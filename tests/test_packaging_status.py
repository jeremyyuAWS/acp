"""`acpctl status` — health, and the drift check that makes the document's own claim true.

`acpctl values` stamps this on every file it renders:

    edit the deployment document and regenerate, or the two disagree and the document
    stops being the record of what was installed

Nothing verified that until `status`. So the tests that matter most here are not the health ones —
`kubectl get pods` shows health — but the drift ones, and specifically the case where the obvious
implementation is WRONG: comparing running replicas against the document's `replicaCount` reports
every healthy autoscaled tier as drifted. A report that is red on every correct installation is
one nobody reads, and then the real drift goes unread with it.
"""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import packaging_kubectl_fake as fake
from packaging_helpers import PACKAGING, load_example

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = PACKAGING / "examples" / "standard-production.acp-deployment.yaml"


def status_for(tmp_path, fixture, *, namespace="acp-production", document=None):
    """The real gather() against the fake kubectl, then the real report()."""
    from acpctl import installation as installation_mod
    from acpctl import status as status_mod
    from acpctl.values import build_values

    env = fake.install(tmp_path, fixture)
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        facts = installation_mod.gather(namespace=namespace)
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    doc = document if document is not None else load_example("standard-production")
    return status_mod.report(build_values(doc), facts, namespace=namespace)


def check(report, check_id):
    for c in report["checks"]:
        if c["id"] == check_id:
            return c
    raise AssertionError(f"no check {check_id!r}; have {[c['id'] for c in report['checks']]}")


def ids(report):
    return [c["id"] for c in report["checks"]]


def deployments_with(**changes):
    """HEALTHY's deployments with one tier changed, by name."""
    out = copy.deepcopy(fake.HEALTHY["deployments"])
    for name, updates in changes.items():
        for d in out:
            if d["name"] == name:
                d.update(updates)
    return out


# ── the baseline ──────────────────────────────────────────────────────────────

def test_a_healthy_matching_installation_reports_ok(tmp_path):
    report = status_for(tmp_path, fake.HEALTHY)
    assert report["ok"] is True, [c for c in report["checks"] if c["status"] != "pass"]
    assert report["drifted"] is False
    assert report["installed"] is True


def test_every_check_passes_on_a_healthy_installation(tmp_path):
    """Asserted per check rather than on the summary.

    A summary assertion is what hid the `metrics.custom` bug in doctor: a warning-severity finding
    can be permanently wrong while `ok` stays True. Every check is named here so a false finding
    has nowhere to sit.
    """
    report = status_for(tmp_path, fake.HEALTHY)
    failing = [(c["id"], c["status"], c["detail"]) for c in report["checks"]
               if c["status"] != "pass"]
    assert not failing, f"a healthy installation produced findings: {failing}"


# ── the trap: autoscaling is not drift ────────────────────────────────────────

def test_an_autoscaled_tier_inside_its_range_is_not_drift(tmp_path):
    """THE TEST THIS FILE EXISTS FOR.

    The remediate tier is configured 3-10 in the document and running at 7. The obvious check —
    compare against `replicaCount`, which is the FLOOR (3) — calls that drift. It is not: it is
    KEDA doing exactly what it was installed to do, and a status command that reports it is red on
    every correctly-working installation.

    Read on remediate rather than assess since the owner pinned the assess tier warm at 5-5
    (2026-09-05). A pinned tier is judged by the opposite rule — exact count, any difference is
    drift — so asserting the autoscaled rule there would have been asserting the wrong rule and
    passing for the wrong reason.
    """
    fixture = fake.shape(deployments=deployments_with(**{
        "acp-worker-remediate": {"replicas": None, "ready": 7}}))
    report = status_for(tmp_path, fixture)
    finding = check(report, "replicas.remediate")
    assert finding["status"] == "pass", finding
    assert "within" in finding["detail"]
    assert report["drifted"] is False


def test_an_autoscaled_tier_outside_its_range_is_drift(tmp_path):
    """The control. Without it the test above is satisfiable by never checking autoscaled tiers
    at all — which would miss a tier scaled by hand, or one whose ScaledObject was deleted so
    nothing is holding the range any more."""
    fixture = fake.shape(deployments=deployments_with(**{
        "acp-worker-remediate": {"replicas": 20, "ready": 20}}))
    report = status_for(tmp_path, fixture)
    finding = check(report, "replicas.remediate")
    assert finding["status"] == "fail"
    assert "outside" in finding["detail"]
    assert "3-10" in finding["detail"]
    assert report["drifted"] is True


