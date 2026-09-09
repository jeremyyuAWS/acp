"""Frozen batch selections must not approve replacement proposal/source versions."""
import pytest
from test_hitl_decision_atomicity import decision as base_decision

@pytest.fixture()
def decision(base_decision):
    from ai_run_policy import run_context
    st, item_id, update, Body, request = base_decision
    with st._db.cursor() as cur:
        st._db.execute(cur, "UPDATE scan_runs SET owner_email=%s WHERE id=%s", ("reviewer@example.com", "s1"))
    result = st.enqueue_stage_batch("s1", "remediate", "remediate_file", [{
        "owner": "reviewer@example.com", "scan_id": "s1", "file": "deck.pptx",
        "remediation_impact_policy": {"ai": 1, "rule_based": 2, "ai_budget_usd": "0.10", "snapshot_id": "fixture"},
    }], snapshot_id=st.stage_snapshot_id("s1"), request_fingerprint="fixture")
    job = st.get_job(result["job_ids"][0])
    with run_context(st, job["payload"], job):
        st.enqueue_proposals("s1", "deck.pptx", "1.1.1", st.get_hitl_item(item_id)["proposals"])
    return base_decision


def expectations(st, item_id):
    row = st.get_hitl_item(item_id)
    return dict(status="approved", approved_values=[p["proposed_value"] for p in row["proposals"]],
                request_id="frozen-batch-1", expected_version=row.get("decision_version") or 0,
                expected_proposal_snapshot_ids=row["proposal_snapshot_ids"],
                expected_source_revision=st.stage_snapshot_id(row["scan_id"]))


@pytest.mark.parametrize("change", ["snapshot", "source", "value", "locator", "missing_slot"])
def test_replacement_between_preview_and_decision_has_no_writes(decision, change):
    import json
    st, item_id, update, Body, request = decision
    before = expectations(st, item_id)
    with st._db.cursor() as cur:
        if change == "snapshot":
            st._db.execute(cur, "UPDATE hitl_queue SET proposal_snapshot_ids=%s WHERE id=%s",
                           (json.dumps(["replacement"]), item_id))
        elif change == "source":
            st._db.execute(cur, "UPDATE scan_runs SET rubric_hash=%s WHERE id=%s", ("reassessed", "s1"))
        elif change in {"value", "locator"}:
            row = st.get_hitl_item(item_id)
            row["proposals"][0]["proposed_value" if change == "value" else "locator"] = "replacement without a new snapshot"
            st._db.execute(cur, "UPDATE hitl_queue SET proposals=%s WHERE id=%s", (json.dumps(row["proposals"]), item_id))
        else:
            before["expected_proposal_snapshot_ids"] = []
    with pytest.raises(Exception) as exc:
        update(item_id, Body(**before), request)
    assert getattr(exc.value, "status_code", None) == 409
    assert st.get_hitl_item(item_id)["status"] == "pending"
    assert st.list_decisions("s1") == []
    assert all(j["type"] != "apply_approved_values" for j in st.list_jobs())


def test_exact_guarded_replay_does_not_duplicate_jobs_or_audit(decision):
    st, item_id, update, Body, request = decision
    body = Body(**expectations(st, item_id))
    first = update(item_id, body, request)
    assert update(item_id, body, request) == first
    assert len(st.list_decisions("s1")) == 1
    assert len([j for j in st.list_jobs() if j["type"] == "apply_approved_values"]) == 1


def test_same_request_id_cannot_be_reused_with_different_snapshot_expectation(decision):
    st, item_id, update, Body, request = decision
    expected = expectations(st, item_id)
    update(item_id, Body(**expected), request)
    expected["expected_proposal_snapshot_ids"] = ["different"]
    with pytest.raises(Exception) as exc:
        update(item_id, Body(**expected), request)
    assert getattr(exc.value, "status_code", None) == 409
    assert len(st.list_decisions("s1")) == 1


def test_frozen_batch_cannot_cross_owner_boundary(decision):
    from test_hitl_owner_isolation import _client
    st, item_id, update, Body, request = decision
    response = _client("somebody-else@example.com").put(f"/hitl/queue/{item_id}", json=expectations(st, item_id))
    assert response.status_code == 404
    assert st.get_hitl_item(item_id)["status"] == "pending"
    assert st.list_decisions("s1") == []


def test_another_scan_source_identity_is_rejected(decision):
    st, item_id, update, Body, request = decision
    expected = expectations(st, item_id)
    st.init_scan_run("other-scan", "drive", 1, "t0", "rubric", "hash")
    expected["expected_source_revision"] = st.stage_snapshot_id("other-scan")
    with pytest.raises(Exception) as exc:
        update(item_id, Body(**expected), request)
    assert getattr(exc.value, "status_code", None) == 409
    assert st.list_decisions("s1") == []


def test_queue_list_exposes_source_identity_without_mutating(decision):
    from test_hitl_owner_isolation import _client
    st, item_id, update, Body, request = decision
    rows = _client("reviewer@example.com").get("/hitl/queue").json()
    row = next(r for r in rows if r["id"] == item_id)
    assert row["source_revision"] == st.stage_snapshot_id("s1")
    assert row["proposal_snapshot_ids"] == st.get_hitl_item(item_id)["proposal_snapshot_ids"]
    assert st.list_decisions("s1") == []
