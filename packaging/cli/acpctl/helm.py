"""Every command acpctl runs that can CHANGE something — helm, and four kubectl writes.

WHY THIS FILE EXISTS AT ALL, RATHER THAN A FEW LINES IN cluster.py. `cluster.py` holds a
read-verb allow-list and refuses everything else, and `tests/test_packaging_doctor.py` asserts
that refusal against a dozen mutating verbs. That guarantee is the reason `acpctl doctor` and
`acpctl status` are safe to run against production from a laptop, and widening the list to let
`install` through would retire it for every command at once — including the two that promise, in
their own help text, to change nothing. So the mutation lives here, behind its own narrower
allow-list, and the read-only promise stays exactly as strong as it was.

WHAT IS PERMITTED, AND WHY EACH ONE.

  helm install/upgrade    the install itself; `upgrade --install` is what makes it idempotent
  helm uninstall          the removal
  helm get/status/list/history   reads: does this release exist, did it land, what is in it
  helm template           the render, for a dry run that touches no cluster

  kubectl get                     reads
  kubectl logs job/<name>         the evidence a backup or restore actually produced
  kubectl create namespace        the install target, when it does not exist yet
  kubectl create job --from=cronjob/<name>   running the chart's backup CronJob NOW
  kubectl apply -f -              the install-state ConfigMap, and the chart's own restore Job —
                                  both from a manifest built here or rendered by `helm template`
  kubectl scale deployment        quiescing the application for a restore, and putting it back
  kubectl delete configmap/pvc    the install state, and PVCs the release owns — both narrowed
                                  by name or by label selector below

Everything else raises. `helm rollback` in particular is absent even though it is a helm
subcommand acpctl will eventually need: rollback is a phase-5 command that does not exist yet,
and an allow-list that already permits the verbs of unimplemented features is not an allow-list.

WHAT `backup` AND `restore` ADDED, AND WHY EACH IS NARROWER THAN IT LOOKS. Four entries above
arrived with those two commands, and the widening is the part of that change worth reviewing:

  create job    ONLY with `--from=cronjob/<name>`. A bare `kubectl create job` would let acpctl
                invent a workload out of arguments it assembled; `--from` copies the pod template
                out of an object the CHART rendered, so what runs is the chart's, sourced from the
                cluster, and acpctl chooses only when. A `create job` with no `--from` is refused.
  logs          ONLY for a `job/<name>` target, never a pod, a deployment or `-l`. The backup and
                restore Jobs print what they did — the dump's name, its object count, the table
                count after a restore — and a command that ran them and could not read that would
                be reporting its own exit status as the result. Pod logs in general are a much
                wider read (they carry application data); this is the two Jobs' own output.
  apply -f -    unchanged in mechanism, WIDENED IN SOURCE, and this is the honest cost: the input
                may now also be a `helm template -s` render of the chart's restore Job, not only
                the ConfigMap this file builds. Still stdin-only, so acpctl cannot be pointed at a
                path — but the manifest is no longer one this module authored end to end. It is
                the chart's own object, rendered from the RELEASE's values (`helm get values`), so
                it matches what is installed rather than what acpctl guessed.
  scale         ONLY Deployments, never `--all`, and always with an explicit `--replicas`. This
                one is genuinely broad — scaling the wrong Deployment to zero is an outage — and
                the guard cannot see WHICH deployments a caller picked. So the bound is split:
                the guard bounds the KIND and forbids `--all`, and `backup.py` only ever names
                Deployments it read back from `app.kubernetes.io/instance=<release>`. That second
                half is a caller discipline, asserted by a test, not something this guard proves.

THE DELETE GUARD IS RESOURCE-SCOPED, WHICH THE HELM ONE DOES NOT NEED TO BE. `helm uninstall`
can only remove what a release owns. `kubectl delete` can remove anything the operator's
kubeconfig can reach, and "uninstall deleted the wrong namespace's database" is a failure with no
undo. So delete is permitted only for the install-state ConfigMap BY NAME, and for
PersistentVolumeClaims BY LABEL SELECTOR — never a bare name, never `--all`.

THE RUNNER IS INJECTABLE, AND THAT IS A TESTABILITY DECISION WITH TEETH. Every command goes
through one callable, defaulting to subprocess. A test supplies a fake that records argv and
answers from a fixture, so the whole of install and uninstall — including the refusals, the
idempotence and the interrupted-install path — is exercised with no cluster, no helm on PATH and
no network. Without it the only honest test of an installer is one that installs something, which
means the interesting cases (helm dies halfway; the release does not come up; the namespace
already holds someone else's ACP) get tested by nobody.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any, Callable

# The one ConfigMap acpctl writes, and the only object it deletes by name. Named rather than
# derived from the release, because `acpctl status`/`uninstall` have to find it in a namespace
# without already knowing which release put it there.
STATE_CONFIGMAP = "acp-installation"

# The key inside that ConfigMap. One key holding one JSON document, rather than a field per
# entry: the state is a nested structure with a history list, and flattening it into ConfigMap
# keys would make every reader reassemble it differently.
STATE_KEY = "installation.json"

# Helm's own label for the release that owns an object. Used to scope PVC deletion, so an
# uninstall can only ever remove volumes belonging to the release named on the command line.
RELEASE_LABEL = "app.kubernetes.io/instance"

HELM_SUBCOMMANDS = frozenset({
    "install", "upgrade", "uninstall", "get", "status", "list", "template", "history",
})

# kubectl verbs, split so the guard can say which kind of permission a refusal fell foul of and
# so a reader can see at a glance exactly which writes exist.
KUBECTL_READ_VERBS = frozenset({"get", "version", "api-resources", "logs"})
KUBECTL_WRITE_VERBS = frozenset({"create", "apply", "delete", "scale"})

# Resources `kubectl create` may make. The namespace is the install target; the ConfigMap is the
# install state; the Job is the chart's backup CronJob run now, and ONLY via `--from=cronjob/…`
# (see check_kubectl). Nothing else — the chart's objects are helm's business, and a `kubectl
# create` of one would be an object helm does not know it owns and will not clean up.
CREATABLE = frozenset({"namespace", "ns", "configmap", "cm", "job", "jobs"})

# Resources `kubectl scale` may resize. Deployments only: the API and worker tiers are what a
# restore has to quiesce, and StatefulSets, ReplicaSets and the rest are not this chart's shape.
SCALABLE = frozenset({"deployment", "deployments", "deploy"})

# Resources `kubectl delete` may remove, each with its own narrowing below.
DELETABLE = frozenset({"configmap", "cm", "pvc", "persistentvolumeclaim", "persistentvolumeclaims"})

# Flags that consume the next argument. Needed so the guard can tell a RESOURCE from a flag's
# value: in `delete pvc -n acp -l app=x` the namespace is not a positional, and a guard that
# thought it was would either refuse a legal command or, worse, read `-n` values as the thing
# being deleted.
VALUE_FLAGS = frozenset({
    "-n", "--namespace", "-o", "--output", "-l", "--selector", "-f", "--filename",
    "--context", "--kube-context", "--kubeconfig", "--timeout", "--set", "--values",
    "--wait-for-jobs", "--description", "--history-max",
    # backup/restore: `-s` selects one template out of a `helm template` render, `--replicas`
    # takes a count, and `-c` a container. Absent from this set they would read as POSITIONALS,
    # so `scale deployment/x --replicas 0` would look like a scale of a resource called "0".
    "-s", "--show-only", "--replicas", "-c", "--container", "--tail", "--since",
})

# helm's own default is 5 minutes, which is short for a migration Job on a large database and is
# the difference between "the install failed" and "the install was still running". 10 minutes is
# a starting point an operator can raise with --timeout, not a measurement.
DEFAULT_TIMEOUT_SECONDS = 600

# The subprocess timeout is deliberately longer than the helm --timeout it wraps: killing helm
# from the outside leaves the release in whatever state it had reached and acpctl unable to say
# what that was, whereas letting helm hit its own timeout gets a release status back.
_SUBPROCESS_MARGIN_SECONDS = 120


class ForbiddenCommand(RuntimeError):
    """A caller tried to run something outside the allow-list.

    A programming error, not an operator error, and raised loudly for the same reason
    `cluster.ForbiddenVerb` is: the alternative is a future edit quietly widening what acpctl can
    do to a cluster, which is precisely what PRD S22 forbids happening by degrees.
    """


class ToolUnavailable(RuntimeError):
    """helm or kubectl is not on PATH. Distinct from a command that ran and failed — nothing was
    attempted, so nothing was changed, and the operator's fix is different."""


