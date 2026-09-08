"""The portable acceptance suite: its report contract, its eligibility rule, and its redaction.

WHAT THIS FILE IS MOSTLY ABOUT is not the scenarios. It is the one property the whole artifact
rests on: **a claim is only as true as the scenarios that actually passed**. So the eligibility
tests below take a run in which nothing failed — everything skipped, or everything came back
unknown — and assert that the report says NOT eligible, naming the ids. A report that says
`supported` because it did nothing is indistinguishable from a real pass by eye, and it is the
failure a suite ships by accident.

THE SECOND PROPERTY IS THAT IT RUNS WITHOUT INFRASTRUCTURE. `test_a_self_test_run_makes_no_real_
subprocess_or_network_call` makes `subprocess.run` and `urllib.request.urlopen` raise for the
duration of a full self-test. If the suite ever grows a direct shell-out or an HTTP call outside
the backend seam, that test fails rather than the suite quietly becoming un-runnable in CI.

THE PATTERN, same as tests/test_packaging_validate.py and tests/test_packaging_doctor.py: take the
healthy fake target, break exactly one thing, assert the one finding. A scenario with no failing
case is a claim, not a check.
"""
from __future__ import annotations

import copy
import dataclasses
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest

# packaging_helpers puts packaging/cli on sys.path (for acpctl); the acceptance package lives
# beside it under packaging/acceptance, mirroring the same layout for the same reason — see
# tests/test_packaging_layout.py.
from packaging_helpers import PACKAGING, ROOT

if str(PACKAGING / "acceptance") not in sys.path:
    sys.path.insert(0, str(PACKAGING / "acceptance"))

from acp_acceptance import SUITE_VERSION                                       # noqa: E402
from acp_acceptance import fake_target as fake                                 # noqa: E402
from acp_acceptance import report as report_mod                                # noqa: E402
from acp_acceptance import run as run_mod                                      # noqa: E402
from acp_acceptance import scenarios as scenarios_mod                          # noqa: E402
from acp_acceptance.context import ArtifactSink                                # noqa: E402
from acp_acceptance.report import (FAIL, PASS, SKIP, UNKNOWN, Outcome,         # noqa: E402
                                   ScenarioResult, support_claim)
from acp_acceptance.runner import run_suite                                    # noqa: E402
from acp_acceptance.target import CAPABILITIES, TargetError, parse_target      # noqa: E402

ACCEPTANCE = PACKAGING / "acceptance"

# The ten scenarios PRD §C names, and which claim each gates. WRITTEN OUT LITERALLY rather than
# derived from the registry: a test that reads the registry to check the registry passes whatever
# the registry says, including after somebody deletes a scenario.
EXPECTED_MVP = ["api-readiness", "worker-registration", "queue-and-progress",
                "fixture-workflow", "audit-and-diagnostics", "worker-restart"]
EXPECTED_SUPPORTED = ["dependency-degradation", "scale-updown", "upgrade-from-previous",
                      "backup-restore"]


def a_target(**overrides):
    """The self-test target, with overrides. Frozen dataclass, so this cannot mutate the shared one."""
    return dataclasses.replace(run_mod.SELF_TEST_TARGET, **overrides)


def run_fake(*, world=None, target=None, scenario_ids=None, artifacts=None):
    tgt = target or run_mod.SELF_TEST_TARGET
    backend = fake.FakeBackend(world if world is not None else fake.world(),
                               grants=frozenset(tgt.capabilities))
    run = run_suite(target=tgt, backend=backend, artifacts=artifacts,
                    scenario_ids=scenario_ids)
    return run, backend


def state_of(report, scenario_id):
    for entry in report["scenarios"]:
        if entry["id"] == scenario_id:
            return entry["state"]
    raise AssertionError(f"no scenario {scenario_id!r} in the report")


def entry_for(report, scenario_id):
    return next(e for e in report["scenarios"] if e["id"] == scenario_id)


def results(*states) -> list[ScenarioResult]:
    """Synthetic results, one per registered scenario, in registry order."""
    import datetime as dt
    moment = dt.datetime(2026, 9, 8, tzinfo=dt.timezone.utc)
    out = []
    for scn, state in zip(scenarios_mod.REGISTRY.values(), states):
        out.append(ScenarioResult(id=scn.id, title=scn.title, state=state, started_at=moment,
                                  duration_seconds=1.0, detail="synthetic"))
    return out


# ── the harness's own bite check ──────────────────────────────────────────────

def test_the_fake_backend_is_actually_being_driven():
    """THE GUARD ON EVERY OTHER TEST HERE.

    Every assertion below runs against the fake target. If the scenarios stopped calling the
    backend — an early return, a refactor that short-circuits — the suite would report a page of
    passes having done nothing, and these tests would agree with it. So: assert the fake was asked
    the questions the scenarios claim to ask.
    """
    run, backend = run_fake()
    kinds = backend.call_kinds()
    assert {"http", "kubectl", "helm", "sse", "fixture"} <= kinds, kinds
    paths = [e["path"] for e in backend.log if e["kind"] == "http"]
    assert "/healthz" in paths and "/readyz" in paths
    assert any(p.startswith("/scans") for p in paths)


def test_the_self_test_target_passes_every_scenario():
    """Not a claim about anything real — it is what makes the FAILING cases below meaningful.

    If the healthy fake did not pass, "break one thing and assert one finding" would be testing
    against a background of noise, and a scenario that fails for an unrelated reason would look
    like the check working.
    """
    run, _ = run_fake()
    states = {e["id"]: e["state"] for e in run.report["scenarios"]}
    assert set(states.values()) == {PASS}, states


# ── the report contract ───────────────────────────────────────────────────────

def test_the_report_validates_against_its_published_schema():
    run, _ = run_fake()
    assert report_mod.validate_report(run.report) == []


def test_the_schema_uses_no_keyword_the_evaluator_ignores():
    """The same guard tests/test_packaging_schema.py puts on the deployment schema.

    An evaluator that does not implement a keyword IGNORES it, and an ignored constraint reports
    every document as valid — so under-validation is invisible unless something checks the
    keywords themselves.
    """
    from acpctl.jsonschema_mini import ANNOTATIONS, SUPPORTED, keywords_used
    unknown = keywords_used(report_mod.load_schema()) - SUPPORTED - ANNOTATIONS
    assert not unknown, (f"report.schema.json uses {sorted(unknown)}, which jsonschema_mini does "
                         f"not implement, so those constraints are silently not enforced")


