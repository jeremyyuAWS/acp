"""`acpctl backup` and `acpctl restore` — what they run, what they refuse, and what they read back.

THREE THEMES, and each is a way one of these commands could look like it worked.

  * SUCCESS IS READ, NOT INFERRED. `kubectl create job` exits 0 when the API server ACCEPTED the
    Job. `test_a_completed_job_that_names_no_dump_is_not_a_success` is the load-bearing test in
    this file: a Job that reports Complete and whose log names no file is not a backup, and a
    command that exits 0 on it has told an operator they have one.
  * A PREVIEW IS ONLY A PREVIEW IF NOTHING MOVED. Every refusal here is asserted with the exit
    code AND an empty mutation list, the same way tests/test_packaging_uninstall.py does it —
    a command that refuses after it has already scaled the API tier to zero has not refused.
  * THE GUARD CANNOT SEE WHICH DEPLOYMENT. `helm.check_kubectl` bounds `kubectl scale` to
    Deployments and forbids `--all`; it has no way to know whether the name a caller passed
    belongs to this release. `test_quiesce_scales_only_deployments_the_release_owns` is the other
    half of that bound, and it is a test rather than a guard on purpose — helm.py says so in its
    own docstring rather than implying the guard proves more than it does.

The fake cluster is tests/test_packaging_install.py's, extended rather than copied, for the reason
the uninstall tests give: two fakes drift, and the first thing they disagree about is what an
installed namespace looks like.

WHAT THIS DOES NOT PROVE, stated plainly. These are the answers helm and kubectl are DOCUMENTED to
give. The Jobs themselves — pg_dump, pg_restore, the live-session guard — are exercised against a
real PostgreSQL on the disposable reference cluster (`.github/workflows/packaging-kind.yml`); the
orchestration in `backup.py` is not. Nothing below establishes that a real API server agrees.
"""
from __future__ import annotations

import json
import shutil
import subprocess

import pytest
import yaml

from packaging_helpers import PACKAGING
from test_packaging_install import CHART, EXAMPLE, FakeRunner, mutations

RELEASE = "acp-production"
NAMESPACE = "acp-production"
# The chart's fullname need not equal the release name — `fullnameOverride`, or a release whose
# name already contains the chart's. The fixture deliberately makes them DIFFER, so a test that
# passes only because the two happen to match cannot.
FULLNAME = "acp-prod"
CRONJOB = f"{FULLNAME}-backup"

BACKUP_LOG = (
    "wrote /backups/acp-20260908T020000Z.dump (3138 bytes, 9 objects)\n"
    "retention 35d, 4 backup(s) on the volume\n"
)
RESTORE_LOG = (
    "acp-20260908T020000Z.dump lists 9 restorable objects\n"
    "restored acp-20260908T020000Z.dump: 24 table(s) in the public schema\n"
)
REFUSAL_LOG = (
    "acp-20260908T020000Z.dump lists 9 restorable objects\n"
    "REFUSING: 6 other session(s) are connected to this database.\n"
)

RENDERED_RESTORE = """\
---
apiVersion: batch/v1
kind: Job
metadata:
  name: {name}
  labels:
    app.kubernetes.io/component: restore
spec:
  backoffLimit: 0
"""