class CommandFailed(RuntimeError):
    """A permitted command ran and returned non-zero.

    Carries the result so the caller can decide whether the failure is fatal (helm upgrade) or
    merely unknown (a status read), because those lead to different exit codes.
    """

    def __init__(self, result: "CommandResult"):
        self.result = result
        super().__init__(result.summary())


@dataclass
class CommandResult:
    argv: list[str]
    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def summary(self) -> str:
        message = (self.stderr or self.stdout or "").strip().splitlines()
        detail = message[0] if message else f"exit {self.returncode}"
        return f"{' '.join(self.argv[:3])}: {detail}"

    def json(self) -> Any:
        return json.loads(self.stdout)


def subprocess_runner(argv: list[str], *, stdin: str | None = None,
                      timeout: int = DEFAULT_TIMEOUT_SECONDS) -> CommandResult:
    """The default runner: actually run it.

    Missing tools raise rather than returning a non-zero result, because "helm is not installed"
    and "helm said no" are different answers to the operator and only one of them says anything
    about the cluster.
    """
    if shutil.which(argv[0]) is None:
        raise ToolUnavailable(
            f"{argv[0]} is not on PATH. acpctl installs through helm and reads the cluster "
            f"through kubectl so that it inherits your kubeconfig, context and credentials.")
    try:
        proc = subprocess.run(argv, input=stdin, capture_output=True, text=True,
                              timeout=timeout + _SUBPROCESS_MARGIN_SECONDS)
    except subprocess.TimeoutExpired as exc:
        raise ToolUnavailable(
            f"{argv[0]} did not return within {timeout + _SUBPROCESS_MARGIN_SECONDS}s: "
            f"{' '.join(argv[:3])}. The release may be mid-change; run `acpctl status` before "
            f"retrying.") from exc
    except OSError as exc:
        raise ToolUnavailable(f"could not run {argv[0]}: {exc}") from exc
    return CommandResult(argv=list(argv), returncode=proc.returncode,
                         stdout=proc.stdout or "", stderr=proc.stderr or "")


