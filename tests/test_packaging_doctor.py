"""`acpctl doctor` — the checks, and the three-way outcome that keeps them honest.

THE PATTERN, same as the validate tests: take a healthy cluster, break exactly one thing, assert
the one finding. A check with no failing case is a claim rather than a check.

THE CASE THIS FILE CARES MOST ABOUT is not a failure at all — it is `unknown`. A check that could
not run has established nothing, and the checks most likely to be unrunnable (a forbidden
`api-resources`) are exactly the ones guarding failures that are otherwise silent. So
`test_an_unknown_blocking_check_is_not_ok` is the load-bearing test here: without it, doctor could
report a clean bill of health for a cluster it never managed to inspect.
"""
from __future__ import annotations

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


def diagnose(tmp_path, fixture, *, namespace="acp-production", example="standard-production"):
    """Run the real gather() against the fake kubectl, then the real diagnose()."""
    from acpctl import cluster as cluster_mod
    from acpctl import doctor as doctor_mod
    from acpctl.values import build_values

    env = fake.install(tmp_path, fixture)
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        facts = cluster_mod.gather(namespace=namespace)
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return doctor_mod.diagnose(build_values(load_example(example)), facts, namespace=namespace)


def status_of(report, check_id):
    for check in report["checks"]:
        if check["id"] == check_id:
            return check["status"]
    return None


def check(report, check_id):
    for c in report["checks"]:
        if c["id"] == check_id:
            return c
    raise AssertionError(f"no check {check_id!r}; have {[c['id'] for c in report['checks']]}")


def ids(report):
    return [c["id"] for c in report["checks"]]


# ── the harness itself ────────────────────────────────────────────────────────

def test_the_fake_kubectl_is_actually_being_used(tmp_path):
    """THE HARNESS'S OWN BITE CHECK.

    Every test below runs against a fake kubectl on PATH. If the fake were not being invoked,
    `gather` would report the cluster unreachable and the assertions would collapse into one
    uninformative failure mode — or worse, a test asserting a blocker would pass because the
    unreachable path also produces one. So: assert the fake ran, and that it was asked the
    questions doctor claims to ask.
    """
    report = diagnose(tmp_path, fake.HEALTHY)
    assert report["reachable"] is True
    log = (tmp_path / "kubectl.log").read_text(encoding="utf-8")
    assert "version -o json" in log
    assert "api-resources" in log
    assert "get nodes" in log


def test_the_fake_refuses_anything_that_is_not_a_read(tmp_path):
    """A guard on the guard: if acpctl ever starts mutating, the fake fails rather than pretending
    to apply something. Verified by asking it to, so the refusal is known to work."""
    env = fake.install(tmp_path, fake.HEALTHY)
    proc = subprocess.run([str(tmp_path / "bin" / "kubectl"), "apply", "-f", "x.yaml"],
                          capture_output=True, text=True, env={**os.environ, **env})
    assert proc.returncode != 0
    assert "must not mutate" in proc.stderr


# ── read-only, enforced ───────────────────────────────────────────────────────

@pytest.mark.parametrize("verb", ["apply", "create", "delete", "patch", "edit", "scale",
                                  "annotate", "label", "rollout", "exec", "drain", "cordon"])
def test_acpctl_refuses_to_run_a_mutating_kubectl_verb(verb):
    """PRD S22: no infrastructure mutation before RBAC and audit logging exist.

    Phase 0 kept that promise by patching `open` in a test — a guard that sees file writes and is
    blind to a subprocess. `doctor` introduced the subprocess, so the promise needed a new
    enforcement point or it would have quietly lapsed the moment acpctl learned to talk to a
    cluster. This is that point, and these are the verbs it must never reach.
    """
    from acpctl import cluster as cluster_mod
    with pytest.raises(cluster_mod.ForbiddenVerb):
        cluster_mod.run([verb, "deployment/acp-api"])


def test_a_mutating_verb_hidden_behind_flags_is_still_refused():
    """`run(["--context", "prod", "delete", ...])` — the check scans for the first non-flag
    argument rather than looking at args[0], because args[0] is not reliably the verb."""
    from acpctl import cluster as cluster_mod
    with pytest.raises(cluster_mod.ForbiddenVerb):
        cluster_mod.run(["--context", "prod", "delete", "ns/acp"])