def test_the_schema_actually_rejects_a_malformed_report():
    """THE BITE CHECK ON THE SCHEMA ITSELF. A validator that accepts everything passes the test
    above too; this is what distinguishes a schema that constrains from one that decorates."""
    run, _ = run_fake()
    broken = copy.deepcopy(run.report)
    broken["scenarios"][0]["state"] = "probably-fine"
    assert report_mod.validate_report(broken), "an invalid state was accepted by the schema"

    missing = copy.deepcopy(run.report)
    del missing["supportClaim"]
    assert report_mod.validate_report(missing)


def test_the_report_names_the_suite_and_both_mandatory_lists():
    run, _ = run_fake()
    suite = run.report["suite"]
    assert suite["version"] == SUITE_VERSION
    assert suite["mandatoryForMvp"] == EXPECTED_MVP
    assert suite["mandatoryForSupported"] == EXPECTED_SUPPORTED
    assert suite["scenarioIds"] == EXPECTED_MVP + EXPECTED_SUPPORTED


def test_every_scenario_entry_carries_timing_and_a_detail():
    run, _ = run_fake()
    for entry in run.report["scenarios"]:
        assert entry["detail"].strip(), entry["id"]
        assert entry["durationSeconds"] >= 0
        assert entry["startedAt"].endswith("Z")


def test_artifacts_are_recorded_as_paths_relative_to_the_report(tmp_path):
    """An absolute path from the machine that produced the report is useless to its readers, and
    on a CI runner it leaks the job's directory layout into a customer-facing document."""
    sink = ArtifactSink(directory=tmp_path)
    run, _ = run_fake(artifacts=sink)
    paths = [p for entry in run.report["scenarios"] for p in entry["artifacts"]]
    assert paths, "no scenario produced an artifact, so this test proves nothing"
    for path in paths:
        assert not Path(path).is_absolute()
        assert (tmp_path / path).exists()


# ── the registry ──────────────────────────────────────────────────────────────

def test_the_registry_holds_exactly_the_ten_prd_scenarios():
    assert list(scenarios_mod.REGISTRY) == EXPECTED_MVP + EXPECTED_SUPPORTED


def test_each_scenario_gates_the_claim_the_prd_says_it_does():
    """Scenarios 1-6 gate the Kubernetes MVP claim; 7-10 gate `supported`. Encoded in
    `Scenario.claim` and derived everywhere else, so this is the only place it is written twice."""
    assert list(scenarios_mod.mandatory_for("mvp")) == EXPECTED_MVP
    assert list(scenarios_mod.mandatory_for("supported")) == EXPECTED_SUPPORTED


def test_every_scenario_declares_capabilities_that_exist():
    """A misspelled capability skips a mandatory scenario forever, and the report's reason names a
    capability no descriptor can grant — a claim that fails for a cause nobody can act on."""
    for scn in scenarios_mod.REGISTRY.values():
        unknown = sorted(set(scn.requires) - set(CAPABILITIES))
        assert not unknown, f"{scn.id} requires unknown capabilities {unknown}"


def test_a_duplicate_scenario_id_is_refused():
    with pytest.raises(ValueError, match="duplicate scenario id"):
        scenarios_mod.scenario(id="api-readiness", title="x", claim="mvp", requires=[],
                               proves="x")(lambda ctx: Outcome.passed("x"))


def test_the_synthetic_fixtures_the_suite_names_actually_exist():
    """The fixture list is not fiction.

    The fake target serves synthetic bytes for these paths, so nothing in the self-test would
    notice if a file were renamed or removed — and the first sign would be a certification run
    failing on somebody else's cluster.
    """
    for relative in scenarios_mod.FIXTURES:
        assert (ROOT / relative).exists(), f"{relative} is named by the suite and is not in the repo"


# ── the eligibility rule — the point of the whole artifact ────────────────────

def test_all_passing_against_a_real_target_is_eligible_for_both_claims():
    claim = support_claim(results(*[PASS] * 10),
                          mandatory_for_mvp=EXPECTED_MVP,
                          mandatory_for_supported=EXPECTED_SUPPORTED,
                          synthetic=False)
    assert claim == {"mvpEligible": True, "supportedEligible": True, "reason": claim["reason"]}
    assert "passed" in claim["reason"]


def test_a_fully_passing_synthetic_run_is_eligible_for_nothing():
    """THE TEST THAT STOPS SOMEBODY "FIXING" THE APPARENT INCONSISTENCY.

    Ten green scenarios and `mvpEligible: false` looks like a bug until you know what a synthetic
    run is: the fake backend passing its own fixtures establishes that the suite works and nothing
    at all about any target. PRD §7 requires a target to pass the acceptance, upgrade, restore and
    recovery gates before it is called supported, and a self-test passes none of them.

    The first draft of this suite got it wrong in the dangerous direction: a run that measured
    nothing emitted `mvpEligible: true`, distinguished from real evidence only by a target name
    that nobody scanning `supportClaim` would read.
    """
    run, _ = run_fake()
    assert run.report["synthetic"] is True
    assert {e["state"] for e in run.report["scenarios"]} == {PASS}
    claim = run.report["supportClaim"]
    assert claim["mvpEligible"] is False
    assert claim["supportedEligible"] is False
    assert "fake backend" in claim["reason"]
    # What the scenarios did is still reported — the states are facts about the run, and the
    # reason keeps them so the file is not merely a refusal.
    assert "every mandatory scenario passed" in claim["reason"]


def test_synthetic_defaults_to_true_where_it_is_ambiguous():
    """The safe direction is to under-claim. A caller that forgets the argument produces a report
    that refuses a claim; a default of false would mint acceptance evidence out of an omission —
    and the schema makes the field required so a consumer never has to guess what absent meant."""
    claim = support_claim(results(*[PASS] * 10), mandatory_for_mvp=EXPECTED_MVP,
                          mandatory_for_supported=EXPECTED_SUPPORTED)
    assert claim["mvpEligible"] is False
    assert "synthetic" in report_mod.load_schema()["required"]


def test_only_the_real_backend_counts_as_a_non_synthetic_run():
    """An allow-list, because the two mistakes are not symmetric: marking a real run synthetic
    loses a certification and somebody re-runs it, while marking a synthetic run real puts
    `mvpEligible: true` on a document that measured nothing — and that one does not correct
    itself. A backend added later is synthetic until somebody deliberately says otherwise.
    """
    from acp_acceptance.backend import SubprocessBackend
    from acp_acceptance.runner import is_synthetic
    assert is_synthetic(fake.FakeBackend(fake.world())) is True
    assert is_synthetic(SubprocessBackend(base_url="https://acp.invalid")) is False


