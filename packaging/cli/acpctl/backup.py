"""`acpctl backup` and `acpctl restore` — run the chart's own Jobs, and report what they did.

WHAT THESE ARE NOT: a second implementation of backup. The dump is taken by
`packaging/chart/acp/templates/backup-cronjob.yaml` and the restore by `templates/restore-job.yaml`,
both of which run on the disposable reference cluster on every packaging PR. Nothing here opens a
database, chooses a retention or invents a pod. What it adds is the three things an operator cannot
get from `kubectl` in one line:

  * RUNNING THE BACKUP NOW, off its schedule, without hand-copying a pod template. A `kubectl
    create job --from=cronjob/…` is one line, but knowing the CronJob's name, that it exists at
    all, and that the release it belongs to is the one you meant is three reads first.
  * READING THE RESULT RATHER THAN THE EXIT STATUS. `kubectl create job` exits 0 when the Job was
    ACCEPTED. The backup's own output — the dump's name, its size, its restorable-object count —
    is in the Job's log, and a command that returned before reading it would be reporting that
    Kubernetes accepted a request, which is not a backup.
  * THE RESTORE'S PRECONDITION, DONE PROPERLY. The restore Job refuses while any other session is
    on the database, which is correct and is also the step operators skip. `--quiesce` scales the
    release's own Deployments to zero, records their replica counts where an interrupted run can
    find them again, restores, and puts them back.

`backup` ACTS; `restore` PREVIEWS. That asymmetry is deliberate and it is not inconsistency with
`install`/`uninstall`, which both preview: a preview earns its friction where the command destroys
something. A backup writes a file. A restore DROPS AND RECREATES every object in the database, so
it prints what it is about to do, what it will not touch, and changes nothing without `--yes`.

THE RELEASE'S FULL NAME IS READ FROM THE CLUSTER, NOT RECOMPUTED. `restore.confirm` must equal the
chart's `acp.fullname`, and reimplementing helm's fullname rule here would be a second definition
of somebody else's contract — the failure mode ADR 0048 and install.py both name. The backup
CronJob is `<fullname>-backup`, so the fullname is that object's name with the suffix removed:
sourced from the render that actually happened, and wrong only if the CronJob is absent, which is
refused anyway because there would then be no volume to read.

AND THE VALUES COME FROM `helm get values`, NOT FROM THE DOCUMENT. See helm.release_values: a
restore Job rendered from the document alone can differ from the release it is restoring
underneath — different image, different secret name, different security context — because the
install may have carried a release manifest, a `--set`, or a second values file.

WHAT IS STILL NOT PROVEN HERE. Every test in tests/test_packaging_backup.py drives these through
an injected runner that answers the way helm and kubectl are documented to answer, exactly as
install and uninstall are tested. The Jobs themselves are exercised against a real Postgres on the
reference cluster; the orchestration in this file is not. `packaging/docs/lifecycle.md` says so
rather than implying otherwise.
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable

from . import spec as spec_mod
from .helm import STATE_CONFIGMAP, CommandFailed, Helm, ToolUnavailable
from .install import DEFAULT_CHART, EXIT_OK, EXIT_REFUSED, EXIT_USAGE, Outcome

# The chart names the CronJob `<fullname>-backup` and the restore Job
# `<fullname>-restore-<runId>`. Both suffixes live here so the two commands cannot disagree about
# what they are looking for.
CRONJOB_SUFFIX = "-backup"
RESTORE_TEMPLATE = "templates/restore-job.yaml"

# How previous backup Jobs are found. BOTH labels, not just the component: a namespace can hold
# two ACP releases (install.py refuses to ADD one, but an existing pair is a shape this has to read
# correctly), and offering an operator another release's dump filenames is offering them a restore
# from the wrong database.
def _backup_selector(release: str) -> str:
    return f"app.kubernetes.io/instance={release},app.kubernetes.io/component=backup"

# Where an interrupted `--quiesce` leaves its replica counts. A key in the install-state
# ConfigMap rather than a file on the operator's laptop, because the machine that ran the restore
# is not necessarily the one that finds the application scaled to zero afterwards.
QUIESCE_KEY = "quiesce"

# How long to wait for each Job, and how often to ask. A dump of a large database is minutes, not
# seconds; polling every two of them is enough to be responsive without a request per second
# against an API server somebody else is also using.
DEFAULT_BACKUP_TIMEOUT = 900
DEFAULT_RESTORE_TIMEOUT = 1800
POLL_SECONDS = 2

# `wrote /backups/acp-20260908T020000Z.dump (3138 bytes, 9 objects)` — the backup Job's own line.
_WROTE = re.compile(r"^wrote (?P<path>\S+) \((?P<bytes>\d+) bytes, (?P<objects>\d+) objects\)$",
                    re.M)
_RETENTION = re.compile(r"^retention (?P<days>\d+)d, (?P<kept>\d+) backup\(s\)", re.M)
# `restored acp-….dump: 24 table(s) in the public schema`
_RESTORED = re.compile(r"^restored (?P<file>\S+): (?P<tables>\d+) table\(s\)", re.M)


def parse_backup_log(text: str) -> dict:
    """What the backup Job says it did, as a record.

    PARSED RATHER THAN ASSUMED, and the fields are the Job's own words. `acpctl backup --json`
    emits this, which is the machine-readable "backup age" PRD S14 asks for — and it is the Job's
    report of a file it verified with `pg_restore --list`, not this module's belief about one.
    """
    record: dict = {}
    wrote = _WROTE.search(text or "")
    if wrote:
        record["file"] = wrote.group("path").rsplit("/", 1)[-1]
        record["bytes"] = int(wrote.group("bytes"))
        record["objects"] = int(wrote.group("objects"))
    retention = _RETENTION.search(text or "")
    if retention:
        record["retentionDays"] = int(retention.group("days"))
        record["kept"] = int(retention.group("kept"))
    return record


def parse_restore_log(text: str) -> dict:
    record: dict = {}
    restored = _RESTORED.search(text or "")
    if restored:
        record["file"] = restored.group("file")
        record["tables"] = int(restored.group("tables"))
    return record


def _timestamp() -> str:
    return time.strftime("%Y%m%d%H%M%S", time.gmtime())


class _Stop(Exception):
    """A refusal, carried out of the preamble as an Outcome."""

    def __init__(self, outcome: Outcome):
        self.outcome = outcome
        super().__init__(outcome.reason)


def _prepare(document_path: str, *, namespace: str, release_name: str | None, helm: Helm
             ) -> tuple[dict, str, str, str]:
    """`(document, release, fullname, cronjob name)`, or raise `_Stop` with the refusal.

    Shared by both commands because both need the same four facts established in the same order,
    and a restore that checked fewer of them than a backup would be the more dangerous of the two
    running with less certainty.
    """
    if not namespace:
        raise _Stop(Outcome(EXIT_USAGE, reason="a namespace is required (-n/--namespace)"))

    try:
        document = spec_mod.load_document(document_path)
    except (OSError, ValueError) as exc:
        raise _Stop(Outcome(EXIT_USAGE, reason=f"could not read {document_path}: {exc}"))

    # NOT REFUSED FOR AN INVALID DOCUMENT, for uninstall's reason: this acts on something already
    # installed, and a document that has since drifted out of validity is a bad reason to refuse
    # somebody a backup. The document is read for its release name and nothing else.
    release = release_name or (document.get("metadata") or {}).get("name") or "acp"

    state = helm.release_state(release, namespace)
    if state.exists is None:
        raise _Stop(Outcome(EXIT_USAGE, reason=(
            f"could not determine whether release {release!r} exists in {namespace}: "
            f"{state.reason}. Nothing was attempted.")))
    if not state.exists:
        raise _Stop(Outcome(EXIT_REFUSED, reason=(
            f"no helm release {release!r} in namespace {namespace}. There is nothing to back up "
            f"or restore here — check the namespace, or --release-name.")))

    cronjob, reason = helm.backup_cronjob(release, namespace)
    if cronjob is None and reason:
        raise _Stop(Outcome(EXIT_USAGE, reason=(
            f"could not read the backup CronJob in {namespace}: {reason}")))
    if cronjob is None:
        # The name is a guess only when it is missing; see the module docstring. Both commands
        # need it, because a restore reads the volume this CronJob writes.
        raise _Stop(Outcome(EXIT_REFUSED, reason=(
            f"release {release!r} renders no backup CronJob, so this installation takes no "
            f"backups and has no volume to restore from.\n"
            f"The chart ships it disabled. Enable it on the release with three values, two of "
            f"which have no default because they are decisions:\n"
            f"  backup.enabled=true\n"
            f"  backup.schedule=<cron>        the recovery point objective\n"
            f"  backup.retentionDays=<days>   match data.postgres.backupRetentionDays\n")))

    name = (cronjob.get("metadata") or {}).get("name") or ""
    fullname = name[: -len(CRONJOB_SUFFIX)] if name.endswith(CRONJOB_SUFFIX) else release
    return document, release, fullname, name


def job_name_in(manifest: str) -> str:
    """The Job's name as the CHART rendered it, not as this module would have spelled it.

    `templates/restore-job.yaml` builds `<fullname>-restore-<runId>` and then `trunc 63`, because
    that is Kubernetes' limit on a name. Recomputing it here would agree with the chart until a
    long release name or run id crossed 63 characters, at which point this command would poll for
    a Job that does not exist and time out reporting nothing — while the restore ran perfectly.
    So the name is read back out of the manifest that is about to be applied.

    A line scan rather than a YAML parse, for helm._kinds_and_names' reason: PyYAML is optional in
    the air-gapped bundle, and `  name:` under a top-level `metadata:` is unambiguous in a
    single-object render.
    """
    for line in manifest.splitlines():
        if line.startswith("  name:"):
            return line.split(":", 1)[1].strip()
    return ""


def _wait_for_job(helm: Helm, name: str, namespace: str, *, timeout: int,
                  sleep: Callable[[float], None]) -> tuple[str, str]:
    """Poll until the Job finishes, or the timeout. Returns the same triple job_state does.

    A TIMEOUT IS "unknown", NOT "failed". The Job may still be running and may still succeed; the
    only true statement is that this command stopped watching. Reporting it as a failure would
    send an operator to re-run a backup that is in progress, which on a large database is the one
    thing least helpful at that moment.
    """
    deadline = time.monotonic() + timeout
    last = "running"
    while True:
        state, reason = helm.job_state(name, namespace)
        if state in ("succeeded", "failed"):
            return state, reason
        if state == "unknown":
            return state, reason
        last = state
        if time.monotonic() >= deadline:
            return "unknown", (
                f"{name} was still {last} after {timeout}s. It has not failed — this command "
                f"stopped watching. `kubectl -n {namespace} logs job/{name}` when it finishes.")
        sleep(POLL_SECONDS)


def _emit_log(helm: Helm, name: str, namespace: str, echo: Callable[[str], None]) -> str:
    text, reason = helm.job_log(name, namespace)
    if reason:
        echo(f"  (could not read {name}'s log: {reason})")
        return ""
    for line in text.splitlines():
        echo(f"  | {line}")
    return text


# ── backup ────────────────────────────────────────────────────────────────────

def backup(document_path: str, *, namespace: str, release_name: str | None = None,
           wait: bool = True, timeout: int = DEFAULT_BACKUP_TIMEOUT,
           context: str | None = None, helm: Helm | None = None,
           sleep: Callable[[float], None] = time.sleep,
           echo: Callable[[str], None] = print) -> Outcome:
    """Run the chart's backup CronJob now and report what it produced."""
    helm = helm if helm is not None else Helm(context=context)
    try:
        _document, release, _fullname, cronjob_name = _prepare(
            document_path, namespace=namespace, release_name=release_name, helm=helm)
    except _Stop as stop:
        return stop.outcome
    except ToolUnavailable as exc:
        return Outcome(EXIT_USAGE, reason=str(exc))

    job_name = f"{cronjob_name}-{_timestamp()}"

    echo(f"acpctl backup — release {release} in {namespace}")
    echo(f"  running {cronjob_name} now as job/{job_name}")

    try:
        helm.create_job_from_cronjob(job_name, cronjob_name, namespace)
    except CommandFailed as exc:
        return Outcome(EXIT_REFUSED, reason=f"could not start the backup: {exc.result.summary()}")
    except ToolUnavailable as exc:
        return Outcome(EXIT_USAGE, reason=str(exc))

    if not wait:
        return Outcome(EXIT_OK, changed=True,
                       state={"job": job_name, "namespace": namespace, "waited": False},
                       reason=(f"started job/{job_name}. NOT WAITED FOR — this says the Job was "
                               f"accepted, not that a backup exists. "
                               f"`kubectl -n {namespace} logs job/{job_name}` for the result."))

    state, reason = _wait_for_job(helm, job_name, namespace, timeout=timeout, sleep=sleep)
    text = _emit_log(helm, job_name, namespace, echo)
    record = parse_backup_log(text)
    record.update({"job": job_name, "namespace": namespace, "release": release})

    if state == "succeeded":
        if "file" not in record:
            # The Job says Complete and its log does not name a dump. Not a success: the whole
            # point of reading the log is that the exit status cannot tell us a file exists.
            return Outcome(EXIT_REFUSED, state=record, changed=True, reason=(
                f"job/{job_name} completed but its log names no dump file. Something ran that "
                f"was not this chart's backup — read the log above before trusting it."))
        return Outcome(EXIT_OK, state=record, changed=True, reason=(
            f"backed up: {record['file']} ({record['bytes']} bytes, {record['objects']} "
            f"restorable objects). Restore it with:\n"
            f"  acpctl restore {document_path} -n {namespace} --from {record['file']}"))
    if state == "failed":
        return Outcome(EXIT_REFUSED, state=record, changed=True,
                       reason=f"the backup Job failed{': ' + reason if reason else ''}. "
                              f"The log is above; the Job is left in place as the record.")
    return Outcome(EXIT_USAGE, state=record, changed=True, reason=reason or (
        f"could not read the state of job/{job_name}"))