def test_a_fixed_tier_is_compared_against_the_exact_count(tmp_path):
    """A tier with no autoscaler has nothing legitimately changing its replica count, so any
    difference IS drift — the opposite rule from the autoscaled case, which is why the two are
    separate branches rather than one comparison with a tolerance."""
    doc = load_example("standard-production")
    del doc["workers"]["discover"]["autoscale"]
    doc["workers"]["discover"]["replicas"] = {"min": 2, "max": 2}
    fixture = fake.shape(deployments=deployments_with(**{
        "acp-worker-discover": {"replicas": 5, "ready": 5}}))
    report = status_for(tmp_path, fixture, document=doc)
    finding = check(report, "replicas.discover")
    assert finding["status"] == "fail"
    assert "the document says 2" in finding["detail"]


def test_a_fixed_tier_at_its_documented_count_is_not_drift(tmp_path):
    doc = load_example("standard-production")
    del doc["workers"]["discover"]["autoscale"]
    doc["workers"]["discover"]["replicas"] = {"min": 2, "max": 2}
    fixture = fake.shape(deployments=deployments_with(**{
        "acp-worker-discover": {"replicas": 2, "ready": 2}}))
    report = status_for(tmp_path, fixture, document=doc)
    assert check(report, "replicas.discover")["status"] == "pass"


# ── release drift ─────────────────────────────────────────────────────────────

def test_a_different_running_release_is_drift(tmp_path):
    report = status_for(tmp_path, fake.shape(release="2026.7"))
    finding = check(report, "release.version")
    assert finding["status"] == "fail"
    assert "2026.7" in finding["detail"] and "2026.9" in finding["detail"]
    assert report["drifted"] is True


def test_a_digest_pinned_install_is_not_reported_as_drift(tmp_path):
    """COMPARED ON THE VERSION LABEL, NOT THE IMAGE STRING.

    `acpctl install` resolves and pins digests, so a correctly-installed release runs
    `repo@sha256:...` while the document names a tag. Comparing image strings would call every
    properly-pinned installation drifted — exactly backwards, since pinning is the thing the
    contract asks for. The chart stamps app.kubernetes.io/version from the tag, so the label
    survives pinning.
    """
    fixture = fake.shape()
    # The fake builds the image from `release`; the LABEL still carries the version, which is the
    # arrangement a digest-pinned install produces.
    for d in fixture["deployments"]:
        d["version"] = "2026.9"
    report = status_for(tmp_path, fixture)
    assert check(report, "release.version")["status"] == "pass"
    assert report["drifted"] is False


def test_two_releases_running_at_once_is_a_blocker(tmp_path):
    """A stalled upgrade. Mixed versions against one database are only safe while a rollout is
    actually moving (ADR 0045's additive-migration window), and a stuck one is not moving."""
    fixture = fake.shape(deployments=deployments_with(**{
        "acp-api": {"version": "2026.7"}}))
    report = status_for(tmp_path, fixture)
    finding = check(report, "release.version")
    assert finding["status"] == "fail"
    assert finding["severity"] == "blocker"
    assert "MORE THAN ONE" in finding["detail"]


# ── the wrong document ────────────────────────────────────────────────────────

def test_the_wrong_document_is_named_rather_than_producing_bogus_drift(tmp_path):
    """An operator with several environments passes the wrong file eventually. Every comparison
    would then be against the wrong baseline, and the output would be a list of confident
    falsehoods that sends somebody to 'fix' a healthy installation."""
    report = status_for(tmp_path, fake.shape(profile="regulated", platform="gcp"))
    finding = check(report, "document.matches")
    assert finding["status"] == "fail"
    assert finding["severity"] == "blocker"
    assert "regulated" in finding["detail"]
    assert report["ok"] is False


def test_a_mismatched_document_stops_the_comparison(tmp_path):
    """It does NOT go on to report release and replica drift measured against a baseline it has
    just said is wrong. Health is still reported, because health does not depend on the document
    at all."""
    report = status_for(tmp_path, fake.shape(profile="regulated"))
    assert "release.version" not in ids(report)
    assert not any(i.startswith("replicas.") for i in ids(report))
    assert any(i.startswith("health.") for i in ids(report)), "health should still be reported"