def test_one_mandatory_failure_costs_the_claim():
    states = [PASS] * 10
    states[EXPECTED_MVP.index("worker-restart")] = FAIL
    claim = support_claim(results(*states), mandatory_for_mvp=EXPECTED_MVP,
                          mandatory_for_supported=EXPECTED_SUPPORTED)
    assert claim["mvpEligible"] is False
    assert claim["supportedEligible"] is False, "supported must require the MVP set as well"
    assert "worker-restart fail" in claim["reason"]


def test_a_suite_of_all_skips_is_not_eligible_and_the_reason_names_the_ids():
    """THE FAILURE THIS FORMAT EXISTS TO PREVENT. Nothing failed. Nothing ran either."""
    claim = support_claim(results(*[SKIP] * 10), mandatory_for_mvp=EXPECTED_MVP,
                          mandatory_for_supported=EXPECTED_SUPPORTED)
    assert claim["mvpEligible"] is False
    assert claim["supportedEligible"] is False
    for sid in EXPECTED_MVP:
        assert f"{sid} skip" in claim["reason"], claim["reason"]


def test_unknown_is_not_folded_into_pass():
    """`acpctl doctor`'s rule, carried into the suite: a check that could not run has established
    nothing, and a report that treats it as a pass means the opposite of what it says."""
    states = [PASS] * 10
    states[EXPECTED_MVP.index("audit-and-diagnostics")] = UNKNOWN
    claim = support_claim(results(*states), mandatory_for_mvp=EXPECTED_MVP,
                          mandatory_for_supported=EXPECTED_SUPPORTED)
    assert claim["mvpEligible"] is False
    assert "audit-and-diagnostics unknown" in claim["reason"]


def test_an_empty_mandatory_list_is_not_vacuously_eligible():
    """`all([])` is True. A mandatory list that arrived empty through a bug would otherwise
    certify anything at all — the same "eligible because nothing ran" failure, arriving through
    the rule instead of through the results."""
    claim = support_claim(results(*[PASS] * 10), mandatory_for_mvp=[],
                          mandatory_for_supported=[])
    assert claim["mvpEligible"] is False
    assert "no mandatory scenarios were declared" in claim["reason"]


def test_a_missing_result_is_not_a_pass():
    """Running a subset must not make the un-run scenarios disappear from the claim."""
    claim = support_claim(results(PASS), mandatory_for_mvp=EXPECTED_MVP,
                          mandatory_for_supported=EXPECTED_SUPPORTED)
    assert claim["mvpEligible"] is False
    assert "did not run" in claim["reason"]


def test_running_one_scenario_still_reports_the_full_mandatory_lists():
    run, _ = run_fake(scenario_ids=["api-readiness"])
    assert run.report["suite"]["mandatoryForMvp"] == EXPECTED_MVP
    assert run.report["supportClaim"]["mvpEligible"] is False
    assert run.report["summary"]["mandatoryFailures"] == [
        sid for sid in EXPECTED_MVP + EXPECTED_SUPPORTED if sid != "api-readiness"]


def test_mandatory_failures_lists_skips_as_well_as_failures():
    """Zero failures with no eligibility and nothing connecting the two is the contradiction that
    makes a report unreadable; `mandatoryFailures` is what connects them."""
    target = a_target(capabilities=frozenset({"api"}))
    run, _ = run_fake(target=target)
    assert run.report["summary"]["fail"] == 0
    assert "worker-restart" in run.report["summary"]["mandatoryFailures"]
    assert state_of(run.report, "worker-restart") == SKIP


# ── redaction ─────────────────────────────────────────────────────────────────

def test_no_credential_from_the_descriptor_reaches_the_serialised_report():
    """Feed the runner a target carrying a fake credential and grep the report for it."""
    secret = "s3cr3t-token-8f3a91d0"
    target = a_target(credentials={"bearerToken": secret},
                      kubeconfig_context="customer-prod-cluster-context")
    run, _ = run_fake(target=target)
    text = report_mod.dump(run.report)
    assert secret not in text
    assert "customer-prod-cluster-context" not in text
    assert run.report["target"] == {
        "name": "self-test", "platform": "kubernetes", "distribution": "fake-backend",
        "kubernetesVersion": "1.29.4", "namespace": "acp-self-test"}


def test_a_report_that_would_leak_a_credential_fails_instead_of_being_written():
    """THE BITE CHECK ON THE REDACTION. The test above passes if nothing ever collects a secret —
    including if `assert_no_secrets` did nothing at all. So: put the secret in the report by hand
    and prove the guard fires."""
    secret = "s3cr3t-token-8f3a91d0"
    run, _ = run_fake(target=a_target(credentials={"bearerToken": secret}))
    poisoned = copy.deepcopy(run.report)
    poisoned["scenarios"][0]["evidence"]["authorization"] = f"Bearer {secret}"
    with pytest.raises(report_mod.SecretLeak):
        report_mod.assert_no_secrets(poisoned, [secret])


def test_the_leak_message_does_not_repeat_the_secret():
    with pytest.raises(report_mod.SecretLeak) as caught:
        report_mod.assert_no_secrets({"x": "hunter2-hunter2"}, ["hunter2-hunter2"])
    assert "hunter2-hunter2" not in str(caught.value)


def test_the_diagnostics_scenario_fails_when_the_export_carries_this_runs_credential():
    """PRD §13, checked by looking rather than by trusting the export's own `redacted: true`."""
    secret = "leaked-value-01234567"
    world = fake.world()
    world["support_bundle"] = dict(world["support_bundle"], postgres_url=f"postgres://{secret}@db")
    run, _ = run_fake(world=world, target=a_target(credentials={"bearerToken": secret}),
                      scenario_ids=["audit-and-diagnostics"])
    entry = entry_for(run.report, "audit-and-diagnostics")
    assert entry["state"] == FAIL
    assert "credentials" in entry["detail"]
    assert secret not in report_mod.dump(run.report)


# ── no infrastructure, and that is enforced ───────────────────────────────────