class Cluster(FakeRunner):
    """An installed namespace that also answers the calls backup and restore make.

    `jobs` maps a Job name to `(state, log)`; a Job created during the test lands there with the
    state the fixture was told to give the NEXT one, which is what lets a single fixture describe
    "the backup will succeed" or "the restore will refuse" without knowing the generated name.
    """

    def __init__(self, *, cronjob=CRONJOB, deployments=(("acp-prod-api", 2),),
                 next_job=("succeeded", BACKUP_LOG), values=None, prior_jobs=(),
                 render=None, render_error="", **kwargs):
        super().__init__(**kwargs)
        self.cronjob = cronjob
        self.deployments = {name: replicas for name, replicas in deployments}
        self.next_job = next_job
        self.values = {} if values is None else values
        self.jobs: dict[str, tuple[str, str]] = dict(prior_jobs)
        self.render = render
        self.render_error = render_error
        self.scaled: list[tuple[str, int]] = []
        self.created_jobs: list[str] = []

    # -- helm ---------------------------------------------------------------
    def _helm(self, argv, args):
        if args[:2] == ["get", "values"]:
            return self._result(argv, 0, stdout=json.dumps(self.values))
        if args[0] == "template":
            if self.render_error:
                return self._result(argv, 1, stderr=self.render_error)
            run = next((a.split("=", 1)[1] for a in args if a.startswith("restore.runId=")), "x")
            name = self.render if self.render else f"{FULLNAME}-restore-{run}"
            return self._result(argv, 0, stdout=RENDERED_RESTORE.format(name=name))
        return super()._helm(argv, args)

    # -- kubectl ------------------------------------------------------------
    def _kubectl(self, argv, args, stdin):
        verb = args[0]
        what = args[1] if len(args) > 1 else ""
        if verb == "get" and what == "cronjob":
            # A LABEL QUERY, so an absent CronJob is an EMPTY LIST and exit 0 — not a NotFound.
            # `kubectl get <kind> -l ...` never 404s, and a fake that answered NotFound here
            # would be testing a code path a real cluster cannot produce.
            names = [] if self.cronjob is None else [self.cronjob]
            return self._result(argv, 0, stdout=json.dumps(
                {"items": [{"metadata": {"name": n}} for n in names]}))
        if verb == "get" and what == "job":
            if "-l" in args:
                return self._result(argv, 0, stdout=json.dumps({"items": [
                    {"metadata": {"name": name, "creationTimestamp": f"2026-09-0{i}T00:00:00Z"}}
                    for i, name in enumerate(sorted(self.jobs), start=1)]}))
            name = args[2]
            state = self.jobs.get(name, ("unknown", ""))[0]
            if state == "unknown":
                return self._result(
                    argv, 1, stderr='Error from server (NotFound): jobs "x" not found')
            condition = {"succeeded": "Complete", "failed": "Failed"}.get(state)
            body: dict = {"status": {}}
            if condition:
                body["status"]["conditions"] = [{"type": condition, "status": "True"}]
            return self._result(argv, 0, stdout=json.dumps(body))
        if verb == "get" and what == "deployment":
            return self._result(argv, 0, stdout=json.dumps({"items": [
                {"metadata": {"name": n}, "spec": {"replicas": r}}
                for n, r in sorted(self.deployments.items())]}))
        if verb == "logs":
            name = args[1].split("/", 1)[1]
            return self._result(argv, 0, stdout=self.jobs.get(name, ("", ""))[1])
        if verb == "create" and what == "job":
            name = args[2]
            self.created_jobs.append(name)
            self.jobs[name] = self.next_job
            return self._result(argv, 0, stdout="job created")
        if verb == "scale":
            name = args[1].split("/", 1)[1]
            replicas = int(next(a.split("=", 1)[1] for a in args
                                if a.startswith("--replicas=")))
            self.scaled.append((name, replicas))
            self.deployments[name] = replicas
            return self._result(argv, 0, stdout="scaled")
        if verb == "apply":
            # The restore's manifest is YAML, the install state is JSON. Branch rather than
            # assuming, because the parent stores whatever it is handed as the install state.
            try:
                payload = json.loads(stdin)
            except (TypeError, json.JSONDecodeError):
                name = next(line.split(":", 1)[1].strip() for line in stdin.splitlines()
                            if line.startswith("  name:"))
                self.jobs[name] = self.next_job
                return self._result(argv, 0, stdout="job created")
            self.state = json.loads(payload["data"]["installation.json"])
            return self._result(argv, 0, stdout="configmap configured")
        return super()._kubectl(argv, args, stdin)


INSTALLED = {"release": {"status": "deployed", "revision": 3}}
STATE = {"apiVersion": "packaging.acp.mova.io/v1alpha1", "release": {"name": RELEASE}}


def cluster(**kwargs) -> Cluster:
    kwargs.setdefault("release", INSTALLED["release"])
    kwargs.setdefault("state", STATE)
    return Cluster(**kwargs)


