from __future__ import annotations

import pytest

from finding_ledger import stable_finding_id
from store import FindingEventConflict, FindingRevisionConflict


def _assessment(store, sid: str = "scan-ledger") -> str:
    with store._db.cursor() as cur:
        store._db.execute(cur,
            "INSERT INTO scan_runs(id,source,status,workflow_id,workflow_revision) "
            "VALUES(%s,'sharepoint','done',%s,1)", (sid, f"workflow-{sid}"))
        store._db.execute(cur,
            "INSERT INTO file_records(scan_id,file,drive_file_id,checksum) "
            "VALUES(%s,'a.docx','drive-item-1','content-one')", (sid,))
        store._db.execute(cur,
            "INSERT INTO scan_rule_traces(scan_id,file,rule_id,rule_name,plain_name,level,"
            "fix_mode,outcome,finding_count) VALUES(%s,'a.docx','1.1.1','Non-text Content',"
            "'Images need text','A','human','FAIL',3)", (sid,))
        store._db.execute(cur,
            "INSERT INTO scan_rule_traces(scan_id,file,rule_id,rule_name,plain_name,level,"
            "fix_mode,outcome,finding_count) VALUES(%s,'a.docx','2.4.4','Link Purpose',"
            "'Links need purpose','A','human','FAIL',2)", (sid,))
    return sid


def _batch(store, sid: str, batch: str = "batch-1") -> str:
    execution = store.enqueue_stage_batch(
        sid, "remediate", "remediate_file", [{"scan_id": sid, "file": "a.docx"}],
        snapshot_id=sid, request_fingerprint=f"request-{batch}")
    return execution["batch_id"]


def test_seed_creates_one_stable_finding_per_assessed_instance(isolated_store):
    sid = _assessment(isolated_store)
    first = isolated_store.seed_finding_dispositions(sid, "batch-1", snapshot_id="snapshot-1")
    second = isolated_store.seed_finding_dispositions(sid, "batch-1", snapshot_id="snapshot-1")
    assert len(first) == len(second) == 5
    assert [row["finding_id"] for row in first] == [row["finding_id"] for row in second]
    assert len({row["finding_id"] for row in first}) == 5
    assert all(row["document_id"] == "sharepoint:drive-item-1" for row in first)
    assert all(row["snapshot_id"] == "snapshot-1" for row in first)
    assert all(row["disposition"] is None and row["revision"] == 0 for row in first)


def test_finding_identity_does_not_depend_on_filename():
    assert stable_finding_id("sharepoint:item-7", "1.1.1", "image:rId4") == stable_finding_id(
        "sharepoint:item-7", "1.1.1", "image:rId4")
    assert stable_finding_id("sharepoint:item-7", "1.1.1", "image:rId4") != stable_finding_id(
        "sharepoint:item-8", "1.1.1", "image:rId4")


def test_transition_is_revision_protected_and_duplicate_events_are_noops(isolated_store):
    sid = _assessment(isolated_store)
    finding = isolated_store.seed_finding_dispositions(sid, "batch-1")[0]
    changed = isolated_store.transition_finding_disposition(
        sid, "batch-1", finding["finding_id"], "awaiting_review", expected_revision=0,
        event_id="review-event-1", review_item_id="review-1")
    assert changed["revision"] == 1
    assert changed["disposition"] == "awaiting_review"
    replay = isolated_store.transition_finding_disposition(
        sid, "batch-1", finding["finding_id"], "awaiting_review", expected_revision=0,
        event_id="review-event-1", review_item_id="review-1")
    assert replay["revision"] == 1
    with pytest.raises(FindingRevisionConflict):
        isolated_store.transition_finding_disposition(
            sid, "batch-1", finding["finding_id"], "resolved_verified", expected_revision=0,
            event_id="verify-event-stale")
    with pytest.raises(FindingEventConflict):
        isolated_store.transition_finding_disposition(
            sid, "batch-1", finding["finding_id"], "resolved_verified", expected_revision=1,
            event_id="review-event-1")


def test_exact_reconciliation_requires_one_disposition_per_finding(isolated_store):
    sid = _assessment(isolated_store)
    findings = isolated_store.seed_finding_dispositions(sid, "batch-1")
    initial = isolated_store.finding_reconciliation(sid, "batch-1")
    assert initial["assessed"] == 5
    assert initial["accounted"] == 0
    assert initial["unaccounted"] == 5
    assert initial["exact"] is False
    for index, finding in enumerate(findings):
        disposition = "resolved_verified" if index < 3 else "awaiting_review"
        isolated_store.transition_finding_disposition(
            sid, "batch-1", finding["finding_id"], disposition, expected_revision=0,
            event_id=f"event-{index}")
    final = isolated_store.finding_reconciliation(sid, "batch-1")
    assert final["resolved_verified"] == 3
    assert final["awaiting_review"] == 2
    assert final["accounted"] == final["assessed"] == 5
    assert final["unaccounted"] == 0
    assert final["exact"] is True


def test_historical_batches_never_contribute_to_current_totals(isolated_store):
    sid = _assessment(isolated_store)
    old = isolated_store.seed_finding_dispositions(sid, "batch-old")
    for index, finding in enumerate(old):
        isolated_store.transition_finding_disposition(
            sid, "batch-old", finding["finding_id"], "resolved_verified", expected_revision=0,
            event_id=f"old-{index}")
    isolated_store.seed_finding_dispositions(sid, "batch-current")
    current = isolated_store.finding_reconciliation(sid, "batch-current")
    assert current["resolved_verified"] == 0
    assert current["unaccounted"] == 5
    assert current["exact"] is False


def test_verified_diff_resolves_all_instances_and_attaches_evidence(isolated_store):
    sid = _assessment(isolated_store)
    batch = _batch(isolated_store, sid)
    isolated_store.seed_finding_dispositions(sid, batch)
    isolated_store.record_remediation_diffs(
        sid, "a.docx", [{"rule_id": "1.1.1", "before": "missing", "after": "text"}])
    rows = [r for r in isolated_store.list_finding_dispositions(sid, batch)
            if r["rule_id"] == "1.1.1"]
    assert len(rows) == 3
    assert {r["disposition"] for r in rows} == {"resolved_verified"}
    assert all(r["verified_at"] and r["fix_evidence_ids"] for r in rows)
    isolated_store.record_remediation_diffs(
        sid, "a.docx", [{"rule_id": "1.1.1", "before": "missing", "after": "text"}])
    assert {r["revision"] for r in isolated_store.list_finding_dispositions(sid, batch)
            if r["rule_id"] == "1.1.1"} == {1}


def test_review_card_transitions_exact_finding_count_without_double_counting(isolated_store):
    sid = _assessment(isolated_store)
    batch = _batch(isolated_store, sid)
    isolated_store.seed_finding_dispositions(sid, batch)
    items = isolated_store.queue_hitl_review_for_file(
        sid, "a.docx", [{"rule_id": "2.4.4", "rule_name": "Link Purpose",
                          "finding_count": 2}])
    item_id = items[0]["id"]
    assert isolated_store.finding_reconciliation(sid, batch)["awaiting_review"] == 2
    isolated_store.update_hitl_item(item_id, "approved")
    isolated_store.sync_hitl_finding_dispositions(item_id, "approved")
    summary = isolated_store.finding_reconciliation(sid, batch)
    assert summary["awaiting_review"] == 0
    assert summary["approved_pending_verification"] == 2