def test_a_self_test_run_makes_no_real_subprocess_or_network_call(monkeypatch, tmp_path):
    """THE PROPERTY CI DEPENDS ON, asserted from both sides.

    From the outside: `subprocess.run` and `urllib.request.urlopen` raise for the duration, so a
    scenario that shelled out directly — bypassing the backend seam — fails the run rather than
    silently making the suite un-runnable where kubectl and helm are absent.

    From the inside: the fake's log is checked to contain the kubectl and helm calls the scenarios
    made, so this cannot pass by the suite doing nothing at all.
    """
    def refuse(*args, **kwargs):
        raise AssertionError("the acceptance suite reached a real subprocess/network call")

    monkeypatch.setattr(subprocess, "run", refuse)
    monkeypatch.setattr(urllib.request, "urlopen", refuse)

    out = tmp_path / "report.json"
    code = run_mod.main(["--self-test", "--out", str(out), "--quiet"])
    assert code == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report_mod.validate_report(report) == []
    # A synthetic run claims nothing, however green it is — see
    # test_a_fully_passing_synthetic_run_is_eligible_for_nothing. What this test is about is that
    # the run happened at all without a cluster, a network, kubectl or helm.
    assert report["synthetic"] is True
    assert report["supportClaim"]["mvpEligible"] is False
    assert report["supportClaim"]["supportedEligible"] is False
    assert {e["state"] for e in report["scenarios"]} == {PASS}


def test_the_backend_refuses_a_mutation_the_descriptor_did_not_grant():
    """The second lock. The runner skips a scenario whose capabilities are missing; this is what
    stops a scenario with the WRONG `requires` set from restarting pods anyway."""
    from acp_acceptance.backend import NotAuthorized
    backend = fake.FakeBackend(fake.world(), grants=frozenset({"api"}))
    with pytest.raises(NotAuthorized):
        backend.kubectl(["rollout", "restart", "deployment/acp-worker-assess"],
                        requires="workload-restart")
    with pytest.raises(NotAuthorized):
        backend.kubectl(["delete", "pod", "acp-api-0"])          # a mutation with no `requires`
    assert backend.kubectl(["get", "deployments", "-o", "json"]).ok


def test_a_scenario_that_raises_is_unknown_rather_than_fail(monkeypatch):
    """A suite bug must not be reported as a target defect: it sends an operator to debug their
    cluster because our code has an AttributeError."""
    def explode(ctx):
        raise RuntimeError("boom")

    original = scenarios_mod.REGISTRY["api-readiness"]
    monkeypatch.setitem(scenarios_mod.REGISTRY, "api-readiness",
                        dataclasses.replace(original, run=explode))
    run, _ = run_fake(scenario_ids=["api-readiness"])
    entry = entry_for(run.report, "api-readiness")
    assert entry["state"] == UNKNOWN
    assert "fault in the suite" in entry["detail"]


# ── one failing case per scenario family ──────────────────────────────────────

def test_a_tier_with_pods_but_no_heartbeat_fails_worker_registration():
    """The failure that reads as healthy in kubectl: Ready pods that never registered."""
    world = fake.world()
    # Present in the roles block, so the tier HAS registered at some point, but stale — which
    # store.worker_roles_status draws as a different fact from a role that never beaten, and needs
    # a different fix (lost Redis, not a tier that never started).
    world["workers"]["remediate"] = dict(world["workers"]["remediate"], age_s=3600.0, alive=False)
    run, _ = run_fake(world=world, scenario_ids=["worker-registration"])
    entry = entry_for(run.report, "worker-registration")
    assert entry["state"] == FAIL
    assert "remediate" in entry["detail"]


def test_an_unstamped_build_fails_api_readiness():
    world = fake.world()
    world["healthz"] = dict(world["healthz"], version_stamped=False)
    run, _ = run_fake(world=world, scenario_ids=["api-readiness"])
    assert state_of(run.report, "api-readiness") == FAIL


def test_an_unreachable_api_is_unknown_not_fail():
    """Nothing about the target was established by a call that never connected."""
    world = fake.world(faults={"GET /healthz": {"error": "connection refused"}})
    run, _ = run_fake(world=world, scenario_ids=["api-readiness"])
    entry = entry_for(run.report, "api-readiness")
    assert entry["state"] == UNKNOWN
    assert "connection refused" in entry["detail"]


def test_a_build_that_does_not_serve_a_required_surface_is_unknown():
    """A 404 says this build has no such surface — which is not a finding about workers."""
    world = fake.world(faults={"GET /readyz": {"status": 404}})
    run, _ = run_fake(world=world, scenario_ids=["worker-registration"])
    entry = entry_for(run.report, "worker-registration")
    assert entry["state"] == UNKNOWN
    assert "does not serve" in entry["detail"]


def test_output_that_lives_only_on_ephemeral_disk_fails_the_fixture_workflow():
    """PRD §12/§20.5. The file exists, is downloadable and is correct — until the pod moves."""
    world = fake.world(artifact_scheme="file")
    run, _ = run_fake(world=world, scenario_ids=["fixture-workflow"])
    entry = entry_for(run.report, "fixture-workflow")
    assert entry["state"] == FAIL
    assert "ephemeral" in entry["detail"]


def test_a_stream_that_delivers_nothing_fails_queue_and_progress():
    """A buffering proxy: every job succeeds and every UI sits at 'starting…'."""
    world = fake.world(faults={"SSE /scans/{sid}/events": {"events": []}})
    run, _ = run_fake(world=world, scenario_ids=["queue-and-progress"])
    entry = entry_for(run.report, "queue-and-progress")
    assert entry["state"] == FAIL
    assert "delivered no events" in entry["detail"]


def test_a_restart_that_duplicates_authoritative_output_fails():
    """The silent half of scenario 6: two corrected files, both written successfully."""
    world = fake.world(duplicate_artifacts=True)
    run, _ = run_fake(world=world, scenario_ids=["worker-restart"])
    entry = entry_for(run.report, "worker-restart")
    assert entry["state"] == FAIL
    assert "two authoritative outputs" in entry["detail"]


def test_a_restart_that_loses_work_fails():
    world = fake.world(lose_work_on_restart=True)
    run, _ = run_fake(world=world, scenario_ids=["worker-restart"])
    entry = entry_for(run.report, "worker-restart")
    assert entry["state"] == FAIL
    assert "did not complete" in entry["detail"]


def test_an_api_that_stays_ready_without_its_database_fails_degradation():
    """The dangerous case: Kubernetes goes on routing traffic to a backend that cannot serve it."""
    world = fake.world()
    world["faults"] = {"GET /readyz": {"status": 200, "json": {"ready": True, "checks": {}}}}
    run, _ = run_fake(world=world, scenario_ids=["dependency-degradation"])
    entry = entry_for(run.report, "dependency-degradation")
    assert entry["state"] == FAIL
    assert "absorbed" in entry["detail"]