# ── restore ───────────────────────────────────────────────────────────────────

def _recent_dumps(helm: Helm, release: str, namespace: str) -> list[str]:
    """Dump filenames named by the backup Jobs still on the cluster, newest first.

    NOT A LISTING OF THE VOLUME, and the difference matters. The claim's contents can only be read
    by a pod that mounts it, and running one would be this tool inventing a workload — the thing
    `--from=cronjob` exists to avoid. What this reads is what each backup Job REPORTED writing,
    which is bounded by the CronJob's history limits and so is a recent subset, not the whole
    volume. A file missing from here may still be on the claim; the restore Job lists the volume
    itself when it is given a name that is not there.
    """
    jobs, reason = helm.jobs_with_label(_backup_selector(release), namespace)
    if reason or not jobs:
        return []
    seen: list[str] = []
    for job in jobs:
        name = (job.get("metadata") or {}).get("name")
        if not name:
            continue
        text, failed = helm.job_log(name, namespace)
        if failed:
            continue
        record = parse_backup_log(text)
        if record.get("file") and record["file"] not in seen:
            seen.append(record["file"])
    return seen


def _quiesce(helm: Helm, release: str, namespace: str
             ) -> tuple[list[tuple[str, int]] | None, str]:
    """Scale the release's Deployments to zero, returning what they were.

    THE COUNTS ARE READ BEFORE ANYTHING IS SCALED and returned to the caller, which writes them
    down before the first scale happens. An interrupted restore that had already scaled down and
    lost the numbers leaves an application at zero replicas and nobody able to say what it should
    be — which is a worse outage than the one the restore was fixing.
    """
    owned, reason = helm.deployments_owned(release, namespace)
    if owned is None:
        return None, f"could not list the release's Deployments: {reason}"
    if not owned:
        return None, (f"no Deployments carry app.kubernetes.io/instance={release} in {namespace}, "
                      f"so there is nothing to quiesce and ownership cannot be demonstrated. "
                      f"Refusing to scale anything.")
    return owned, ""