def run_backup(runner, **kwargs):
    from acpctl.backup import backup
    from acpctl.helm import Helm

    kwargs.setdefault("namespace", NAMESPACE)
    kwargs.setdefault("release_name", RELEASE)
    lines: list[str] = []
    outcome = backup(str(EXAMPLE), helm=Helm(runner=runner), echo=lines.append,
                     sleep=lambda _s: None, **kwargs)
    outcome.messages = lines
    return outcome


def run_restore(runner, **kwargs):
    from acpctl.backup import restore
    from acpctl.helm import Helm

    kwargs.setdefault("namespace", NAMESPACE)
    kwargs.setdefault("release_name", RELEASE)
    kwargs.setdefault("chart_dir", CHART)
    lines: list[str] = []
    outcome = restore(str(EXAMPLE), helm=Helm(runner=runner), echo=lines.append,
                      sleep=lambda _s: None, **kwargs)
    outcome.messages = lines
    return outcome


def argv_containing(runner, needle) -> list[list[str]]:
    return [argv for argv in runner.log if needle in " ".join(argv)]


# ── the fixture's own guard ───────────────────────────────────────────────────

def test_the_fixture_makes_the_release_name_and_the_fullname_differ():
    """Otherwise half this file passes for the wrong reason.

    `restore.confirm` must be the chart's FULLNAME and the CronJob is the only place acpctl reads
    it from. If the fixture's release name and fullname were the same string, a version of
    backup.py that simply used the release name would pass every assertion below.
    """
    assert FULLNAME != RELEASE
    assert not CRONJOB.startswith(RELEASE), (
        "the CronJob must NOT be findable by <release>-backup, or the label lookup "
        "this file is about would be indistinguishable from a computed name")


# ── backup ────────────────────────────────────────────────────────────────────

def test_a_backup_runs_the_charts_cronjob_and_nothing_it_assembled_itself():
    runner = cluster()
    outcome = run_backup(runner)
    assert outcome.code == 0, outcome.reason
    created = argv_containing(runner, "create job")
    assert len(created) == 1, created
    assert f"--from=cronjob/{CRONJOB}" in created[0], created[0]


def test_a_backup_reports_the_dump_the_job_says_it_wrote():
    outcome = run_backup(cluster())
    assert outcome.code == 0, outcome.reason
    assert outcome.state["file"] == "acp-20260908T020000Z.dump"
    assert outcome.state["bytes"] == 3138
    assert outcome.state["objects"] == 9
    assert outcome.state["retentionDays"] == 35
    assert outcome.state["kept"] == 4
    # And it tells the operator the one command that consumes that filename.
    assert "acpctl restore" in outcome.reason and "--from acp-2026" in outcome.reason


def test_a_completed_job_that_names_no_dump_is_not_a_success():
    """THE LOAD-BEARING TEST. A Job whose condition is Complete and whose log names no file is
    not a backup — and the exit status of everything this command ran is zero. Exiting 0 here
    would tell an operator they have a dump they do not have."""
    outcome = run_backup(cluster(next_job=("succeeded", "some other container's output\n")))
    assert outcome.code == 1, outcome.reason
    assert "names no dump file" in outcome.reason


def test_a_failed_backup_job_exits_nonzero():
    outcome = run_backup(cluster(next_job=("failed", "pg_dump: error: connection refused\n")))
    assert outcome.code == 1, outcome.reason
    assert "failed" in outcome.reason
    assert any("connection refused" in line for line in outcome.messages)


def test_a_backup_that_is_not_waited_for_says_what_it_did_not_establish():
    outcome = run_backup(cluster(), wait=False)
    assert outcome.code == 0
    assert "NOT WAITED FOR" in outcome.reason
    assert outcome.state["waited"] is False


def test_a_job_that_never_finishes_is_a_2_and_is_not_called_a_failure():
    """A timeout means this command stopped watching, not that the backup failed. Reporting it as
    a failure sends an operator to re-run a dump that is still in progress."""
    runner = cluster(next_job=("running", ""))
    outcome = run_backup(runner, timeout=0)
    assert outcome.code == 2, outcome.reason
    assert "stopped watching" in outcome.reason
    assert "the backup Job failed" not in outcome.reason