def test_a_managed_dependency_that_cannot_be_taken_away_is_unknown_not_pass():
    """A target with managed Redis is a legitimate shape; its degradation behaviour is simply not
    established here, and calling that a pass would certify something nobody observed."""
    world = fake.world(faults={"kubectl scale deployment/acp-redis":
                               {"returncode": 1, "stderr": "no such deployment"}})
    run, _ = run_fake(world=world, scenario_ids=["dependency-degradation"])
    entry = entry_for(run.report, "dependency-degradation")
    assert entry["state"] == UNKNOWN
    assert "redis" in entry["detail"]


def test_a_scale_down_that_abandons_work_fails():
    world = fake.world(drains_on_scale_down=False)
    run, _ = run_fake(world=world, scenario_ids=["scale-updown"])
    entry = entry_for(run.report, "scale-updown")
    assert entry["state"] == FAIL
    assert "drain" in entry["detail"]


def test_an_unpinned_release_cannot_demonstrate_the_upgrade_requirement():
    """PRD §15 requires deploying by immutable digest, so an upgrade against a tag has not shown
    it however cleanly the upgrade itself ran."""
    unpinned = dataclasses.replace(
        run_mod.SELF_TEST_TARGET.release, pinned=False,
        components={"acp-web-api": {"repository": "r/acp-web-api", "digest": ""}})
    run, _ = run_fake(target=a_target(release=unpinned), scenario_ids=["upgrade-from-previous"])
    entry = entry_for(run.report, "upgrade-from-previous")
    assert entry["state"] == FAIL
    assert "pinned" in entry["detail"]


def test_no_previous_release_skips_the_upgrade_scenario():
    """Honest, and it still costs the `supported` claim — which is the intended consequence."""
    release = dataclasses.replace(run_mod.SELF_TEST_TARGET.release, previous_version="")
    run, _ = run_fake(target=a_target(release=release), scenario_ids=["upgrade-from-previous"])
    assert state_of(run.report, "upgrade-from-previous") == SKIP


def test_a_backup_with_no_restore_fails():
    """PRD §16: a backup is not healthy until a restore has succeeded. A backup job exiting zero
    proves a file was written and nothing about whether it can be read back."""
    world = fake.world(faults={"kubectl create job": {"returncode": 1,
                                                      "stderr": "cronjob acp-restore not found"}})
    run, _ = run_fake(world=world, scenario_ids=["backup-restore"])
    entry = entry_for(run.report, "backup-restore")
    # The backup itself is what fails to be created here, so the honest answer is `unknown`:
    # neither backup nor restore was exercised.
    assert entry["state"] == UNKNOWN
    assert "not exercised" in entry["detail"]


# ── the target descriptor ─────────────────────────────────────────────────────

def test_an_unknown_capability_is_refused_rather_than_ignored():
    """A misspelled capability silently skips a mandatory scenario, and the claim then fails for a
    reason nobody can find in the descriptor."""
    with pytest.raises(TargetError, match="unknown capabilities"):
        parse_target({"kind": "ACPAcceptanceTarget", "name": "x",
                      "capabilities": ["fault_injection"]})


def test_pinned_is_derived_from_the_digests_not_declared():
    target = parse_target({
        "kind": "ACPAcceptanceTarget", "name": "x",
        "release": {"pinned": True, "components": {"acp-web-api": {"repository": "r"}}}})
    assert target.release.pinned is False, "a component with no digest cannot make a release pinned"


def test_a_release_with_no_components_is_not_pinned():
    """An empty set is not 'all of them'."""
    target = parse_target({"kind": "ACPAcceptanceTarget", "name": "x", "release": {}})
    assert target.release.pinned is False


def test_the_example_descriptor_parses_and_grants_everything(monkeypatch):
    """The example is the file operators copy. One that does not parse teaches them to guess."""
    monkeypatch.setenv("ACP_ACCEPTANCE_TOKEN", "example-token-value")
    monkeypatch.setenv("ACP_MONITOR_KEY", "example-monitor-key")
    from acp_acceptance.target import load_target
    target = load_target(ACCEPTANCE / "example-target.yaml")
    assert target.capabilities == frozenset(CAPABILITIES)
    assert target.release.pinned is True
    assert "example-token-value" in target.secret_values()


def test_an_unset_environment_variable_is_an_error_not_an_empty_credential(monkeypatch):
    """A run that silently authenticates as nobody produces a page of `unknown` results whose
    cause is one missing export and appears nowhere in the report."""
    monkeypatch.delenv("ACP_ACCEPTANCE_TOKEN", raising=False)
    with pytest.raises(TargetError, match="ACP_ACCEPTANCE_TOKEN"):
        parse_target({"kind": "ACPAcceptanceTarget", "name": "x",
                      "credentials": {"bearerToken": "${ACP_ACCEPTANCE_TOKEN}"}})


# ── the command line ──────────────────────────────────────────────────────────

def test_self_test_exits_zero_and_writes_a_valid_report(tmp_path, capsys):
    """Exit 0 here means THE SUITE WORKS, not that anything is eligible — and the terminal says
    which, on its first line, because a run is usually remembered as the green lines somebody
    glanced at an hour ago."""
    out = tmp_path / "report.json"
    assert run_mod.main(["--self-test", "--out", str(out)]) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report_mod.validate_report(report) == []
    printed = capsys.readouterr().out
    assert "SYNTHETIC RUN" in printed
    assert "mvpEligible: false" in printed
    assert "fake backend" in printed


def test_a_mandatory_failure_and_a_could_not_run_have_different_exit_codes(tmp_path):
    """A CI gate must not treat "your cluster loses work when a worker restarts" and "you did not
    grant fault injection" as the same event."""
    failing = copy.deepcopy(run_fake(world=fake.world(duplicate_artifacts=True))[0].report)
    assert run_mod._exit_code(failing, "mvp") == run_mod.EXIT_MANDATORY_FAILURE

    skipped, _ = run_fake(target=a_target(capabilities=frozenset({"api"})))
    assert run_mod._exit_code(skipped.report, "mvp") == run_mod.EXIT_COULD_NOT_RUN