def _scale_all(helm: Helm, targets: list[tuple[str, int]], namespace: str,
               echo: Callable[[str], None]) -> str:
    for name, replicas in targets:
        echo(f"  scaling deployment/{name} to {replicas}")
        try:
            helm.scale_deployment(name, replicas, namespace)
        except CommandFailed as exc:
            return f"could not scale deployment/{name}: {exc.result.summary()}"
    return ""


def restore(document_path: str, *, namespace: str, from_file: str | None = None,
            release_name: str | None = None, run_id: str | None = None,
            quiesce: bool = False, assume_yes: bool = False,
            timeout: int = DEFAULT_RESTORE_TIMEOUT, chart_dir: str | Path = DEFAULT_CHART,
            context: str | None = None, helm: Helm | None = None,
            sleep: Callable[[float], None] = time.sleep,
            echo: Callable[[str], None] = print) -> Outcome:
    """Preview — or, with --yes, perform — a restore of one dump into the release's database."""
    helm = helm if helm is not None else Helm(context=context)
    try:
        document, release, fullname, _cronjob = _prepare(
            document_path, namespace=namespace, release_name=release_name, helm=helm)
    except _Stop as stop:
        return stop.outcome
    except ToolUnavailable as exc:
        return Outcome(EXIT_USAGE, reason=str(exc))

    echo(f"acpctl restore — release {release} in {namespace}")

    if not from_file:
        dumps = _recent_dumps(helm, release, namespace)
        lines = "\n".join(f"  {name}" for name in dumps) if dumps else \
            "  (none reported by the backup Jobs still on this cluster)"
        return Outcome(EXIT_USAGE, reason=(
            "--from is required: name the dump to restore.\n"
            "There is deliberately no \"latest\" — after a bad migration the newest backup is "
            "the one you do not want.\n"
            "Dumps the backup Jobs on this cluster reported writing, newest first:\n"
            f"{lines}\n"
            "That is what those Jobs recorded, not a listing of the volume — the CronJob's "
            "history limits bound it. A name that is not on the claim is refused by the restore "
            "Job, which lists what is."))

    run = run_id or f"acpctl-{_timestamp()}"
    job_name = f"{fullname}-restore-{run}"

    # ── the preview, which is also the whole command without --yes ────────────
    data = document.get("data") or {}
    echo("")
    echo("  WHAT THIS REPLACES")
    echo(f"    the release's PostgreSQL database, from {from_file}")
    echo("    every object in it is DROPPED and recreated. Anything written since that dump was")
    echo("    taken is gone — that is what restoring a backup means.")
    echo("")
    echo("  WHAT IT DOES NOT TOUCH")
    echo(f"    object storage ({(data.get('objectStorage') or {}).get('mode', 'not stated')}) — "
         f"remediated documents and artifacts live there (ADR 0010) and are NOT restored to the "
         f"dump's point in time, so afterwards the database and the artifact store disagree "
         f"about anything produced in between.")
    echo(f"    Redis ({(data.get('redis') or {}).get('mode', 'not stated')}) — scan progress and "
         f"worker leases, reconstructable, left as it is.")
    echo("")
    echo("  HOW")
    echo(f"    job/{job_name}, rendered from this release's own values")
    if quiesce:
        echo("    --quiesce: the release's Deployments are scaled to 0 first and put back after")
    else:
        echo("    NOT quiesced. The Job refuses while any other session is on the database, which")
        echo("    is almost certainly the case while the API and workers are running. Re-run with")
        echo("    --quiesce to have that done for you.")
    echo("")

    if not assume_yes:
        return Outcome(EXIT_OK, changed=False, reason=(
            "PREVIEW ONLY — nothing was changed. Re-run with --yes to restore."))

    # ── the render, before anything is changed ────────────────────────────────
    values, reason = helm.release_values(release, namespace)
    if values is None:
        return Outcome(EXIT_USAGE, reason=f"could not read the release's values: {reason}")

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
        # JSON, which helm accepts as a values file because JSON is YAML. Written rather than
        # passed as --set so that a value containing a comma or a dot survives intact.
        json.dump(values, handle)
        values_path = handle.name

    manifest, reason = helm.render_template(
        release, str(chart_dir), namespace, values_path=values_path,
        show_only=RESTORE_TEMPLATE,
        sets=["restore.enabled=true", f"restore.file={from_file}",
              f"restore.runId={run}", f"restore.confirm={fullname}"])
    Path(values_path).unlink(missing_ok=True)
    if reason:
        return Outcome(EXIT_REFUSED, reason=(
            f"the chart refused to render the restore Job:\n{reason}"))

    # THE NAME COMES BACK OUT OF THE MANIFEST. See job_name_in: the chart truncates to 63
    # characters, and a recomputed name would agree until it did not — at which point this would
    # poll for a Job that does not exist while the restore ran perfectly.
    rendered_name = job_name_in(manifest)
    if not rendered_name:
        return Outcome(EXIT_REFUSED, reason=(
            "the rendered restore Job carries no metadata.name; refusing to apply a manifest "
            "whose result this command could not then find."))
    job_name = rendered_name

    # ── quiesce, recording the counts BEFORE the first scale ──────────────────
    restore_to: list[tuple[str, int]] | None = None
    if quiesce:
        prior, why = _quiesce(helm, release, namespace)
        if prior is None:
            return Outcome(EXIT_REFUSED, reason=why)
        # An earlier interrupted run's counts win: the live ones are zero, and scaling "back" to
        # zero afterwards would leave the outage in place.
        recorded, state_reason = helm.read_state(namespace)
        if recorded is None:
            # NO RECORD, NO SCALE-DOWN. Not a technicality: the counts are the only way back, and
            # a run interrupted between the scale and the scale-up leaves an application at zero
            # with nothing on the cluster saying what it was. An installation acpctl did not
            # install has no state ConfigMap, which is a legitimate situation and still not one
            # where this command may take the tiers down.
            why_none = (f" ({state_reason})" if state_reason
                        else " — this release was not installed by acpctl")
            return Outcome(EXIT_REFUSED, reason=(
                f"refusing --quiesce: there is no {STATE_CONFIGMAP} ConfigMap in {namespace} to "
                f"record the replica counts in{why_none}.\n"
                f"Scaling to zero with no record of what the counts were is how a restore turns "
                f"into an outage nobody can undo. Scale the tiers down yourself and re-run "
                f"without --quiesce, or install through `acpctl install` so there is a record."))
        stale = (recorded.get(QUIESCE_KEY) or {}).get("replicas")
        if stale:
            echo("  a previous --quiesce did not finish; using the replica counts it recorded")
            restore_to = [(name, int(count)) for name, count in sorted(stale.items())]
        else:
            restore_to = prior
            recorded[QUIESCE_KEY] = {"replicas": {n: r for n, r in prior}, "job": job_name}
            try:
                helm.write_state(namespace, recorded)
            except (CommandFailed, ToolUnavailable) as exc:
                return Outcome(EXIT_REFUSED, reason=(
                    f"refusing to scale down: the replica counts could not be recorded "
                    f"({exc}). An interrupted restore would leave the application at zero "
                    f"with nothing saying what it was."))
        failed = _scale_all(helm, [(name, 0) for name, _ in restore_to], namespace, echo)
        if failed:
            _scale_all(helm, restore_to, namespace, echo)
            return Outcome(EXIT_REFUSED, changed=True, reason=failed)

    # ── the restore ───────────────────────────────────────────────────────────
    outcome = _run_restore(helm, manifest, job_name, namespace, timeout=timeout, sleep=sleep,
                           echo=echo, from_file=from_file)

    if restore_to is not None:
        failed = _scale_all(helm, restore_to, namespace, echo)
        if failed:
            return Outcome(EXIT_REFUSED, state=outcome.state, changed=True, reason=(
                f"{outcome.reason}\nAND THE APPLICATION IS STILL SCALED DOWN: {failed}. The "
                f"replica counts are in the install state under {QUIESCE_KEY!r}."))
        recorded, _ = helm.read_state(namespace)
        if recorded is not None and QUIESCE_KEY in recorded:
            recorded.pop(QUIESCE_KEY)
            try:
                helm.write_state(namespace, recorded)
            except (CommandFailed, ToolUnavailable):
                echo("  (the quiesce record could not be cleared; it is stale, not harmful)")
    return outcome