# ── the refusals, each asserted to have changed nothing ───────────────────────

def test_no_backup_cronjob_refuses_and_names_the_values_that_enable_it():
    runner = cluster(cronjob=None)
    outcome = run_backup(runner)
    assert outcome.code == 1, outcome.reason
    for key in ("backup.enabled", "backup.schedule", "backup.retentionDays"):
        assert key in outcome.reason, outcome.reason
    assert mutations(runner) == []


def test_no_release_here_refuses_before_anything_is_created():
    runner = cluster(release=None)
    outcome = run_backup(runner)
    assert outcome.code == 1, outcome.reason
    assert "no helm release" in outcome.reason
    assert mutations(runner) == []


def test_a_release_that_could_not_be_read_is_a_2_not_a_1():
    """2 is retryable and 1 is not. "helm could not tell us" is a different answer from "there is
    no release here", and treating the first as the second is how a backup command reports a
    cluster it never reached."""
    runner = cluster(fail={"helm --kube-context": "x", "status": "Error: query: forbidden"})
    outcome = run_backup(runner)
    assert outcome.code == 2, outcome.reason
    assert mutations(runner) == []


# ── restore: the preview ──────────────────────────────────────────────────────

def test_a_restore_preview_issues_no_mutating_command():
    runner = cluster()
    outcome = run_restore(runner, from_file="acp-20260908T020000Z.dump")
    assert outcome.code == 0, outcome.reason
    assert outcome.changed is False
    assert "PREVIEW ONLY" in outcome.reason
    assert mutations(runner) == []


def test_the_preview_says_what_a_restore_does_not_put_back():
    """The database goes back to the dump's point in time and object storage does not, so
    afterwards the two disagree about everything produced in between. An operator who is not told
    that finds out from a broken artifact link."""
    outcome = run_restore(cluster(), from_file="acp-20260908T020000Z.dump")
    text = "\n".join(outcome.messages)
    assert "object storage" in text and "NOT restored" in text
    assert "Redis" in text
    assert "DROPPED and recreated" in text


def test_a_restore_with_no_dump_named_lists_what_the_backup_jobs_reported():
    """There is deliberately no "latest" — after a bad migration the newest backup is the one you
    do not want — so the command has to help the operator find the name instead."""
    runner = cluster(prior_jobs={f"{CRONJOB}-1": ("succeeded", BACKUP_LOG)})
    outcome = run_restore(runner)
    assert outcome.code == 2, outcome.reason
    assert "acp-20260908T020000Z.dump" in outcome.reason
    assert "no \"latest\"" in outcome.reason
    assert mutations(runner) == []


def test_the_listing_says_it_is_not_a_listing_of_the_volume():
    """It is what the surviving backup Jobs REPORTED, bounded by the CronJob's history limits. A
    name absent from it may still be on the claim, and an operator who reads it as the volume's
    contents concludes their backup is gone."""
    outcome = run_restore(cluster())
    assert "not a listing of the volume" in outcome.reason


# ── restore: doing it ─────────────────────────────────────────────────────────

def test_the_restore_confirms_with_the_fullname_read_off_the_cronjob():
    """`restore.confirm` must equal the chart's `acp.fullname`, and recomputing helm's fullname
    rule here would be a second definition of somebody else's contract. It is read from the
    CronJob's own name — which is why the fixture's release name and fullname differ."""
    runner = cluster(next_job=("succeeded", RESTORE_LOG))
    outcome = run_restore(runner, from_file="acp-x.dump", assume_yes=True)
    assert outcome.code == 0, outcome.reason
    template = argv_containing(runner, "template")[0]
    assert f"restore.confirm={FULLNAME}" in template, template
    assert f"restore.confirm={RELEASE}" not in " ".join(template)