def test_the_claim_flag_chooses_which_mandatory_set_gates_the_exit_code():
    """An MVP-eligible target that skips the operational scenarios exits 0 for --claim mvp and 2
    for --claim supported. Same report, two questions."""
    run, _ = run_fake(target=a_target(capabilities=frozenset({"api"})))
    mvp_only = copy.deepcopy(run.report)
    for entry in mvp_only["scenarios"]:
        if entry["id"] in EXPECTED_MVP:
            entry["state"] = PASS
    assert run_mod._exit_code(mvp_only, "mvp") == run_mod.EXIT_OK
    assert run_mod._exit_code(mvp_only, "supported") == run_mod.EXIT_COULD_NOT_RUN


def test_a_usage_error_exits_three_not_two(capsys):
    """argparse's own exit code is 2, and 2 means "retryable" here — a CI gate retrying a
    misspelled flag would loop forever."""
    assert run_mod.main([]) == run_mod.EXIT_USAGE
    assert run_mod.main(["--self-test", "--target", "x.yaml"]) == run_mod.EXIT_USAGE
    assert run_mod.main(["--self-test", "--scenario", "no-such-scenario"]) == run_mod.EXIT_USAGE
    with pytest.raises(SystemExit) as caught:
        run_mod.main(["--nonsense"])
    assert caught.value.code == run_mod.EXIT_USAGE


def test_list_names_every_scenario_and_the_claim_it_gates(capsys):
    assert run_mod.main(["--list"]) == 0
    out = capsys.readouterr().out
    for sid in EXPECTED_MVP + EXPECTED_SUPPORTED:
        assert sid in out
    assert out.count("mandatory for MVP") == len(EXPECTED_MVP)
    assert out.count("mandatory for `supported`") == len(EXPECTED_SUPPORTED)


def test_the_readme_states_that_no_target_has_passed_yet():
    """The claim this whole directory is about. If a target ever does pass, this line changes with
    the evidence attached — not because somebody read the suite and assumed."""
    text = (ACCEPTANCE / "README.md").read_text(encoding="utf-8")
    assert "No target has passed this suite" in text
    assert "planned" in text


# ── the suite's API contract versus the application's actual routes ───────────
#
# WHY THIS SECTION EXISTS. Every test above passed while the suite spoke a contract the
# application has never served: it POSTed a JSON body of fixture names to `/scans`, whose real
# signature is `source: str = Query(..., pattern="^(local|drive|sharepoint)$")` — a 422 before any
# handler runs — and it polled `/scans/{sid}/status` for `files_done`, which is ADR 0026's
# Accessibility Status roll-up and has never carried that field. Both would have reported a
# failing TARGET, on a healthy cluster, for a defect entirely inside this suite.
#
# The fake passed because the fake had been written from the same assumption. That is the failure
# mode CLAUDE.md calls a check that cannot fail, and the fix is not "be more careful with the
# fake": it is to compare the suite's paths against `api/routes/` in a test that needs no cluster.

API_ROUTES = ROOT / "api" / "routes"

# (constant name, HTTP method, whether the application serves it today). The third column is the
# assertion, in both directions: a path marked served that disappears fails, and a path marked
# MISSING that someone implements ALSO fails — with a message saying to move it, because a
# scenario reporting `unknown: this build does not serve X` after X shipped is a scenario that
# silently stopped measuring anything.
SUITE_PATHS = [
    ("PATH_HEALTH", "get", True),
    ("PATH_READY", "get", True),
    ("PATH_READY_ROLES", "get", True),
    ("PATH_SCANS", "post", True),
    ("PATH_SCAN_LIVE", "get", True),
    ("PATH_SCAN_EVENTS", "get", True),
    ("PATH_SCAN_ASSESS", "post", True),
    ("PATH_SCAN_REMEDIATE", "post", True),
    ("PATH_JOB", "get", True),
    # PRD §12/§13 surfaces the acceptance criteria need and no build serves yet. Their scenarios
    # report `unknown`, never a pass — see the kind-cluster job's expected-outcome table.
    ("PATH_ARTIFACTS", "get", False),
    ("PATH_AUDIT", "get", False),
    ("PATH_SUPPORT_BUNDLE", "get", False),
]


def _route_decorators() -> set[tuple[str, str]]:
    """Every `@router.<verb>("<path>")` in api/routes, as (verb, path)."""
    import re as _re
    found = set()
    for source in sorted(API_ROUTES.glob("*.py")):
        for verb, path in _re.findall(r'@router\.(get|post|put|patch|delete)\(\s*"([^"]+)"',
                                      source.read_text(encoding="utf-8")):
            found.add((verb, path))
    return found


def _path_pattern(template: str) -> str:
    """A suite path template as a regex over route paths.

    The two spell their parameters differently and always will — the suite says `{sid}` where
    `scans.py` says `{scan_id}`, and `{jid}` where it says `{job_id}` — so the comparison is on
    the SHAPE of the path, not on the parameter names. Query strings are stripped: they are the
    caller's business, and `_route_decorators` never sees them.
    """
    import re as _re
    base = template.split("?", 1)[0]
    return "^" + _re.sub(r"\\\{[a-zA-Z_]+\\\}", r"\\{[a-zA-Z_]+(?::path)?\\}",
                         _re.escape(base)) + "$"


@pytest.mark.parametrize("const,verb,served", SUITE_PATHS)
def test_every_path_the_suite_probes_matches_the_applications_actual_routes(const, verb, served):
    import re as _re
    template = getattr(scenarios_mod, const)
    pattern = _path_pattern(template)
    hits = sorted(p for v, p in _route_decorators() if v == verb and _re.match(pattern, p))
    if served:
        assert hits, (
            f"{const} = {template!r} is declared as a path the application serves, and no "
            f"@router.{verb} in api/routes matches it. Either the route moved and the scenarios "
            f"that probe it now report a target failure that is really ours, or this entry is "
            f"wrong. Do not relax this test — fix the constant.")
    else:
        assert not hits, (
            f"{const} = {template!r} is declared MISSING, and api/routes now serves {hits}. "
            f"Its scenario is currently reporting `unknown: this build does not serve X` and has "
            f"therefore stopped measuring anything. Move it to served=True and re-check what the "
            f"scenario asserts.")