def test_same_profile_in_a_different_namespace_compares_cleanly(tmp_path):
    """Staging and production are both `standard` on `azure`. They differ by namespace and
    cluster — which the operator already chose when they ran the command — so this check must not
    fire on them, or it would fire on the most ordinary multi-environment setup there is."""
    report = status_for(tmp_path, fake.HEALTHY, namespace="acp-staging")
    assert check(report, "document.matches")["status"] == "pass"


# ── health ────────────────────────────────────────────────────────────────────

def test_nothing_installed_is_a_definite_answer_not_an_error(tmp_path):
    report = status_for(tmp_path, fake.shape(deployments=[]))
    finding = check(report, "install.present")
    assert finding["status"] == "fail"
    assert report["installed"] is False
    assert report["ok"] is False


def test_a_crashlooping_container_is_reported_even_though_the_pod_is_running(tmp_path):
    """THE MOST COMMON BROKEN INSTALL, and the one a phase check misses.

    A pod whose container is in CrashLoopBackOff has phase `Running`. Reporting the phase alone
    would tell an operator their installation is up while a container restarts every thirty
    seconds — the opposite of what is happening.
    """
    fixture = fake.shape(pods=[{"name": "acp-api-abc", "phase": "Running", "containers": [
        {"ready": False, "restarts": 47, "waiting_reason": "CrashLoopBackOff",
         "message": "back-off 5m0s restarting failed container"}]}])
    report = status_for(tmp_path, fixture)
    finding = check(report, "pod.acp-api-abc")
    assert finding["status"] == "fail"
    assert "CrashLoopBackOff" in finding["detail"]
    assert "47 restart" in finding["detail"]
    assert report["ok"] is False


def test_a_pending_pod_reports_the_schedulers_reason(tmp_path):
    """"Pending" tells an operator something is wrong; "Insufficient cpu" tells them what to fix."""
    fixture = fake.shape(pods=[{"name": "acp-worker-assess-xyz", "phase": "Pending",
                                "containers": [],
                                "conditions": [{"type": "PodScheduled", "status": "False",
                                                "message": "0/3 nodes are available: "
                                                           "Insufficient cpu."}]}])
    report = status_for(tmp_path, fixture)
    assert "Insufficient cpu" in check(report, "pod.acp-worker-assess-xyz")["detail"]


def test_a_tier_short_of_its_ready_replicas_is_a_blocker(tmp_path):
    fixture = fake.shape(deployments=deployments_with(**{
        "acp-api": {"replicas": 2, "ready": 0}}))
    report = status_for(tmp_path, fixture)
    finding = check(report, "health.acp-api")
    assert finding["status"] == "fail"
    assert finding["severity"] == "blocker"


def test_an_autoscaled_tier_is_healthy_at_whatever_the_autoscaler_chose(tmp_path):
    """Health compares ready against the OBSERVED count, not against the document. Whether the
    autoscaler picked the right number is drift, and belongs to the other half of the report —
    conflating them would make a scaled-up tier look unhealthy."""
    fixture = fake.shape(deployments=deployments_with(**{
        "acp-worker-assess": {"replicas": None, "ready": 9}}))
    report = status_for(tmp_path, fixture)
    assert not any(i == "health.acp-worker-assess" for i in ids(report))


# ── the scalers and the migration ─────────────────────────────────────────────

def test_a_missing_scaledobject_is_reported(tmp_path):
    """doctor's silent failure from the other side: doctor asks whether KEDA is installed before
    the fact, this asks whether the scalers are actually there afterwards. One deleted by a
    partial upgrade leaves its tier pinned wherever it was, with nothing reporting it."""
    # One of the two autoscaled tiers keeps its scaler. Naming a tier the document does NOT
    # autoscale would not exercise this check at all — assess is pinned warm now, so a
    # ScaledObject on it is a different finding, not a smaller version of this one.
    report = status_for(tmp_path, fake.shape(scaled_objects=["acp-worker-discover"]))
    finding = check(report, "scalers.present")
    assert finding["status"] == "fail"
    assert "2 worker tier(s)" in finding["detail"]
    assert "only 1" in finding["detail"]