def _run_restore(helm: Helm, manifest: str, job_name: str, namespace: str, *, timeout: int,
                 sleep: Callable[[float], None], echo: Callable[[str], None],
                 from_file: str) -> Outcome:
    echo(f"  applying job/{job_name}")
    try:
        helm.apply_manifest(manifest, namespace)
    except CommandFailed as exc:
        return Outcome(EXIT_REFUSED, reason=f"could not create the restore Job: "
                                            f"{exc.result.summary()}")
    except ToolUnavailable as exc:
        return Outcome(EXIT_USAGE, reason=str(exc))

    state, reason = _wait_for_job(helm, job_name, namespace, timeout=timeout, sleep=sleep)
    text = _emit_log(helm, job_name, namespace, echo)
    record = parse_restore_log(text)
    record.update({"job": job_name, "namespace": namespace, "from": from_file})

    if state == "succeeded":
        if "tables" not in record:
            return Outcome(EXIT_REFUSED, state=record, changed=True, reason=(
                f"job/{job_name} completed but its log does not say what it restored. Read the "
                f"log above before treating this database as recovered."))
        return Outcome(EXIT_OK, state=record, changed=True, reason=(
            f"restored {from_file}: {record['tables']} table(s) in the public schema."))
    if state == "failed":
        # THE COMMON FAILURE IS THE GUARD, AND IT IS NOT A BUG. Naming it here saves the operator
        # reading a stack of Kubernetes events to find a message that is already in the log above.
        hint = ""
        if "REFUSING" in text:
            hint = ("\nThe Job refused rather than failed: it found other sessions on the "
                    "database and stopped BEFORE dropping anything. Nothing was changed. "
                    "Re-run with --quiesce, or scale the application down yourself.")
        return Outcome(EXIT_REFUSED, state=record, changed=True,
                       reason=f"the restore Job failed{': ' + reason if reason else ''}.{hint}")
    return Outcome(EXIT_USAGE, state=record, changed=True,
                   reason=reason or f"could not read the state of job/{job_name}")