def test_the_scan_start_call_carries_source_local_and_sends_no_body():
    backend = fake.FakeBackend(grants=frozenset(CAPABILITIES))
    ctx_target = run_mod.SELF_TEST_TARGET
    from acp_acceptance.context import ScenarioContext
    ctx = ScenarioContext(target=ctx_target, backend=backend, artifacts=ArtifactSink())
    sid, failure = scenarios_mod._start_scan(ctx)
    assert failure is None, failure.detail
    starts = [e for e in backend.log if e["kind"] == "http" and e["method"] == "POST"
              and e["path"].startswith("/scans?")]
    assert starts, f"no query-string POST to /scans in the log: {backend.log}"
    assert "source=local" in starts[0]["path"], starts[0]["path"]
    assert "queue=true" in starts[0]["path"], (
        "the scan must be QUEUED — with queue=false discovery runs inside the API process and a "
        "green report would say nothing about whether any worker ever claimed a job")


def test_the_fake_refuses_a_scan_start_that_omits_source_exactly_as_fastapi_would():
    """The bite check. If this fake ever accepts the old shape again, the whole suite goes back to
    passing a contract no cluster serves."""
    backend = fake.FakeBackend(grants=frozenset(CAPABILITIES))
    resp = backend.http("POST", "/scans", body={"fixtures": ["a.docx"], "source": "acceptance"})
    assert resp.status == 422, (
        f"the fake accepted a JSON-body scan start ({resp.status}); the application answers 422 "
        f"for a missing `source` query parameter, and a fake that is wrong in a different way "
        f"than the application is worse than no fake")


def test_the_suite_polls_live_and_not_status():
    backend = fake.FakeBackend(grants=frozenset(CAPABILITIES))
    from acp_acceptance.context import ScenarioContext
    ctx = ScenarioContext(target=run_mod.SELF_TEST_TARGET, backend=backend,
                          artifacts=ArtifactSink())
    sid, failure = scenarios_mod._start_scan(ctx)
    assert failure is None
    snap, failure = scenarios_mod._await_scan(ctx, sid)
    assert failure is None, failure.detail
    polled = [e["path"] for e in backend.log if e["kind"] == "http" and e["method"] == "GET"]
    assert any(p.endswith("/live") for p in polled), polled
    assert not any(p.endswith("/status") for p in polled), (
        "/scans/{sid}/status is ADR 0026's Accessibility Status roll-up, not scan progress — it "
        "never carries a completion count, so polling it reads as a scan permanently at zero")


def test_a_run_that_is_not_available_to_this_caller_is_unknown_rather_than_a_failure():
    """`/live` answers `available: false` for an unknown OR FOREIGN scan. Reporting that as a
    target failure sends an operator to debug a cluster over an identity mismatch."""
    backend = fake.FakeBackend(grants=frozenset(CAPABILITIES))
    from acp_acceptance.context import ScenarioContext
    ctx = ScenarioContext(target=run_mod.SELF_TEST_TARGET, backend=backend,
                          artifacts=ArtifactSink())
    snap, failure = scenarios_mod._await_scan(ctx, "no-such-scan")
    assert snap is None
    assert failure is not None and failure.state == UNKNOWN, failure
    assert "not available" in failure.detail


def test_keep_alive_frames_are_not_counted_as_live_progress():
    """The stream carries `: keep-alive` comment frames between snapshots. Counting them would let
    a stream that delivers nothing but keep-alives report live progress."""
    run, _ = run_fake(scenario_ids=["queue-and-progress"])
    entry = entry_for(run.report, "queue-and-progress")
    assert entry["state"] == PASS, entry
    frames = entry["evidence"]["snapshotFrames"]
    backend = fake.FakeBackend(grants=frozenset(CAPABILITIES))
    from acp_acceptance.context import ScenarioContext
    ctx = ScenarioContext(target=run_mod.SELF_TEST_TARGET, backend=backend,
                          artifacts=ArtifactSink())
    sid, _ = scenarios_mod._start_scan(ctx)
    delivered = backend.sse(f"/scans/{sid}/events", max_events=10)
    assert any(f.get("data") == "" for f in delivered), (
        "the fake stopped emitting keep-alive frames, so this test no longer proves they are "
        "excluded")
    assert frames < len(delivered), (
        f"every one of the {len(delivered)} delivered frames was counted as progress, keep-alives "
        f"included")


def test_the_suite_takes_no_reading_through_a_provider_specific_surface():
    """PRD §2.9: provider differences live in infrastructure adapters, not in the portable suite.

    THE DEFECT THIS CATCHES SHIPPED. `worker-registration` — the scenario that decides whether any
    worker tier registered at all — read `/control/workers/capacity`, which is Azure Container
    Apps: it queries ACA replica counts and Azure Monitor, and with no Azure configured returns
    `_empty_capacity(False)`, a block carrying no `roles` key. Against any Kubernetes cluster the
    scenario would have reported "no worker tier registered for discovery, assess, remediate" —
    a total, confident, wrong failure, on a target whose workers were heartbeating fine.

    The tell was in the route's own module: a handler gated on `_AZ_CONFIGURED` cannot answer
    portably. So that is what this asserts, rather than a hand-kept list of banned paths.
    """
    import re as _re
    offenders = []
    for const, verb, served in SUITE_PATHS:
        if not served:
            continue
        pattern = _path_pattern(getattr(scenarios_mod, const))
        for source in sorted(API_ROUTES.glob("*.py")):
            text = source.read_text(encoding="utf-8")
            hits = [p for v, p in _re.findall(
                r'@router\.(get|post|put|patch|delete)\(\s*"([^"]+)"', text)
                if v == verb and _re.match(pattern, p)]
            if hits and "_AZ_CONFIGURED" in text:
                offenders.append(f"{const} -> {source.name}{hits}")
    assert not offenders, (
        "the acceptance suite probes a route whose module gates on Azure configuration: "
        f"{offenders}. A portable suite certifying six platforms cannot take a reading through "
        f"a provider adapter — on every non-Azure target that route degrades to an empty block "
        f"and the scenario reports a failure that is about the adapter, not the target.")


# ── what the first real reference-cluster run found ───────────────────────────
#
# Three defects, all in this suite, none of them visible until it met an API server. Recorded as
# tests because each one produced a CONFIDENT WRONG STATEMENT ABOUT THE CLUSTER, which is the
# failure mode a suite whose whole job is honest reporting can least afford.