def test_the_restore_renders_from_the_releases_values_not_from_the_document():
    """An install may have carried a release manifest's digests or a `--set`. A Job rendered from
    the document alone would differ from the workloads it is restoring underneath."""
    runner = cluster(next_job=("succeeded", RESTORE_LOG))
    run_restore(runner, from_file="acp-x.dump", assume_yes=True)
    order = [" ".join(argv) for argv in runner.log]
    got_values = next(i for i, line in enumerate(order) if "get values" in line)
    templated = next(i for i, line in enumerate(order) if " template " in line)
    assert got_values < templated, order


def test_the_job_polled_for_is_the_one_the_chart_named():
    """`templates/restore-job.yaml` truncates the name to 63 characters. A recomputed name would
    agree until a long release name crossed that, and this command would then poll for a Job that
    does not exist and time out — while the restore ran perfectly."""
    runner = cluster(next_job=("succeeded", RESTORE_LOG), render="truncated-name-from-the-chart")
    outcome = run_restore(runner, from_file="acp-x.dump", run_id="a-very-long-run-id",
                          assume_yes=True)
    assert outcome.code == 0, outcome.reason
    assert outcome.state["job"] == "truncated-name-from-the-chart"
    assert argv_containing(runner, "get job truncated-name-from-the-chart")


def test_a_render_the_chart_refuses_stops_before_anything_is_applied():
    runner = cluster(render_error="Error: execution error: restore.confirm must be \"acp-prod\"")
    outcome = run_restore(runner, from_file="acp-x.dump", assume_yes=True)
    assert outcome.code == 1, outcome.reason
    assert "restore.confirm" in outcome.reason
    assert mutations(runner) == []


def test_the_jobs_own_refusal_is_reported_as_a_refusal_and_not_as_damage():
    """The live-session guard runs BEFORE `pg_restore --clean` drops anything, so a Job that
    refuses has changed nothing. Saying "the restore failed" without that is how somebody
    concludes their database is half-restored and starts making it worse."""
    runner = cluster(next_job=("failed", REFUSAL_LOG))
    outcome = run_restore(runner, from_file="acp-x.dump", assume_yes=True)
    assert outcome.code == 1, outcome.reason
    assert "refused rather than failed" in outcome.reason
    assert "Nothing was changed" in outcome.reason
    assert "--quiesce" in outcome.reason


def test_a_completed_restore_that_says_nothing_about_what_it_restored_is_not_a_success():
    outcome = run_restore(cluster(next_job=("succeeded", "\n")),
                          from_file="acp-x.dump", assume_yes=True)
    assert outcome.code == 1, outcome.reason
    assert "does not say what it restored" in outcome.reason


# ── restore: --quiesce ────────────────────────────────────────────────────────

QUIESCE_FIXTURE = dict(
    deployments=(("acp-prod-api", 2), ("acp-prod-worker-assess", 5)),
    next_job=("succeeded", RESTORE_LOG),
)


def test_quiesce_scales_only_deployments_the_release_owns():
    """THE HALF OF THE BOUND THE GUARD CANNOT MAKE. `helm.check_kubectl` bounds the KIND a scale
    may touch and forbids `--all`; it cannot know whether a name belongs to this release. The
    names come from `deployments_owned`, which queries the release's own instance label, and this
    asserts that nothing else ever reaches the scale call."""
    runner = cluster(**QUIESCE_FIXTURE)
    outcome = run_restore(runner, from_file="acp-x.dump", assume_yes=True, quiesce=True)
    assert outcome.code == 0, outcome.reason
    owned = {"acp-prod-api", "acp-prod-worker-assess"}
    assert {name for name, _ in runner.scaled} == owned
    for argv in argv_containing(runner, "scale"):
        assert any(f"deployment/{name}" in argv for name in owned), argv
    # Every ownership query used the release's instance label rather than a name this tool chose.
    for argv in argv_containing(runner, "get deployment"):
        assert f"app.kubernetes.io/instance={RELEASE}" in " ".join(argv), argv