# ── argument parsing, beside the code that reads it ───────────────────────────

def add_parser(sub) -> None:
    """Register `backup` and `restore`.

    Declared here rather than in cli.py for support_bundle's reason: a flag parsed in one file and
    acted on in another is a flag that can silently stop being read.
    """
    p = sub.add_parser(
        "backup", help="run the chart's backup CronJob now and report what it produced")
    p.add_argument("spec")
    p.add_argument("--namespace", "-n", required=True, help="namespace holding the release")
    p.add_argument("--release-name", default=None,
                   help="helm release name (default: the document's metadata.name)")
    p.add_argument("--no-wait", action="store_true",
                   help="start the Job and return. Reports that Kubernetes accepted it, which is "
                        "not the same as a backup existing")
    p.add_argument("--timeout", type=int, default=DEFAULT_BACKUP_TIMEOUT,
                   help=f"seconds to wait for the Job (default {DEFAULT_BACKUP_TIMEOUT})")
    p.add_argument("--context", default=None, help="kubeconfig context to use")
    p.add_argument("--json", action="store_true",
                   help="print the backup record as JSON on stdout")
    p.set_defaults(func=_cmd_backup)

    p = sub.add_parser(
        "restore",
        help="restore a dump into the release's database — PREVIEWS by default, DESTRUCTIVE")
    p.add_argument("spec")
    p.add_argument("--namespace", "-n", required=True, help="namespace holding the release")
    p.add_argument("--from", dest="from_file", default=None,
                   help="the dump to restore, by filename on the backup volume. Run without it "
                        "to see what the backup Jobs on this cluster reported writing")
    p.add_argument("--release-name", default=None,
                   help="helm release name (default: the document's metadata.name)")
    p.add_argument("--run-id", default=None,
                   help="names the Job (default: acpctl-<timestamp>)")
    p.add_argument("--quiesce", action="store_true",
                   help="scale the release's Deployments to 0 first and back afterwards. The "
                        "restore refuses while any other session is on the database")
    p.add_argument("--yes", action="store_true",
                   help="actually restore; without this the command previews and changes nothing")
    p.add_argument("--timeout", type=int, default=DEFAULT_RESTORE_TIMEOUT,
                   help=f"seconds to wait for the Job (default {DEFAULT_RESTORE_TIMEOUT})")
    p.add_argument("--chart", default=str(DEFAULT_CHART), help="path to the ACP chart")
    p.add_argument("--context", default=None, help="kubeconfig context to use")
    p.add_argument("--json", action="store_true",
                   help="print the restore record as JSON on stdout")
    p.set_defaults(func=_cmd_restore)