def test_the_allowed_verbs_are_only_reads():
    from acpctl import cluster as cluster_mod
    assert cluster_mod.READ_VERBS == {"version", "api-resources", "get"}


# ── the cluster is not there ──────────────────────────────────────────────────

def test_an_unreachable_cluster_reports_nothing_checked_rather_than_passing(tmp_path):
    """The distinction the whole command rests on. An empty check list with `ok: true` would be a
    tool that reports success for a cluster it never contacted."""
    report = diagnose(tmp_path, fake.shape(deny={"version": "connection refused"}))
    assert report["reachable"] is False
    assert report["ok"] is False
    assert status_of(report, "cluster.reachable") == "unknown"


def test_a_kubectl_that_cannot_reach_the_api_server_is_not_reachable(tmp_path):
    """kubectl answers `version` with clientVersion ALONE when it cannot reach the API server,
    and exits zero doing it. Reading that as success would run every check below against nothing
    and report an empty cluster as a healthy one."""
    report = diagnose(tmp_path, fake.shape(server_version=None))
    assert report["reachable"] is False
    assert "could not reach the API server" in check(report, "cluster.reachable")["detail"]


# ── the healthy baseline ──────────────────────────────────────────────────────

def test_a_healthy_cluster_passes(tmp_path):
    report = diagnose(tmp_path, fake.HEALTHY)
    assert report["ok"] is True, [c for c in report["checks"] if c["status"] != "pass"]
    assert report["blockers"] == 0
    assert status_of(report, "keda.installed") == "pass"
    assert status_of(report, "networkpolicy.enforcement") == "pass"


# ── silent failure #1: KEDA ───────────────────────────────────────────────────

def test_missing_keda_is_a_blocker_that_explains_the_silence(tmp_path):
    """The headline case. Without KEDA the ScaledObjects apply cleanly and nothing reconciles
    them: the worker tiers sit at their floor and the queue grows, with no error, no event and no
    status field anywhere. The finding has to say that, because an operator who reads only
    "KEDA not installed" may reasonably decide to install it later."""
    report = diagnose(tmp_path, fake.without_api("scaledobjects.keda.sh"))
    assert status_of(report, "keda.installed") == "fail"
    assert report["ok"] is False
    finding = check(report, "keda.installed")
    assert finding["severity"] == "blocker"

    # The tiers are read from the document rather than named here. This assertion said "assess and
    # remediate" until the owner pinned assess warm at 5-5 (2026-09-05); the finding then correctly
    # named discover and remediate, and the test failed on the document rather than on the doctor.
    # Deriving it means the next scaling decision does not break this test either — with a
    # non-empty guard, because "every autoscaled tier is named" is satisfied by naming none.
    autoscaled = [name for name, tier in load_example("standard-production")["workers"].items()
                  if tier.get("autoscale")]
    assert autoscaled, "no worker tier autoscales in the example; this check proves nothing"
    for tier in autoscaled:
        assert tier in finding["detail"], (
            f"{tier} autoscales but the KEDA blocker does not name it; an operator cannot tell "
            "which tiers will sit silently at their floor")
    assert "do NOTHING" in finding["remedy"] or "DOING" in finding["remedy"].upper()


def test_keda_is_not_checked_when_nothing_needs_it(tmp_path):
    """The evaluation profile has no autoscaling, so a KEDA finding there would be noise — and a
    report with irrelevant findings is one that gets skimmed."""
    report = diagnose(tmp_path, fake.without_api("scaledobjects.keda.sh"),
                      example="evaluation", namespace="acp-eval")
    assert "keda.installed" not in ids(report)


# ── silent failure #2: NetworkPolicy enforcement ──────────────────────────────

def test_a_non_enforcing_cni_is_a_blocker_and_names_it(tmp_path):
    """Flannel accepts every NetworkPolicy and enforces none. The cluster reports nothing: no
    error on apply, no status saying unenforced. A regulated install can pass review in this
    state with completely open pod networking."""
    report = diagnose(tmp_path, fake.shape(
        kube_system_daemonsets=["kube-proxy", "kube-flannel-ds"]))
    finding = check(report, "networkpolicy.enforcement")
    assert finding["status"] == "fail"
    assert finding["severity"] == "blocker"
    assert "Flannel" in finding["detail"]
    assert report["ok"] is False