def _positionals(args: list[str]) -> list[str]:
    """The non-flag arguments, with flag VALUES skipped. See VALUE_FLAGS for why that matters."""
    out: list[str] = []
    skip = False
    for arg in args:
        if skip:
            skip = False
            continue
        if arg.startswith("-"):
            if arg in VALUE_FLAGS:
                skip = True
            continue
        out.append(arg)
    return out


def check_helm(args: list[str]) -> None:
    """Refuse any helm subcommand outside the allow-list.

    The subcommand must be args[0]. Insisting on that rather than scanning for the first non-flag
    argument closes the hole `cluster.run` has to defend against explicitly — with a global flag
    in front, "the first thing that does not start with a dash" is the flag's VALUE, not the verb.
    Callers here build their own argv, so requiring the verb first costs nothing.
    """
    if not args:
        raise ForbiddenCommand("refusing to run helm with no subcommand")
    verb = args[0]
    if verb.startswith("-"):
        raise ForbiddenCommand(
            f"the helm subcommand must be the first argument; got {verb!r}. A guard that scanned "
            f"for it could be walked past with a global flag.")
    if verb not in HELM_SUBCOMMANDS:
        raise ForbiddenCommand(
            f"acpctl may only run helm {', '.join(sorted(HELM_SUBCOMMANDS))}; refused {verb!r}. "
            f"Commands acpctl has not implemented do not get their verbs pre-authorised.")