def test_scalers_unknown_when_keda_is_not_served(tmp_path):
    """"KEDA is not there" and "we could not ask" must not render the same — the first is a
    finding, the second is a gap in the report."""
    report = status_for(tmp_path, fake.without_api("scaledobjects.keda.sh"))
    finding = check(report, "scalers.present")
    assert finding["status"] == "unknown"


def test_a_failed_migration_says_the_running_code_may_be_the_previous_version(tmp_path):
    """Helm stops the release at its pre-upgrade hook, so the workloads can look perfectly healthy
    while being the OLD ones. An operator reading "all pods ready" has been told something true
    and deeply misleading."""
    report = status_for(tmp_path, fake.shape(
        jobs=[{"name": "acp-migrate", "failed": 1, "succeeded": 0, "active": 0}]))
    finding = check(report, "migration.result")
    assert finding["status"] == "fail"
    assert finding["severity"] == "blocker"
    assert "PREVIOUS version" in finding["remedy"]


def test_an_absent_migration_job_is_normal_and_not_reported(tmp_path):
    """The chart's hook-delete-policy removes it on success, so absence is the normal state after
    a clean install. Reporting it would make every healthy installation look broken."""
    report = status_for(tmp_path, fake.HEALTHY)
    assert "migration.result" not in ids(report)


def test_an_unreadable_resource_is_reported_rather_than_dropped(tmp_path):
    report = status_for(tmp_path, fake.shape(deny={"pods": "pods is forbidden"}))
    assert any(i.startswith("read.") for i in ids(report))


def test_deployments_unreadable_blocks_rather_than_reporting_nothing_installed(tmp_path):
    """"I cannot list deployments" and "nothing is installed" are opposite conclusions from the
    same empty result, and only one of them should send an operator to install something."""
    report = status_for(tmp_path, fake.shape(deny={"deployments": "forbidden"}))
    finding = check(report, "install.present")
    assert finding["status"] == "unknown"
    assert finding["severity"] == "blocker"
    assert report["ok"] is False


# ── read-only, still ──────────────────────────────────────────────────────────

def run_cli(tmp_path, fixture, *args):
    env = {**os.environ, **fake.install(tmp_path, fixture),
           "PYTHONPATH": str(PACKAGING / "cli")}
    return subprocess.run([sys.executable, "-m", "acpctl", "status", str(EXAMPLE),
                           "-n", "acp-production", *args],
                          capture_output=True, text=True, env=env, cwd=str(ROOT), timeout=120)


def test_status_never_asks_kubectl_to_change_anything(tmp_path):
    """installation.py reuses cluster.run(), so it inherits the read-verb allow-list — asserted
    on the log rather than assumed from the shared helper."""
    run_cli(tmp_path, fake.HEALTHY)
    log = (tmp_path / "kubectl.log").read_text(encoding="utf-8")
    assert log.strip(), "the command ran no kubectl at all"
    for line in log.strip().splitlines():
        verb = next(a for a in line.split() if not a.startswith("-"))
        assert verb in {"version", "api-resources", "get"}, f"non-read invocation: {line}"


def test_the_command_exits_zero_when_healthy_and_matching(tmp_path):
    proc = run_cli(tmp_path, fake.HEALTHY)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "Healthy, and matching the document." in proc.stdout


def test_the_command_exits_one_on_drift(tmp_path):
    proc = run_cli(tmp_path, fake.shape(release="2026.7"))
    assert proc.returncode == 1
    assert "DRIFT" in proc.stdout


def test_the_command_exits_two_when_the_cluster_is_unreachable(tmp_path):
    proc = run_cli(tmp_path, fake.shape(deny={"version": "connection refused"}))
    assert proc.returncode == 2
    assert "NOTHING WAS CHECKED" in proc.stdout


def test_the_json_output_is_machine_readable(tmp_path):
    payload = json.loads(run_cli(tmp_path, fake.HEALTHY, "--json").stdout)
    assert payload["ok"] is True
    assert payload["drifted"] is False
    assert {"id", "status", "severity", "detail", "remedy"} <= set(payload["checks"][0])


def test_status_is_no_longer_advertised_as_unimplemented():
    from acpctl.cli import NOT_YET_IMPLEMENTED
    assert "status" not in NOT_YET_IMPLEMENTED