def test_an_unrecognised_cni_is_unknown_rather_than_a_pass_or_a_failure(tmp_path):
    """The list of policy-capable CNIs cannot be exhaustive, so "not on my list" must not mean
    "broken" — and it must not mean "fine" either. Claiming either would be asserting something
    about a security control this tool cannot observe."""
    report = diagnose(tmp_path, fake.shape(kube_system_daemonsets=["kube-proxy", "some-other-cni"]))
    finding = check(report, "networkpolicy.enforcement")
    assert finding["status"] == "unknown"
    assert finding["severity"] == "warning"


def test_the_passing_case_says_it_is_an_inference(tmp_path):
    """Enforcement has no API. A finding that reads like a proof would end an investigation that
    should continue — the CNI can be present and configured with policy disabled."""
    report = diagnose(tmp_path, fake.HEALTHY)
    detail = check(report, "networkpolicy.enforcement")["detail"]
    assert "inferred" in detail.lower()


# ── the unknown that must not read as a pass ──────────────────────────────────

def test_an_unknown_blocking_check_is_not_ok(tmp_path):
    """THE LOAD-BEARING TEST.

    A kubeconfig user without permission to run `api-resources` cannot be told whether KEDA is
    installed. That is not a pass, and it is not a warning either: the thing it guards fails
    silently, so an operator who installs on the strength of a green report gets exactly the
    outcome doctor exists to prevent. `ok` has to be false.
    """
    report = diagnose(tmp_path, fake.shape(deny={"api-resources": "forbidden"}))
    assert status_of(report, "keda.installed") == "unknown"
    assert check(report, "keda.installed")["severity"] == "blocker"
    assert report["ok"] is False, "an unknown blocking check reported as OK"


def test_a_check_that_could_not_run_is_reported_rather_than_omitted(tmp_path):
    """Silently dropping a check is the same failure in a different place: the report simply has
    one fewer line and nothing says why."""
    report = diagnose(tmp_path, fake.shape(deny={"nodes": "nodes is forbidden"}))
    assert status_of(report, "capacity.floor") == "unknown"
    assert any(c["id"].startswith("read.") for c in report["checks"])


def test_one_unreadable_resource_does_not_abort_the_whole_report(tmp_path):
    """An operator who can read nodes but not SecretStores should still learn everything else.
    Aborting would turn a partial answer into no answer."""
    report = diagnose(tmp_path, fake.shape(deny={"secretstores": "forbidden"}))
    assert status_of(report, "cluster.version") == "pass"
    assert status_of(report, "keda.installed") == "pass"


# ── the ordinary preflight ────────────────────────────────────────────────────

def test_missing_external_secrets_operator_is_a_blocker(tmp_path):
    report = diagnose(tmp_path, fake.without_api("externalsecrets.external-secrets.io",
                                                 "secretstores.external-secrets.io"))
    assert status_of(report, "externalsecrets.installed") == "fail"
    assert report["ok"] is False


def test_the_secret_store_check_lists_what_is_there_rather_than_guessing(tmp_path):
    """A CONTRACT GAP, reported as one.

    The deployment document has no field naming the SecretStore, and the chart derives one from
    the Helm RELEASE name — chosen at `helm install` time and absent from the document. So doctor
    cannot know which store the release will reference.

    It could guess by reimplementing the chart's `acp.fullname` here, which is a duplicate that
    drifts and would produce confident wrong answers. Instead it says it cannot know and lists
    what the namespace actually holds, which the operator can match themselves and which stays
    correct whatever the chart names things. The status is `unknown` rather than `pass`: this
    check established nothing about correctness.
    """
    report = diagnose(tmp_path, fake.shape(secret_stores=["team-vault-store", "other"]))
    finding = check(report, "externalsecrets.store")
    assert finding["status"] == "unknown"
    assert finding["severity"] == "warning"
    assert "team-vault-store" in finding["detail"] and "other" in finding["detail"]
    assert report["ok"] is True, "an unknowable name must not block an install"


def test_the_secret_store_check_says_so_when_the_namespace_has_none(tmp_path):
    """"none" and "could not list" are different facts and must not render the same — the first
    means the operator has something to create, the second means they have something to check."""
    report = diagnose(tmp_path, fake.shape(secret_stores=[]))
    assert "none" in check(report, "externalsecrets.store")["detail"]


def test_no_ingress_class_is_a_blocker(tmp_path):
    report = diagnose(tmp_path, fake.shape(ingress_classes=[]))
    assert status_of(report, "ingress.class") == "fail"