def check_kubectl(args: list[str]) -> None:
    """Refuse any kubectl call that is not a read or one of the four narrow writes."""
    if not args:
        raise ForbiddenCommand("refusing to run kubectl with no verb")
    verb = args[0]
    if verb.startswith("-"):
        raise ForbiddenCommand(
            f"the kubectl verb must be the first argument; got {verb!r}.")
    if verb == "logs":
        # NARROWED TO THE TWO JOBS' OWN OUTPUT. `kubectl logs` in general reads application
        # containers, whose output carries document names, user identifiers and whatever else the
        # application logged — a far wider read than anything else on this list. What backup and
        # restore need is one Job's stdout, and `job/<name>` is the only form that can express
        # that. A pod name, a deployment, or a `-l` selector would each admit the general case.
        targets = [a for a in _positionals(args)[1:]]
        if len(targets) != 1 or not targets[0].startswith("job/"):
            raise ForbiddenCommand(
                f"acpctl may only read `kubectl logs job/<name>`; refused "
                f"{targets or '(no target)'}. Reading arbitrary pod logs is the support bundle's "
                f"job, where every line goes through the redactor first.")
        return
    if verb in KUBECTL_READ_VERBS:
        return
    if verb not in KUBECTL_WRITE_VERBS:
        raise ForbiddenCommand(
            f"acpctl may run kubectl {', '.join(sorted(KUBECTL_READ_VERBS | KUBECTL_WRITE_VERBS))} "
            f"only; refused {verb!r}. Everything acpctl changes in a cluster is changed by helm, "
            f"which knows what the release owns.")

    rest = _positionals(args)[1:]
    resource = (rest[0] if rest else "").lower()

    if verb == "create":
        if resource not in CREATABLE:
            raise ForbiddenCommand(
                f"acpctl may only `kubectl create` {', '.join(sorted(CREATABLE))}; refused "
                f"{resource or '(nothing)'!r}. The release's own objects belong to helm — one "
                f"created behind its back is one it will not upgrade and will not clean up.")
        if resource in {"job", "jobs"}:
            # `--from` IS THE WHOLE PERMISSION. With it, the Job's pod template is copied from a
            # CronJob the chart rendered — acpctl decides WHEN a backup runs and nothing about
            # WHAT it runs. Without it, `kubectl create job --image=... -- <command>` would let
            # this tool run an arbitrary container, with the release's service account, inside
            # the namespace holding the database. That is not a backup command; it is a shell.
            source = next((a.split("=", 1)[1] for a in args
                           if a.startswith("--from=")), None)
            if not source:
                raise ForbiddenCommand(
                    "acpctl may only `kubectl create job --from=cronjob/<name>`; refused a Job "
                    "created from arguments. What runs must come from an object the chart "
                    "rendered, not from a command line this tool assembled.")
            if not source.startswith("cronjob/"):
                raise ForbiddenCommand(
                    f"`kubectl create job --from` must name a cronjob; refused {source!r}.")
        return

    if verb == "apply":
        # Apply is permitted ONLY from stdin. Two things are ever piped into it: the install-state
        # ConfigMap this module builds in state_manifest(), and the chart's restore Job as
        # rendered by `helm template -s` from the RELEASE's own values. Allowing `-f <path>` would
        # make acpctl a general-purpose applier of whatever a caller pointed it at, which is the
        # difference between a tool that installs one chart and a tool that applies YAML.
        if "-f" not in args and "--filename" not in args:
            raise ForbiddenCommand("`kubectl apply` needs -f -; refused an apply with no input")
        idx = args.index("-f") if "-f" in args else args.index("--filename")
        if idx + 1 >= len(args) or args[idx + 1] != "-":
            raise ForbiddenCommand(
                "acpctl may only `kubectl apply -f -`, piping a manifest it built itself; "
                "refused an apply reading from a path.")
        return

    if verb == "scale":
        # `kind/name` as well as `kind name`, because scaling one Deployment back to its own
        # replica count is the ordinary case and `deployment/acp-api` is how it is spelled.
        kind = resource.split("/", 1)[0]
        if kind not in SCALABLE:
            raise ForbiddenCommand(
                f"acpctl may only `kubectl scale` {', '.join(sorted(SCALABLE))}; refused "
                f"{resource or '(nothing)'!r}.")
        if "--all" in args:
            raise ForbiddenCommand(
                "refusing `kubectl scale --all`: a restore quiesces the release it names, not "
                "every workload that happens to share the namespace.")
        if not any(a == "--replicas" or a.startswith("--replicas=") for a in args):
            raise ForbiddenCommand(
                "refusing a `kubectl scale` with no --replicas: the count is the whole of what "
                "this command does, and defaulting it would be this tool choosing a topology.")
        return

    # delete
    if resource not in DELETABLE:
        raise ForbiddenCommand(
            f"acpctl may only `kubectl delete` {', '.join(sorted(DELETABLE))}; refused "
            f"{resource or '(nothing)'!r}. Removing a release's workloads is `helm uninstall`, "
            f"which removes what the release owns and nothing else.")
    if "--all" in args:
        raise ForbiddenCommand(
            "refusing `kubectl delete --all`: an uninstall must name what it removes, or it "
            "removes whatever else happens to be in the namespace.")
    if resource in {"configmap", "cm"}:
        named = rest[1:]
        if named != [STATE_CONFIGMAP]:
            raise ForbiddenCommand(
                f"acpctl may only delete the ConfigMap it wrote ({STATE_CONFIGMAP}); refused "
                f"{named or '(unnamed)'}.")
        return
    # PVCs, by selector only. A bare name is refused because the caller would be asserting
    # ownership rather than demonstrating it, and a PVC holds the one thing an uninstall cannot
    # put back.
    if "-l" not in args and "--selector" not in args:
        raise ForbiddenCommand(
            "refusing to delete PersistentVolumeClaims without a label selector: an uninstall "
            "may only remove volumes the release owns, and a bare name does not establish that.")
    if len(rest) > 1:
        raise ForbiddenCommand(
            f"refusing to delete named PersistentVolumeClaims ({', '.join(rest[1:])}); the "
            f"selector is what scopes the deletion to this release.")