def test_quiesce_puts_every_tier_back_at_the_count_it_had():
    runner = cluster(**QUIESCE_FIXTURE)
    run_restore(runner, from_file="acp-x.dump", assume_yes=True, quiesce=True)
    assert runner.deployments == {"acp-prod-api": 2, "acp-prod-worker-assess": 5}
    assert runner.scaled[:2] == [("acp-prod-api", 0), ("acp-prod-worker-assess", 0)]


def test_quiesce_records_the_counts_before_it_scales_anything():
    """An interrupted run that had already scaled down and not written the numbers leaves an
    application at zero with nothing on the cluster saying what it should be."""
    runner = cluster(**QUIESCE_FIXTURE)
    run_restore(runner, from_file="acp-x.dump", assume_yes=True, quiesce=True)
    order = [" ".join(argv) for argv in runner.log]
    wrote = next(i for i, line in enumerate(order) if "apply" in line)
    scaled = next(i for i, line in enumerate(order) if " scale " in line)
    assert wrote < scaled, order


def test_quiesce_refuses_when_there_is_nowhere_to_record_the_counts():
    """A release installed by hand has no acp-installation ConfigMap. Legitimate — and still not a
    situation in which this command may take the tiers down."""
    runner = cluster(state=None, **QUIESCE_FIXTURE)
    outcome = run_restore(runner, from_file="acp-x.dump", assume_yes=True, quiesce=True)
    assert outcome.code == 1, outcome.reason
    assert "nowhere" in outcome.reason or "no acp-installation" in outcome.reason
    assert runner.scaled == []


def test_an_interrupted_quiesce_is_resumed_from_its_own_record():
    """The live counts are zero, so `prior` would scale the application "back" to the outage. The
    recorded ones are the only true answer, and they win."""
    stale = dict(STATE, quiesce={"replicas": {"acp-prod-api": 4, "acp-prod-worker-assess": 7},
                                 "job": "acp-prod-restore-earlier"})
    runner = cluster(state=stale, deployments=(("acp-prod-api", 0), ("acp-prod-worker-assess", 0)),
                     next_job=("succeeded", RESTORE_LOG))
    outcome = run_restore(runner, from_file="acp-x.dump", assume_yes=True, quiesce=True)
    assert outcome.code == 0, outcome.reason
    assert runner.deployments == {"acp-prod-api": 4, "acp-prod-worker-assess": 7}


def test_the_tiers_go_back_up_even_when_the_restore_failed():
    """A restore that fails is a bad afternoon. A restore that fails and leaves the application at
    zero replicas is an outage, and the second is the one this command would have caused."""
    runner = cluster(deployments=(("acp-prod-api", 2),), next_job=("failed", REFUSAL_LOG))
    outcome = run_restore(runner, from_file="acp-x.dump", assume_yes=True, quiesce=True)
    assert outcome.code == 1, outcome.reason
    assert runner.deployments == {"acp-prod-api": 2}


def test_a_finished_quiesce_clears_its_record():
    """A stale record is what `test_an_interrupted_quiesce_is_resumed_from_its_own_record` acts
    on, so leaving one behind after a clean run would make the NEXT restore scale back to counts
    from the one before it."""
    runner = cluster(**QUIESCE_FIXTURE)
    run_restore(runner, from_file="acp-x.dump", assume_yes=True, quiesce=True)
    assert "quiesce" not in (runner.state or {})


# ── the allow-list these two commands widened ────────────────────────────────

@pytest.mark.parametrize("args, needle", [
    (["create", "job", "adhoc", "--image=alpine", "-n", "acp"], "--from=cronjob"),
    (["create", "job", "adhoc", "--from=deployment/acp-api", "-n", "acp"], "must name a cronjob"),
    (["logs", "pod/acp-api-1", "-n", "acp"], "job/<name>"),
    (["logs", "-l", "app=acp", "-n", "acp"], "job/<name>"),
    (["scale", "statefulset/pg", "--replicas=0", "-n", "acp"], "may only `kubectl scale`"),
    (["scale", "deployment/acp-api", "-n", "acp"], "no --replicas"),
    (["scale", "deployment", "--all", "--replicas=0", "-n", "acp"], "--all"),
])
def test_the_widened_verbs_are_still_narrow(args, needle):
    """Each entry backup and restore added to helm.py's allow-list, asked to do the general thing
    it was NOT widened for. A permission granted for one command that turns out to admit the
    general case is how an allow-list stops being one."""
    from acpctl.helm import ForbiddenCommand, check_kubectl

    with pytest.raises(ForbiddenCommand) as excinfo:
        check_kubectl(args)
    assert needle in str(excinfo.value)