def test_a_discover_only_run_ending_in_discovered_is_a_success_not_an_unmodelled_state():
    """`discovered` is where a Discover-only scan STOPS. `completed_at` stays NULL until somebody
    runs Assess (store.py:308, 3343), so a suite waiting for `completed` waits forever on a scan
    that finished — which is what the first reference-cluster run reported, twice."""
    assert "discovered" in scenarios_mod.RUN_SUCCEEDED_STATES
    backend = fake.FakeBackend(grants=frozenset(CAPABILITIES))
    from acp_acceptance.context import ScenarioContext
    ctx = ScenarioContext(target=run_mod.SELF_TEST_TARGET, backend=backend,
                          artifacts=ArtifactSink())
    sid, _ = scenarios_mod._start_scan(ctx)
    snap, failure = scenarios_mod._await_scan(ctx, sid)
    assert failure is None, failure.detail
    assert snap["state"] == "discovered", snap["state"]


def test_a_queued_run_is_polled_rather_than_reported_unmodelled():
    """`queued` is the state before a worker claims the job. It is also NOT in
    `live_snapshot._ACTIVE_STATES`, so the snapshot reports `active: false` for it — which is why
    this must be modelled explicitly and never derived from that boolean."""
    assert "queued" in scenarios_mod.RUN_IN_PROGRESS_STATES
    assert "queued" not in scenarios_mod.RUN_SUCCEEDED_STATES
    backend = fake.FakeBackend(grants=frozenset(CAPABILITIES))
    from acp_acceptance.context import ScenarioContext
    ctx = ScenarioContext(target=run_mod.SELF_TEST_TARGET, backend=backend,
                          artifacts=ArtifactSink())
    sid, _ = scenarios_mod._start_scan(ctx)
    first = json.loads(backend.http("GET", f"/scans/{sid}/live").body)
    assert first["state"] == "queued" and first["active"] is False, first
    snap, failure = scenarios_mod._await_scan(ctx, sid)
    assert failure is None, "a run seen in `queued` was not polled to its terminal state"


def test_an_unknown_from_the_restart_scenario_never_becomes_a_failure_about_the_target():
    """THE WORST OF THE THREE. The first real run reported "work did not complete after the tier
    restarted" for all three tiers, on a cluster where all three had completed — because
    `_await_scan` came back `unknown` over a state the suite did not model, and the scenario
    folded that straight into a lost-work finding."""
    world = fake.world(faults={"GET /scans/{sid}/live": {"status": 404}})
    run, _ = run_fake(world=world, scenario_ids=["worker-restart"])
    entry = entry_for(run.report, "worker-restart")
    assert entry["state"] == UNKNOWN, (
        f"an unreadable run state was reported as {entry['state']}: {entry['detail']}")


def test_the_fixture_workflow_sends_no_body_to_assess_or_remediate():
    """`assess` declares only query parameters, so a JSON body is silently ignored — it read as a
    scope being honoured and never was. `remediate`'s optional body takes a LIST of filenames, and
    the old `{"scope": "all"}` was a string where a list belongs; omitting it is what its own
    docstring says remediates everything."""
    run, backend = run_fake(scenario_ids=["fixture-workflow"])
    posts = [e for e in backend.log if e["kind"] == "http" and e["method"] == "POST"
             and ("/assess" in e["path"] or "/remediate" in e["path"])]
    assert posts, "the scenario never reached assess or remediate"
    bodies = [json.loads(r.body) for r in [backend.http("POST", p["path"], body={"scope": "all"})
                                           for p in posts]]
    assert all(b.get("detail") for b in bodies), (
        "the fake accepted a `{'scope': 'all'}` body on assess/remediate; the application either "
        "ignores it or would iterate the string character by character")


def test_a_persistent_503_is_unknown_rather_than_a_defect_in_the_target():
    """`app.py`'s capacity guard answers 503 with `Retry-After` and `changes: "unknown"` — the
    application saying it could not determine whether the request took effect. Calling that a
    target FAILURE says "this installation cannot assess documents" about one that was busy."""
    world = fake.world(faults={"POST /scans/{sid}/assess": {
        "status": 503, "json": {"detail": "database_busy", "code": "DB_CAPACITY_BUSY",
                                "changes": "unknown"}}})
    run, _ = run_fake(world=world, scenario_ids=["fixture-workflow"])
    entry = entry_for(run.report, "fixture-workflow")
    assert entry["state"] == UNKNOWN, f"a 503 was reported as {entry['state']}: {entry['detail']}"
    assert "DB_CAPACITY_BUSY" in entry["detail"], (
        "the outcome does not name WHICH 503 it was. A status code alone is not a diagnosis, and "
        f"the next reference-cluster run is fifteen minutes away: {entry['detail']}")


def test_a_503_is_retried_before_it_is_believed():
    world = fake.world(faults={"POST /scans/{sid}/assess": {"status": 503, "json": {}}})
    run, backend = run_fake(world=world, scenario_ids=["fixture-workflow"])
    attempts = [e for e in backend.log
                if e["kind"] == "http" and e["method"] == "POST" and "/assess" in e["path"]]
    assert len(attempts) > 1, (
        f"the suite believed a single 503 without retrying; the application asks for a retry with "
        f"Retry-After ({len(attempts)} attempt)")


def test_a_500_is_still_a_failure_and_not_swallowed_as_busy():
    """The 503 rule must not become "any error is inconclusive". A 500 is the target answering
    definitively, and a suite that treats those as unknown cannot fail at all."""
    world = fake.world(faults={"POST /scans/{sid}/assess": {"status": 500, "json": {}}})
    run, _ = run_fake(world=world, scenario_ids=["fixture-workflow"])
    assert state_of(run.report, "fixture-workflow") == FAIL


def test_only_a_503_is_retried_and_a_500_is_attempted_once():
    """Retry is scoped to the one status the application asks us to retry. Retrying a 500 turns
    one defect into four identical entries in the log and delays the report by three sleeps; the
    claim was untested until a bite check failed to bite."""
    world = fake.world(faults={"POST /scans/{sid}/assess": {"status": 500, "json": {}}})
    run, backend = run_fake(world=world, scenario_ids=["fixture-workflow"])
    attempts = [e for e in backend.log
                if e["kind"] == "http" and e["method"] == "POST" and "/assess" in e["path"]]
    assert len(attempts) == 1, (
        f"a 500 was retried {len(attempts)} times; only 503 carries the application's "
        f"Retry-After contract")


def test_a_failed_request_names_what_the_target_said():
    world = fake.world(faults={"POST /scans/{sid}/assess": {
        "status": 500, "json": {"detail": "boom", "code": "WIDGET_EXPLODED"}}})
    run, _ = run_fake(world=world, scenario_ids=["fixture-workflow"])
    detail = entry_for(run.report, "fixture-workflow")["detail"]
    assert "WIDGET_EXPLODED" in detail, detail