@dataclass
class ReleaseState:
    """What helm says about a release, with "could not tell" kept separate from "not there".

    `exists is None` is the outcome that matters. An install that reads "no release here" from a
    failed status call would happily install over one, and an uninstall reading the same thing
    would report there was nothing to remove — both are the "success because nothing was
    observed" failure this command set is built to avoid.
    """

    exists: bool | None = None
    status: str = ""
    revision: int | None = None
    chart: str = ""
    reason: str = ""


@dataclass
class Helm:
    """The mutating client: helm plus the four kubectl writes, over one injectable runner."""

    runner: Callable[..., CommandResult] = subprocess_runner
    context: str | None = None
    timeout: int = DEFAULT_TIMEOUT_SECONDS
    # Every argv this instance ran, in order. Not a debugging aid — it is what `--json` reports
    # as the record of what an install actually did, and what the tests assert a preview did NOT
    # do. A destructive command that cannot say what it ran is one nobody can audit.
    log: list[list[str]] = field(default_factory=list)

    # ── plumbing ─────────────────────────────────────────────────────────────

    def helm(self, args: list[str], *, stdin: str | None = None,
             check: bool = False) -> CommandResult:
        check_helm(args)
        argv = ["helm"]
        if self.context:
            argv += ["--kube-context", self.context]
        argv += args
        self.log.append(argv)
        result = self.runner(argv, stdin=stdin, timeout=self.timeout)
        if check and not result.ok:
            raise CommandFailed(result)
        return result

    def kubectl(self, args: list[str], *, stdin: str | None = None,
                check: bool = False) -> CommandResult:
        check_kubectl(args)
        argv = ["kubectl"]
        if self.context:
            argv += ["--context", self.context]
        argv += args
        self.log.append(argv)
        result = self.runner(argv, stdin=stdin, timeout=self.timeout)
        if check and not result.ok:
            raise CommandFailed(result)
        return result

    def mutations(self) -> list[list[str]]:
        """The subset of the log that could have changed something.

        Derived from the same allow-list the guard uses rather than from a second list of
        "dangerous-looking" strings, so a new permitted write is counted here by construction —
        a preview that quietly stopped noticing one class of mutation would be exactly as wrong
        as one that performed it.
        """
        out = []
        for argv in self.log:
            if not argv:
                continue
            tool, rest = argv[0], [a for a in argv[1:]]
            # Skip the global flag pair this class prepends.
            if rest[:1] in (["--kube-context"], ["--context"]):
                rest = rest[2:]
            verb = rest[0] if rest else ""
            if tool == "helm" and verb in {"install", "upgrade", "uninstall"}:
                out.append(argv)
            elif tool == "kubectl" and verb in KUBECTL_WRITE_VERBS:
                out.append(argv)
        return out

    # ── reads ────────────────────────────────────────────────────────────────

    def release_state(self, release: str, namespace: str) -> ReleaseState:
        result = self.helm(["status", release, "-n", namespace, "-o", "json"])
        if not result.ok:
            text = (result.stderr or result.stdout or "").lower()
            if "not found" in text or "release: not found" in text:
                return ReleaseState(exists=False, reason="helm reports no such release")
            return ReleaseState(exists=None, reason=result.summary())
        try:
            payload = result.json()
        except (json.JSONDecodeError, ValueError) as exc:
            return ReleaseState(exists=None, reason=f"unparseable JSON from helm status: {exc}")
        info = payload.get("info") or {}
        return ReleaseState(exists=True, status=info.get("status", ""),
                            revision=payload.get("version"),
                            chart=((payload.get("chart") or {}).get("metadata") or {}).get("name", ""))

    def releases(self, namespace: str) -> list[dict] | None:
        """Every helm release in the namespace, or None when the list could not be read.

        None rather than [] on failure, because "no other release is here" is the answer that
        lets an install proceed and it must not be produced by a call that did not work.
        """
        result = self.helm(["list", "-n", namespace, "-o", "json"])
        if not result.ok:
            return None
        try:
            payload = result.json()
        except (json.JSONDecodeError, ValueError):
            return None
        return payload if isinstance(payload, list) else None

    def namespace_exists(self, namespace: str) -> bool | None:
        result = self.kubectl(["get", "namespace", namespace, "-o", "json"])
        if result.ok:
            return True
        if "notfound" in (result.stderr or "").lower().replace(" ", ""):
            return False
        return None

    def read_state(self, namespace: str) -> tuple[dict | None, str]:
        """The install-state document, and why it is absent when it is.

        Returns `(state, reason)`. `(None, "")` means definitely nothing recorded here;
        `(None, "<reason>")` means the read did not work, which is a different answer and the
        caller must not treat it as an empty namespace.
        """
        result = self.kubectl(
            ["get", "configmap", STATE_CONFIGMAP, "-n", namespace, "-o", "json"])
        if not result.ok:
            text = (result.stderr or "").lower().replace(" ", "")
            if "notfound" in text:
                return None, ""
            return None, result.summary()
        try:
            payload = result.json()
        except (json.JSONDecodeError, ValueError) as exc:
            return None, f"unparseable ConfigMap JSON: {exc}"
        raw = (payload.get("data") or {}).get(STATE_KEY)
        if raw is None:
            return None, f"{STATE_CONFIGMAP} exists but has no {STATE_KEY} key"
        try:
            return json.loads(raw), ""
        except json.JSONDecodeError as exc:
            return None, f"{STATE_CONFIGMAP}/{STATE_KEY} is not valid JSON: {exc}"

    def owned_pvcs(self, release: str, namespace: str) -> tuple[list[str] | None, str]:
        """PVCs carrying this release's instance label, or (None, reason) when unreadable."""
        result = self.kubectl(["get", "pvc", "-n", namespace, "-l",
                               f"{RELEASE_LABEL}={release}", "-o", "json"])
        if not result.ok:
            return None, result.summary()
        try:
            payload = result.json()
        except (json.JSONDecodeError, ValueError) as exc:
            return None, f"unparseable JSON: {exc}"
        return [item["metadata"]["name"] for item in payload.get("items", [])], ""

    def backup_cronjob(self, release: str, namespace: str) -> tuple[dict | None, str]:
        """The release's backup CronJob, found BY LABEL rather than by a name computed here.

        `(None, "")` means definitely not there; `(None, reason)` means the read did not work.

        WHY NOT `<release>-backup`. The chart names it `<fullname>-backup`, and the fullname is
        NOT the release name whenever `fullnameOverride` or `nameOverride` is set, or the release
        name already contains the chart's. A lookup by the computed name would then find nothing
        and report "this installation takes no backups" about one that does — the wrong answer in
        the worse direction, since the operator's next move is to stop looking. The instance and
        component labels are on the object itself, so this asks the cluster which object it is
        rather than predicting what it was called.
        """
        result = self.kubectl(["get", "cronjob", "-n", namespace, "-l",
                               f"{RELEASE_LABEL}={release},app.kubernetes.io/component=backup",
                               "-o", "json"])
        if not result.ok:
            return None, result.summary()
        try:
            items = (result.json() or {}).get("items") or []
        except (json.JSONDecodeError, ValueError) as exc:
            return None, f"unparseable CronJob JSON: {exc}"
        if not items:
            return None, ""
        if len(items) > 1:
            names = ", ".join(sorted((i.get("metadata") or {}).get("name", "?") for i in items))
            return None, (f"{len(items)} backup CronJobs carry this release's labels ({names}); "
                          f"refusing to guess which one this installation's backups come from")
        return items[0], ""

    def job_state(self, name: str, namespace: str) -> tuple[str, str]:
        """`("succeeded"|"failed"|"running"|"unknown", reason)` for one Job.

        "unknown" is a distinct answer and not folded into "running", because a command that
        cannot read a Job must not go on waiting for it as though it had — that is how a wait
        loop becomes a timeout with nothing to report.
        """
        result = self.kubectl(["get", "job", name, "-n", namespace, "-o", "json"])
        if not result.ok:
            if "notfound" in (result.stderr or "").lower().replace(" ", ""):
                return "unknown", f"no Job {name} in {namespace}"
            return "unknown", result.summary()
        try:
            status = (result.json() or {}).get("status") or {}
        except (json.JSONDecodeError, ValueError) as exc:
            return "unknown", f"unparseable Job JSON: {exc}"
        for condition in status.get("conditions") or []:
            if condition.get("status") != "True":
                continue
            if condition.get("type") == "Complete":
                return "succeeded", ""
            if condition.get("type") == "Failed":
                return "failed", condition.get("message") or condition.get("reason") or ""
        if status.get("succeeded"):
            return "succeeded", ""
        return "running", ""

    def jobs_with_label(self, selector: str, namespace: str) -> tuple[list[dict] | None, str]:
        """Jobs carrying a label selector, newest first by creation timestamp."""
        result = self.kubectl(["get", "job", "-n", namespace, "-l", selector, "-o", "json"])
        if not result.ok:
            return None, result.summary()
        try:
            items = (result.json() or {}).get("items") or []
        except (json.JSONDecodeError, ValueError) as exc:
            return None, f"unparseable JSON: {exc}"
        return sorted(items,
                      key=lambda i: (i.get("metadata") or {}).get("creationTimestamp") or "",
                      reverse=True), ""

    def job_log(self, name: str, namespace: str) -> tuple[str, str]:
        """One Job's own output — the only logs acpctl reads. See check_kubectl."""
        result = self.kubectl(["logs", f"job/{name}", "-n", namespace])
        if not result.ok:
            return "", result.summary()
        return result.stdout, ""

    def deployments_owned(self, release: str, namespace: str
                          ) -> tuple[list[tuple[str, int]] | None, str]:
        """`(name, spec.replicas)` for the Deployments this release owns.

        THE ONLY SOURCE OF NAMES `scale_deployment` IS EVER GIVEN. helm.check_kubectl bounds the
        KIND a scale may touch and forbids `--all`; it cannot know which Deployments belong to
        this release. This query is the other half of that bound — ownership demonstrated by the
        release's own instance label rather than asserted by a caller — and
        tests/test_packaging_backup.py asserts nothing else ever reaches the scale call.
        """
        result = self.kubectl(["get", "deployment", "-n", namespace, "-l",
                               f"{RELEASE_LABEL}={release}", "-o", "json"])
        if not result.ok:
            return None, result.summary()
        try:
            items = (result.json() or {}).get("items") or []
        except (json.JSONDecodeError, ValueError) as exc:
            return None, f"unparseable JSON: {exc}"
        out = []
        for item in items:
            name = (item.get("metadata") or {}).get("name")
            replicas = (item.get("spec") or {}).get("replicas")
            if name is not None:
                out.append((name, int(replicas) if replicas is not None else 1))
        return sorted(out), ""

    def release_values(self, release: str, namespace: str) -> tuple[dict | None, str]:
        """The values the release was installed with.

        WHY NOT `build_values(document)`: because the running release is what a restore Job has to
        match. An install may have carried a release manifest's digests, a `--set`, or a second
        values file, and a Job rendered from the document alone would differ from the workloads it
        is restoring underneath — a different image, a different security context, a different
        secret name. helm knows what was actually supplied; this asks it.
        """
        result = self.helm(["get", "values", release, "-n", namespace, "-o", "json"])
        if not result.ok:
            return None, result.summary()
        try:
            payload = result.json()
        except (json.JSONDecodeError, ValueError) as exc:
            return None, f"unparseable JSON from helm get values: {exc}"
        # helm prints `null` for a release installed with no user values at all.
        return (payload if isinstance(payload, dict) else {}), ""

    def render_template(self, release: str, chart: str, namespace: str, *,
                        values_path: str, show_only: str, sets: list[str]
                        ) -> tuple[str, str]:
        """`helm template -s <one template>` — renders, contacts no API server, changes nothing."""
        args = ["template", release, chart, "-n", namespace,
                "--values", values_path, "-s", show_only]
        for item in sets:
            args += ["--set", item]
        result = self.helm(args)
        if not result.ok:
            return "", (result.stderr or result.stdout or "").strip()
        return result.stdout, ""

    def manifest_objects(self, release: str, namespace: str) -> tuple[list[str] | None, str]:
        """`kind/name` for everything the release owns, for the uninstall preview.

        Read from helm rather than from `kubectl get`, because helm's manifest is the definition
        of what the release owns — a label query would also catch objects somebody else labelled,
        and an uninstall preview that overstates what will be removed is as misleading as one
        that understates it.
        """
        result = self.helm(["get", "manifest", release, "-n", namespace])
        if not result.ok:
            return None, result.summary()
        return _kinds_and_names(result.stdout), ""

    # ── writes ───────────────────────────────────────────────────────────────

    def create_namespace(self, namespace: str) -> CommandResult:
        return self.kubectl(["create", "namespace", namespace], check=True)

    def upgrade_install(self, release: str, namespace: str, chart: str, *,
                        values_path: str, atomic: bool = True) -> CommandResult:
        """`helm upgrade --install` — the same command for a first install and a re-run.

        --atomic, so a failed install ROLLS BACK rather than leaving half a release behind. The
        alternative is a namespace containing some of ACP, which is the state that makes the next
        install's "is something already here?" question unanswerable.

        --wait, because the exit status of a helm install without it means "the objects were
        accepted", not "the application came up" — and reporting the first as the second is how
        an installer comes to claim success for a release that never started.
        """
        args = ["upgrade", "--install", release, chart,
                "-n", namespace,
                "--values", values_path,
                "--wait", "--timeout", f"{self.timeout}s"]
        if atomic:
            args.append("--atomic")
        return self.helm(args, check=True)

    def uninstall(self, release: str, namespace: str) -> CommandResult:
        return self.helm(["uninstall", release, "-n", namespace, "--wait",
                          "--timeout", f"{self.timeout}s"], check=True)

    def write_state(self, namespace: str, state: dict) -> CommandResult:
        return self.kubectl(["apply", "-n", namespace, "-f", "-"],
                            stdin=json.dumps(state_manifest(namespace, state), indent=2),
                            check=True)

    def delete_state(self, namespace: str) -> CommandResult:
        return self.kubectl(["delete", "configmap", STATE_CONFIGMAP, "-n", namespace,
                             "--ignore-not-found"], check=True)

    def create_job_from_cronjob(self, name: str, cronjob: str, namespace: str) -> CommandResult:
        """Run the chart's backup CronJob now. The pod template comes from the CronJob, not from
        here — see check_kubectl for why `--from` is the whole of the permission."""
        return self.kubectl(["create", "job", name, f"--from=cronjob/{cronjob}",
                             "-n", namespace], check=True)

    def apply_manifest(self, manifest: str, namespace: str) -> CommandResult:
        """Apply a manifest from stdin. The only callers are `write_state` above and the restore,
        which pipes the chart's own `helm template -s` render."""
        return self.kubectl(["apply", "-n", namespace, "-f", "-"], stdin=manifest, check=True)

    def scale_deployment(self, name: str, replicas: int, namespace: str) -> CommandResult:
        """Resize ONE Deployment, named from `deployments_owned` and never from anywhere else."""
        return self.kubectl(["scale", f"deployment/{name}", f"--replicas={replicas}",
                             "-n", namespace], check=True)

    def delete_owned_pvcs(self, release: str, namespace: str) -> CommandResult:
        return self.kubectl(["delete", "pvc", "-n", namespace, "-l",
                             f"{RELEASE_LABEL}={release}"], check=True)