def test_a_cluster_too_small_for_the_replica_floor_is_a_blocker(tmp_path):
    """The FLOOR, not the ceiling. A cluster that cannot fit the minimum cannot install at all —
    pods stay Pending — which is different from one that merely cannot autoscale to the maximum."""
    report = diagnose(tmp_path, fake.shape(nodes=[{"cpu": "2", "memory": "4Gi"}]))
    finding = check(report, "capacity.floor")
    assert finding["status"] == "fail"
    assert finding["severity"] == "blocker"
    assert "MINIMUM" in finding["detail"]


def test_the_capacity_check_admits_it_ignores_existing_workloads(tmp_path):
    """It compares against total allocatable, so a cluster already running things looks roomier
    than it is. Saying so is the difference between a useful estimate and a wrong number."""
    report = diagnose(tmp_path, fake.HEALTHY)
    assert "ignoring existing workloads" in check(report, "capacity.floor")["detail"]


def test_an_old_kubernetes_is_a_blocker(tmp_path):
    report = diagnose(tmp_path, fake.shape(
        server_version={"major": "1", "minor": "21", "gitVersion": "v1.21.14"}))
    assert status_of(report, "cluster.version") == "fail"


@pytest.mark.parametrize("minor,expected_pass", [("29", True), ("29+", True), ("23", True),
                                                 ("22", False)])
def test_managed_clusters_report_a_patched_minor_version(tmp_path, minor, expected_pass):
    """GKE and EKS append "+" to the minor version to signal a patched build. Parsing that as an
    int fails, and a version check that cannot read the version would call every managed cluster
    unknown — which is most real clusters."""
    report = diagnose(tmp_path, fake.shape(
        server_version={"major": "1", "minor": minor, "gitVersion": f"v1.{minor}.0"}))
    assert (status_of(report, "cluster.version") == "pass") is expected_pass


def test_a_missing_namespace_is_a_warning_not_a_blocker(tmp_path):
    """helm --create-namespace makes it, so refusing to proceed would block a normal install."""
    report = diagnose(tmp_path, fake.shape(namespace_exists=False))
    finding = check(report, "cluster.namespace")
    assert finding["status"] == "fail"
    assert finding["severity"] == "warning"
    assert report["ok"] is True, "a missing namespace should not block"


def test_missing_metrics_server_blocks_a_cpu_autoscaled_api(tmp_path):
    report = diagnose(tmp_path, fake.without_api("nodes.metrics.k8s.io", "pods.metrics.k8s.io"))
    assert status_of(report, "metrics.server") == "fail"


def test_every_check_on_a_healthy_cluster_actually_passes(tmp_path):
    """THE CONTROL THAT WAS MISSING, and its absence shipped a bug.

    `metrics.custom` looked for the API group `custom.metrics.k8s.io` with a prefix test, but
    `kubectl api-resources -o name` prints `pods.custom.metrics.k8s.io` — the group is a SUFFIX.
    So the check reported the API missing on every cluster, including ones that served it.

    Its failure-case test passed the whole time, because a check that always says "missing" is
    indistinguishable from a check that is right about a broken cluster. Only asserting the
    healthy case separates them. `test_a_healthy_cluster_passes` did not catch it either: that
    check is a warning, so `ok` stayed True with a false finding sitting in the report.

    So this asserts on EVERY check individually rather than on the summary — a passing summary is
    exactly what hid it.
    """
    report = diagnose(tmp_path, fake.HEALTHY)
    not_passing = [(c["id"], c["status"], c["detail"]) for c in report["checks"]
                   if c["status"] != "pass" and c["id"] != "externalsecrets.store"]
    assert not not_passing, f"a healthy cluster produced findings: {not_passing}"


def test_a_missing_custom_metrics_api_is_only_a_warning(tmp_path):
    """Unlike the KEDA case this failure is visible: the HPA reports FailedGetPodsMetric in its
    own status, so an operator has somewhere to find it. Severity tracks how findable the failure
    is, not how much this tool dislikes it."""
    report = diagnose(tmp_path, fake.without_api("pods.custom.metrics.k8s.io"))
    finding = check(report, "metrics.custom")
    assert finding["status"] == "fail"
    assert finding["severity"] == "warning"
    assert report["ok"] is True


# ── the command ───────────────────────────────────────────────────────────────