@pytest.mark.parametrize("args", [
    ["create", "job", "acp-backup-1", "--from=cronjob/acp-backup", "-n", "acp"],
    ["logs", "job/acp-backup-1", "-n", "acp"],
    ["scale", "deployment/acp-api", "--replicas=2", "-n", "acp"],
])
def test_the_calls_these_commands_actually_make_are_permitted(args):
    """The other direction, so the parametrized refusals above cannot pass by refusing
    everything — which a guard with a typo in it would do, silently, at the exact moment an
    operator needed a backup."""
    from acpctl.helm import check_kubectl

    check_kubectl(args)


def test_a_scale_is_counted_as_a_mutation():
    """`mutations()` is what every "this refused and changed nothing" assertion in this file
    reads. It derives from KUBECTL_WRITE_VERBS, so `scale` is counted by construction — but a
    preview that quietly stopped noticing one class of mutation would be exactly as wrong as one
    that performed it, so the property is asserted rather than assumed."""
    from acpctl.helm import Helm

    probe = Helm(runner=lambda *a, **k: None)
    probe.log = [["kubectl", "scale", "deployment/acp-api", "--replicas=0", "-n", "acp"]]
    assert probe.mutations() == probe.log


# ── the CLI surface ───────────────────────────────────────────────────────────

def test_backup_and_restore_are_no_longer_advertised_as_unimplemented():
    from acpctl.cli import NOT_YET_IMPLEMENTED

    assert "backup" not in NOT_YET_IMPLEMENTED
    assert "restore" not in NOT_YET_IMPLEMENTED
    # And the two that genuinely are not implemented still say so, so this test cannot pass by
    # the dictionary having been emptied.
    assert set(NOT_YET_IMPLEMENTED) == {"upgrade", "rollback"}