def state_manifest(namespace: str, state: dict) -> dict:
    """The ConfigMap carrying the install state.

    NOT A HELM-MANAGED OBJECT, deliberately. If the chart rendered it, `helm uninstall` would
    delete it as part of the release — and the record of what was installed would vanish at the
    exact moment somebody most needs to know what was there. acpctl writes it, and removes it
    itself after recording the uninstall.
    """
    return {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {
            "name": STATE_CONFIGMAP,
            "namespace": namespace,
            "labels": {
                "app.kubernetes.io/part-of": "acp",
                "app.kubernetes.io/managed-by": "acpctl",
            },
        },
        "data": {STATE_KEY: json.dumps(state, indent=2, sort_keys=False)},
    }


def _kinds_and_names(manifest_text: str) -> list[str]:
    """`kind/name` out of a multi-document manifest.

    Deliberately a line scan rather than a YAML parse: PyYAML is optional in the air-gapped
    bundle (see values.render_values_yaml), and this feeds a human-readable preview where an
    approximate list is far better than a hard dependency. Both fields are top-level and
    unindented for `kind`, which is what makes the scan reliable enough for the purpose.
    """
    objects: list[str] = []
    kind: str | None = None
    name: str | None = None
    for line in manifest_text.splitlines():
        if line.startswith("---"):
            if kind:
                objects.append(f"{kind}/{name or '?'}")
            kind = name = None
            continue
        if line.startswith("kind:"):
            kind = line.split(":", 1)[1].strip()
        elif line.startswith("  name:") and name is None:
            name = line.split(":", 1)[1].strip()
    if kind:
        objects.append(f"{kind}/{name or '?'}")
    return objects