def _cmd_backup(args) -> int:
    """EXIT CODES, matching install and uninstall:

        0  the backup ran and its log names the dump it wrote
        1  refused (no release, no CronJob), or the Job failed, or it completed without naming a
           dump — the last is deliberately not 0, because a Job that says Complete and produced
           no file is the failure reading the log exists to catch
        2  usage, an unreachable cluster, or a Job this command stopped watching. Retryable.
    """
    from .cli import _emit
    echo = (lambda line: print(line, file=sys.stderr)) if args.json else print
    return _emit(backup(args.spec, namespace=args.namespace, release_name=args.release_name,
                        wait=not args.no_wait, timeout=args.timeout, context=args.context,
                        echo=echo), args)


def _cmd_restore(args) -> int:
    """EXIT CODES:

        0  the preview was printed (nothing changed), or the restore completed and said what it
           restored
        1  refused, or the Job failed — including the Job's own refusal to run under a live
           application, which changes nothing and is reported as a failure of the command
        2  usage (no --from), an unreachable cluster, or a Job this command stopped watching
    """
    from .cli import _emit
    echo = (lambda line: print(line, file=sys.stderr)) if args.json else print
    return _emit(restore(args.spec, namespace=args.namespace, from_file=args.from_file,
                         release_name=args.release_name, run_id=args.run_id,
                         quiesce=args.quiesce, assume_yes=args.yes, timeout=args.timeout,
                         chart_dir=args.chart, context=args.context, echo=echo), args)