@pytest.mark.parametrize("command, flag", [
    ("backup", "--no-wait"),
    ("restore", "--quiesce"),
    ("restore", "--from"),
])
def test_the_flags_are_registered_where_the_code_that_reads_them_lives(command, flag):
    from acpctl.cli import build_parser

    parser = build_parser()
    sub = next(a for a in parser._actions if hasattr(a, "choices") and a.choices)
    assert flag in {opt for action in sub.choices[command]._actions
                    for opt in action.option_strings}


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
@pytest.mark.parametrize("template, component, selector", [
    ("templates/backup-cronjob.yaml", "backup", "backup_cronjob"),
    ("templates/restore-job.yaml", "restore", None),
])
def test_the_chart_labels_the_objects_acpctl_looks_them_up_by(template, component, selector):
    """THE SEAM BETWEEN THIS TOOL AND THE CHART, AND IT IS INVISIBLE FROM EITHER SIDE.

    `backup_cronjob` finds the CronJob by `app.kubernetes.io/instance=<release>` **and**
    `app.kubernetes.io/component=backup`, deliberately rather than by a name it computes. That
    query returns an empty list — not an error — if the chart ever stopped emitting either label,
    and `acpctl backup` would then report "this installation takes no backups" about one that
    takes them nightly. Nothing in the chart's own tests would notice, and nothing in this file's
    fake would either: the fake answers whatever it is asked.

    So this renders the real chart and asserts the labels are there.
    """
    values = json.dumps({"secrets": {"existingSecret": "acp-secrets"},
                         "backup": {"enabled": True, "schedule": "0 2 * * *",
                                    "retentionDays": 35}})
    proc = subprocess.run(
        [shutil.which("helm"), "template", RELEASE, str(CHART), "-n", NAMESPACE, "-f", "-",
         "-s", template,
         "--set", "restore.enabled=true", "--set", "restore.file=acp-x.dump",
         "--set", "restore.runId=drill", f"--set=restore.confirm={RELEASE}"],
        input=values, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    # The backup template renders TWO objects — the CronJob and its PersistentVolumeClaim — so
    # this picks the one by kind rather than assuming a single-document render.
    wanted = "CronJob" if component == "backup" else "Job"
    rendered = next(d for d in yaml.safe_load_all(proc.stdout) if d and d["kind"] == wanted)
    labels = rendered["metadata"]["labels"]
    assert labels["app.kubernetes.io/instance"] == RELEASE, labels
    assert labels["app.kubernetes.io/component"] == component, labels

    if selector == "backup_cronjob":
        # And the Jobs the CronJob spawns carry them too, which is what `_recent_dumps` reads.
        job_labels = rendered["spec"]["jobTemplate"]["metadata"]["labels"]
        assert job_labels["app.kubernetes.io/instance"] == RELEASE, job_labels
        assert job_labels["app.kubernetes.io/component"] == "backup", job_labels


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_the_rendered_job_name_is_where_this_module_looks_for_it():
    """`job_name_in` is a line scan for the first `  name:`. That holds because `metadata` is the
    first block of a single-object render — asserted against the real chart rather than against
    the fake's hand-written manifest, which is the one place this could agree with itself and be
    wrong about helm."""
    from acpctl.backup import job_name_in

    values = json.dumps({"secrets": {"existingSecret": "acp-secrets"},
                         "backup": {"enabled": True, "schedule": "0 2 * * *",
                                    "retentionDays": 35}})
    proc = subprocess.run(
        [shutil.which("helm"), "template", RELEASE, str(CHART), "-n", NAMESPACE, "-f", "-",
         "-s", "templates/restore-job.yaml",
         "--set", "restore.enabled=true", "--set", "restore.file=acp-x.dump",
         "--set", "restore.runId=drill", f"--set=restore.confirm={RELEASE}"],
        input=values, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    assert job_name_in(proc.stdout) == yaml.safe_load(proc.stdout)["metadata"]["name"]


def test_the_wait_for_first_consumer_hazard_is_written_down_where_it_bites():
    """A FAILURE THIS REPOSITORY HAS ALREADY PAID FOR ONCE, and it names nothing about backups.

    `helm --wait` waits for every PVC to reach Bound. The backup claim is mounted by exactly one
    pod — the backup Job — which does not exist until the CronJob fires, so on a StorageClass with
    `volumeBindingMode: WaitForFirstConsumer` (kind's local-path, AWS gp3, Azure's managed-csi
    default) it stays Pending. The reference cluster spent ten minutes on it and then reported
    `context deadline exceeded` (run 34241201489). `acpctl install` passes `--wait --atomic`, so on
    such a cluster the release ROLLS BACK.

    Nothing renderable can assert this — it is a property of Kubernetes volume binding, not of the
    manifest — so what is asserted is that the warning is still in the two places an operator
    meets it: beside the value that creates the claim, and in the lifecycle doc. A silently
    deleted warning is how the next person spends the same ten minutes.
    """
    values = (PACKAGING / "chart" / "acp" / "values.yaml").read_text(encoding="utf-8")
    lifecycle = (PACKAGING / "docs" / "lifecycle.md").read_text(encoding="utf-8")
    for name, text in (("values.yaml", values), ("lifecycle.md", lifecycle)):
        assert "WaitForFirstConsumer" in text, name
        assert "existingClaim" in text, name
        # The escape hatch, not just the diagnosis. A warning that does not say what to do
        # instead sends the reader to disable the backup.
        assert "Immediate" in text, name


def test_the_docs_describe_both_commands():
    """lifecycle.md is where an operator reads what these do and what has not been proven about
    them. A command that ships without a line there is one whose limits are only in a docstring."""
    text = (PACKAGING / "docs" / "lifecycle.md").read_text(encoding="utf-8")
    assert "acpctl backup" in text and "acpctl restore" in text
    assert "--quiesce" in text
