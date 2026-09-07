import json
import importlib.util
import concurrent.futures
from pathlib import Path
import pytest

from fastapi.testclient import TestClient

from remediation_automation_policy import REASON_ORDER, build_policy_preview
import remediation_automation_policy as policy
from fastapi import FastAPI


FIXTURE = Path(__file__).parent / "fixtures/remediation_automation_policy_preview.json"
OWNER = "operator@example.com"


@pytest.fixture
def client(monkeypatch, isolated_store):
    import core
    monkeypatch.setattr(core, "store", isolated_store)
    isolated_store.init_scan_run("scan-http", "local", 0, "t0", "r", "h", owner="demo")
    from app import app
    return TestClient(app)


def _router():
    path = Path(__file__).parents[1] / "api/routes/remediation_policy.py"
    spec = importlib.util.spec_from_file_location("remediation_policy_route", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.router


def _fixture():
    return json.loads(FIXTURE.read_text())


def test_contract_has_exact_counts_exclusive_reasons_and_honest_unknown():
    result = build_policy_preview(_fixture()["findings"], level=3)
    assert result["open"] == {"findings": 8, "files": 7}
    assert result["lanes"] == {
        "automatic": {"findings": 1, "files": 1},
        "review": {"findings": 3, "files": 3},
        "protected": {"findings": 4, "files": 4},
    }
    assert [item["reason"] for item in result["reasons"]] == list(REASON_ORDER)
    assert sum(item["findings"] for item in result["reasons"]) == 6
    assert result["findings"][-1]["primary_reason"] is None
    assert result["integrity"] == {
        "open_equals_lane_sum": True,
        "reason_is_mutually_exclusive": True,
        "unknown_primary_reason": {"findings": 1, "files": 1},
        "complete": False,
    }


def test_reason_drilldown_counts_distinct_files_by_criterion_and_format():
    rows = [
        {"file": "one.docx", "criterion": "1.1.1", "lane": "review", "primary_reason": "missing_evidence"},
        {"file": "one.docx", "criterion": "1.1.1", "lane": "review", "primary_reason": "missing_evidence"},
        {"file": "two.pdf", "criterion": "1.1.1", "lane": "review", "primary_reason": "missing_evidence"},
    ]
    reason = build_policy_preview(rows)["reasons"][0]
    assert reason["findings"] == 3 and reason["files"] == 2
    assert reason["criteria"] == [{"criterion": "1.1.1", "findings": 3, "files": 2}]
    assert reason["formats"] == [
        {"format": "docx", "findings": 2, "files": 1},
        {"format": "pdf", "findings": 1, "files": 1},
    ]


def test_preview_route_returns_the_versioned_contract():
    app = FastAPI()
    app.include_router(_router())
    response = TestClient(app).post("/remediation/automation-policy/preview", json=_fixture())
    assert response.status_code == 200
    assert response.json()["contract_version"] == "remediation-automation-policy-preview.v1"


def test_save_is_versioned_audited_and_duplicate_is_one_effect(isolated_store):
    first = policy.execute(isolated_store, OWNER, OWNER, action="save_future", level=4,
                           expected_revision=0, idempotency_key="same-stable-key-0001")
    duplicate = policy.execute(isolated_store, OWNER, OWNER, action="save_future", level=4,
                               expected_revision=0, idempotency_key="same-stable-key-0001")
    assert first["policy"]["revision"] == 1 and duplicate["duplicate"] is True
    assert policy.read(isolated_store, OWNER)["policy"]["level"] == 4
    assert len([r for r in isolated_store.list_decisions()
                if r["action"] == "remediation.policy.saved"]) == 1


def test_stale_revision_changes_nothing(isolated_store):
    policy.execute(isolated_store, OWNER, OWNER, action="save_future", level=2,
                   expected_revision=0, idempotency_key="first-stable-key-01")
    with pytest.raises(policy.PolicyConflict):
        policy.execute(isolated_store, OWNER, OWNER, action="save_future", level=5,
                       expected_revision=0, idempotency_key="second-stable-key-1")
    assert policy.read(isolated_store, OWNER)["policy"]["level"] == 2


def test_audit_failure_rolls_back_policy_and_receipt(isolated_store, monkeypatch):
    original = isolated_store._db.execute
    def fail_audit(cur, sql, params=()):
        if "INSERT INTO decision_log" in sql:
            raise RuntimeError("audit unavailable")
        return original(cur, sql, params)
    monkeypatch.setattr(isolated_store._db, "execute", fail_audit)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        policy.execute(isolated_store, OWNER, OWNER, action="save_future", level=4,
                       expected_revision=0, idempotency_key="rollback-key-000001")
    monkeypatch.setattr(isolated_store._db, "execute", original)
    assert policy.read(isolated_store, OWNER)["policy"]["revision"] == 0


def test_concurrent_retries_produce_one_effect(isolated_store):
    def submit(_):
        return policy.execute(isolated_store, OWNER, OWNER, action="save_future", level=5,
                              expected_revision=0, idempotency_key="concurrent-key-0001")
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, range(2)))
    assert sorted(r["duplicate"] for r in results) == [False, True]
    assert policy.read(isolated_store, OWNER)["policy"]["revision"] == 1


def test_active_run_action_is_hidden_and_refused_until_routing_is_safe(isolated_store):
    assert policy.read(isolated_store, OWNER)["capabilities"]["apply_waiting"] is False
    with pytest.raises(policy.ActiveRunUnsupported):
        policy.execute(isolated_store, OWNER, OWNER, action="apply_waiting", level=4,
                       expected_revision=0, idempotency_key="active-stable-key-01")
    assert policy.read(isolated_store, OWNER)["policy"]["revision"] == 0


def test_future_run_snapshot_is_immutable_after_saved_policy_changes(isolated_store):
    snap = policy.snapshot_for_future_run(isolated_store, OWNER)
    policy.bind_run_snapshot(isolated_store, OWNER, OWNER, "scan-1", "batch-1", snap)
    policy.execute(isolated_store, OWNER, OWNER, action="save_future", level=5,
                   expected_revision=0, idempotency_key="later-policy-key-001")
    policy.bind_run_snapshot(isolated_store, OWNER, OWNER, "scan-1", "batch-1",
                             policy.snapshot_for_future_run(isolated_store, OWNER))
    bound = policy.read(isolated_store, OWNER, scan_id="scan-1")["run_policy_snapshot"]
    assert bound["level"] == 3 and bound["policy_revision"] == 0


def test_policy_action_route_requires_operate_role():
    import workspace_capability_map as capmap
    assert capmap.required_capabilities(
        "POST", "/scans/{sid}/remediation/automation-policy/actions") == {"remediate.run"}


def test_stale_route_returns_machine_conflict_and_current_policy(client):
    headers = {"Idempotency-Key": "route-first-key-0001"}
    assert client.post("/scans/scan-http/remediation/automation-policy/actions", headers=headers,
                       json={"action": "save_future", "level": 2,
                             "expected_revision": 0}).status_code == 200
    response = client.post("/scans/scan-http/remediation/automation-policy/actions",
                           headers={"Idempotency-Key": "route-stale-key-001"},
                           json={"action": "save_future", "level": 5,
                                 "expected_revision": 0})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "stale_policy_revision"
    assert response.json()["detail"]["current"]["level"] == 2
