"""Frozen batch selections must not approve replacement proposal/source versions."""
import pytest
from test_hitl_decision_atomicity import decision  # real isolated SQLite route fixture


def expectations(st, item_id):
    row = st.get_hitl_item(item_id)
    return dict(status="approved", approved_values=[p["proposed_value"] for p in row["proposals"]],
                request_id="frozen-batch-1", expected_version=row.get("decision_version") or 0,
                expected_proposal_snapshot_ids=row["proposal_snapshot_ids"],
                expected_source_revision=st.stage_snapshot_id(row["scan_id"]))


@pytest.mark.parametrize("change", ["snapshot", "source", "value", "missing_slot"])
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
        elif change == "value":
            row = st.get_hitl_item(item_id)
            row["proposals"][0]["proposed_value"] = "replacement without a new snapshot"
            st._db.execute(cur, "UPDATE hitl_queue SET proposals=%s WHERE id=%s", (json.dumps(row["proposals"]), item_id))
        else:
            before["expected_proposal_snapshot_ids"] = []
    with pytest.raises(Exception) as exc:
        update(item_id, Body(**before), request)
    assert getattr(exc.value, "status_code", None) == 409
    assert st.get_hitl_item(item_id)["status"] == "pending"
    assert st.list_decisions("s1") == []
    assert st.list_jobs() == []


def test_exact_guarded_replay_does_not_duplicate_jobs_or_audit(decision):
    st, item_id, update, Body, request = decision
    body = Body(**expectations(st, item_id))
    first = update(item_id, body, request)
    assert update(item_id, body, request) == first
    assert len(st.list_decisions("s1")) == 1
    assert len(st.list_jobs()) == 1


def test_same_request_id_cannot_be_reused_with_different_snapshot_expectation(decision):
    st, item_id, update, Body, request = decision
    expected = expectations(st, item_id)
    update(item_id, Body(**expected), request)
    expected["expected_proposal_snapshot_ids"] = ["different"]
    with pytest.raises(Exception) as exc:
        update(item_id, Body(**expected), request)
    assert getattr(exc.value, "status_code", None) == 409
    assert len(st.list_decisions("s1")) == 1