def run_cli(tmp_path, fixture, *args):
    env = {**os.environ, **fake.install(tmp_path, fixture),
           "PYTHONPATH": str(PACKAGING / "cli")}
    return subprocess.run([sys.executable, "-m", "acpctl", "doctor", str(EXAMPLE),
                           "-n", "acp-production", *args],
                          capture_output=True, text=True, env=env, cwd=str(ROOT), timeout=120)


def test_the_command_exits_zero_on_a_healthy_cluster(tmp_path):
    proc = run_cli(tmp_path, fake.HEALTHY)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "No blockers" in proc.stdout


def test_the_command_exits_one_on_a_blocker(tmp_path):
    proc = run_cli(tmp_path, fake.without_api("scaledobjects.keda.sh"))
    assert proc.returncode == 1
    assert "keda.installed" in proc.stdout


def test_the_command_exits_two_when_the_cluster_is_unreachable(tmp_path):
    """Distinct from 1 on purpose: a pipeline should retry an unreachable cluster and must not
    retry a real blocker."""
    proc = run_cli(tmp_path, fake.shape(deny={"version": "connection refused"}))
    assert proc.returncode == 2
    assert "NOTHING WAS CHECKED" in proc.stdout


def test_the_json_output_is_machine_readable(tmp_path):
    proc = run_cli(tmp_path, fake.HEALTHY, "--json")
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert {"id", "status", "severity", "detail", "remedy"} <= set(payload["checks"][0])


def test_the_command_never_asks_kubectl_to_change_anything(tmp_path):
    """End to end, on the log the fake kept: every invocation the real command made was a read."""
    run_cli(tmp_path, fake.HEALTHY)
    log = (tmp_path / "kubectl.log").read_text(encoding="utf-8")
    assert log.strip(), "the command ran no kubectl at all"
    for line in log.strip().splitlines():
        verb = next(a for a in line.split() if not a.startswith("-"))
        assert verb in {"version", "api-resources", "get"}, f"non-read invocation: {line}"


def test_doctor_is_no_longer_advertised_as_unimplemented():
    from acpctl.cli import NOT_YET_IMPLEMENTED
    assert "doctor" not in NOT_YET_IMPLEMENTED


# ── doctor against the chart it is preflighting ───────────────────────────────

def test_doctor_checks_for_every_custom_resource_the_chart_renders():
    """THE DRIFT GUARD BETWEEN THE TWO HALVES OF PHASE 2.

    A custom resource rendered by the chart needs a controller in the cluster, and every such
    controller that is absent produces the same silent failure: the object applies cleanly and
    nothing reconciles it. doctor exists to catch exactly that — so a custom resource the chart
    renders and doctor does not check for is a hole of precisely the shape the command was built
    to close.

    Adding a `ServiceMonitor` for Prometheus, say, would be a one-line chart change that silently
    reintroduces the KEDA problem for a different operator, and every existing test would stay
    green. This fails until doctor learns about it.
    """
    import inspect
    import shutil
    import subprocess

    import yaml as _yaml

    helm = shutil.which("helm")
    if helm is None:
        pytest.skip("helm not installed; see test_packaging_chart.py::test_ci_has_helm")

    from acpctl import doctor as doctor_mod
    from acpctl.values import render_values_yaml

    chart = PACKAGING / "chart" / "acp"
    proc = subprocess.run([helm, "template", "acp", str(chart), "-f", "-"],
                          input=render_values_yaml(load_example("standard-production")),
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr

    # Built-in API groups ship with Kubernetes and need no operator; only third-party ones do.
    builtin = {"apps", "batch", "policy", "autoscaling", "networking.k8s.io", "rbac.authorization.k8s.io"}
    rendered_groups = set()
    for doc in _yaml.safe_load_all(proc.stdout):
        if not doc:
            continue
        api = doc.get("apiVersion", "")
        if "/" in api:
            group = api.split("/", 1)[0]
            if group not in builtin and not group.endswith(".k8s.io"):
                rendered_groups.add(group)

    assert rendered_groups, "no third-party resources found; this guard would pass vacuously"

    source = inspect.getsource(doctor_mod)
    unchecked = sorted(g for g in rendered_groups if g not in source)
    assert not unchecked, (
        f"the chart renders custom resources in {unchecked} but doctor never checks whether their "
        "controller is installed — those objects would apply cleanly and do nothing")
