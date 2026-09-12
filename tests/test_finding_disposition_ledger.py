from __future__ import annotations

import pytest

from finding_ledger import normalize_instance_key, reconcile, stable_finding_id
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


def test_seed_replay_is_frozen_and_rejects_snapshot_reuse(isolated_store):
    sid = _assessment(isolated_store)
    first = isolated_store.seed_finding_dispositions(sid, "batch-1", snapshot_id="snapshot-1")
    with isolated_store._db.cursor() as cur:
        isolated_store._db.execute(cur,
            "UPDATE scan_rule_traces SET finding_count=99 WHERE scan_id=%s", (sid,))
    replay = isolated_store.seed_finding_dispositions(
        sid, "batch-1", snapshot_id="snapshot-1")
    assert [row["finding_id"] for row in replay] == [row["finding_id"] for row in first]
    assert len(replay) == 5
    with pytest.raises(ValueError, match="different snapshot"):
        isolated_store.seed_finding_dispositions(sid, "batch-1", snapshot_id="snapshot-2")


def test_aggregate_identity_is_snapshot_scoped_and_sorts_numerically():
    keys = [normalize_instance_key(None, ordinal=n, aggregate_scope="snapshot-1")
            for n in (1, 2, 10)]
    assert keys == sorted(keys)
    assert normalize_instance_key(None, ordinal=1, aggregate_scope="snapshot-1") != \
        normalize_instance_key(None, ordinal=1, aggregate_scope="snapshot-2")


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
    with pytest.raises(FindingEventConflict):
        isolated_store.transition_finding_disposition(
            sid, "batch-1", finding["finding_id"], "awaiting_review", expected_revision=0,
            event_id="review-event-1", review_item_id="different-review")


def test_failed_cas_rolls_back_event_append(isolated_store):
    sid = _assessment(isolated_store)
    finding = isolated_store.seed_finding_dispositions(sid, "batch-1")[0]
    isolated_store.transition_finding_disposition(
        sid, "batch-1", finding["finding_id"], "awaiting_review", expected_revision=0,
        event_id="winner")
    with pytest.raises(FindingRevisionConflict):
        isolated_store.transition_finding_disposition(
            sid, "batch-1", finding["finding_id"], "unchanged_no_fix", expected_revision=0,
            event_id="loser")
    with isolated_store._db.cursor() as cur:
        isolated_store._db.execute(cur,
            "SELECT COUNT(*) AS n FROM finding_disposition_event WHERE event_id='loser'")
        assert isolated_store._db.fetchone(cur)["n"] == 0


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


def test_group_updates_use_canonical_current_execution_not_newest_historical_job(isolated_store):
    sid = _assessment(isolated_store)
    current = _batch(isolated_store, sid, "current")
    isolated_store.seed_finding_dispositions(sid, current)
    old = isolated_store.seed_finding_dispositions(sid, "historical")
    with isolated_store._db.cursor() as cur:
        isolated_store._db.execute(cur,
            "INSERT INTO jobs(id,type,status,batch_id,scan_id,created_at,updated_at) "
            "VALUES('z-historical','remediate_file','done','historical',%s,'9999','9999')", (sid,))
    isolated_store.set_finding_group_disposition(
        sid, "a.docx", "1.1.1", "awaiting_review", event_key="review-current")
    assert {r["disposition"] for r in isolated_store.list_finding_dispositions(sid, current)
            if r["rule_id"] == "1.1.1"} == {"awaiting_review"}
    assert all(r["disposition"] is None for r in old)


def test_reconciliation_reports_overcount_and_invalid_partition():
    result = reconcile(2, {"resolved_verified": 2}, rows=3)
    assert result["exact"] is False
    assert {v["code"] for v in result["violations"]} == {
        "ledger_cardinality", "finding_overcount", "disposition_partition"}

    invalid = reconcile(1, {"resolved_verified": -1}, rows=1)
    assert "invalid_finding_counts" in {v["code"] for v in invalid["violations"]}


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


def test_group_action_can_legitimately_return_after_an_intervening_transition(isolated_store):
    """A Remediate replay may route the same card back to review after an approval.

    The producer key is intentionally stable across runs. It must not be mistaken for the full
    immutable event identity, or the second routing collides with the first and its proposals
    or proposals are discarded by the caller.
    """
    sid = _assessment(isolated_store)
    batch = _batch(isolated_store, sid)
    isolated_store.seed_finding_dispositions(sid, batch)

    isolated_store.set_finding_group_disposition(
        sid, "a.docx", "1.1.1", "awaiting_review", event_key="hitl:review-1:pending",
        review_item_id="review-1")
    moved = isolated_store.set_finding_group_disposition(
        sid, "a.docx", "1.1.1", "approved_pending_verification",
        event_key="hitl:review-1:approved", review_item_id="review-1")
    assert moved == 3
    moved = isolated_store.set_finding_group_disposition(
        sid, "a.docx", "1.1.1", "awaiting_review", event_key="hitl:review-1:pending",
        review_item_id="review-1")

    assert moved == 3
    rows = [r for r in isolated_store.list_finding_dispositions(sid, batch)
            if r["rule_id"] == "1.1.1"]
    assert {r["disposition"] for r in rows} == {"awaiting_review"}
    assert {r["revision"] for r in rows} == {3}
    for row in rows:
        events = isolated_store.finding_disposition_events(sid, batch, row["finding_id"])
        assert [event["to_disposition"] for event in events] == [
            "awaiting_review", "approved_pending_verification", "awaiting_review"]
        assert len({event["event_id"] for event in events}) == 3


def test_mixed_rule_diff_evidence_uses_per_rule_ordinals(isolated_store):
    sid = _assessment(isolated_store)
    batch = _batch(isolated_store, sid)
    isolated_store.seed_finding_dispositions(sid, batch)
    isolated_store.record_remediation_diffs(sid, "a.docx", [
        {"rule_id": "1.1.1", "before": "a", "after": "A"},
        {"rule_id": "2.4.4", "before": "b", "after": "B"},
        {"rule_id": "1.1.1", "before": "c", "after": "C"},
    ])
    by_rule = {r["rule_id"]: r for r in isolated_store.list_finding_dispositions(sid, batch)}
    assert by_rule["1.1.1"]["fix_evidence_ids"] == [
        "remediation_diff:a.docx:1.1.1:0", "remediation_diff:a.docx:1.1.1:1"]
    assert by_rule["2.4.4"]["fix_evidence_ids"] == ["remediation_diff:a.docx:2.4.4:0"]


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


def test_reused_review_card_reconciles_new_batch_and_count_growth(isolated_store):
    sid = _assessment(isolated_store)
    item = isolated_store.queue_hitl_review_for_file(sid, 'a.docx', [
        {'rule_id': '2.4.4', 'finding_count': 1}])[0]
    batch = _batch(isolated_store, sid)
    isolated_store.seed_finding_dispositions(sid, batch)
    assert isolated_store.queue_hitl_review_for_file(sid, 'a.docx', [
        {'rule_id': '2.4.4', 'finding_count': 2}]) == []
    rows = [r for r in isolated_store.list_finding_dispositions(sid, batch)
            if r['rule_id'] == '2.4.4']
    assert len(rows) == 2
    assert {r['disposition'] for r in rows} == {'awaiting_review'}
    assert {r['review_item_id'] for r in rows} == {item['id']}


@pytest.mark.parametrize('status,expected', [('approved', 'approved_pending_verification'),
                                            ('rejected', 'unchanged_no_fix')])
def test_reused_review_card_keeps_decision_and_verified_rows(isolated_store, status, expected):
    sid = _assessment(isolated_store)
    item = isolated_store.queue_hitl_review_for_file(sid, 'a.docx', [
        {'rule_id': '1.1.1', 'finding_count': 3}])[0]
    isolated_store.update_hitl_item(item['id'], status)
    batch = _batch(isolated_store, sid)
    rows = isolated_store.seed_finding_dispositions(sid, batch)
    first = next(r for r in rows if r['rule_id'] == '1.1.1')
    isolated_store.transition_finding_disposition(sid, batch, first['finding_id'],
        'resolved_verified', expected_revision=0, event_id='verified-one',
        fix_evidence_ids=['real-write'], verified_at='2026-09-12T15:00:00Z')
    isolated_store.queue_hitl_review_for_file(sid, 'a.docx', [
        {'rule_id': '1.1.1', 'finding_count': 3}])
    rows = [r for r in isolated_store.list_finding_dispositions(sid, batch) if r['rule_id'] == '1.1.1']
    assert sorted(r['disposition'] for r in rows) == sorted(['resolved_verified', expected, expected])
    assert isolated_store.get_hitl_item(item['id'])['status'] == status


def test_authorized_queue_reconciliation_repairs_completed_run_without_more_jobs(isolated_store, monkeypatch):
    from routes import hitl
    import core
    sid = _assessment(isolated_store)
    monkeypatch.setattr(core, 'store', isolated_store)
    monkeypatch.setattr(core, 'fire_webhook', lambda rows: None)
    with isolated_store._db.cursor() as cur:
        isolated_store._db.execute(cur, "UPDATE scan_rule_traces SET outcome='REVIEW',fix_mode='human' "
                                  "WHERE scan_id=%s AND rule_id='1.1.1'", (sid,))
    isolated_store.queue_hitl_review_for_file(sid, 'a.docx', [{'rule_id': '2.4.4', 'finding_count': 1}])
    batch = _batch(isolated_store, sid)
    isolated_store.seed_finding_dispositions(sid, batch)
    assert isolated_store.reconcile_completed_remediation_reviews(sid) == []
    with isolated_store._db.cursor() as cur:
        isolated_store._db.execute(cur, "UPDATE jobs SET status='done' WHERE batch_id=%s", (batch,))
        isolated_store._db.execute(cur, "UPDATE stage_executions SET state='succeeded' WHERE execution_id=%s", (batch,))
        isolated_store._db.execute(cur, 'SELECT COUNT(*) AS n FROM jobs WHERE scan_id=%s', (sid,))
        job_count = isolated_store._db.fetchone(cur)['n']
    result = hitl.hitl_auto_queue(sid, None)
    assert result['queued'] == 1
    summary = isolated_store.finding_reconciliation(sid, batch)
    assert summary['exact'] and summary['awaiting_review'] == 5 and summary['resolved_verified'] == 0
    assert hitl.hitl_auto_queue(sid, None)['queued'] == 0
    with isolated_store._db.cursor() as cur:
        isolated_store._db.execute(cur, 'SELECT COUNT(*) AS n FROM jobs WHERE scan_id=%s', (sid,))
        assert isolated_store._db.fetchone(cur)['n'] == job_count


def test_ai_queue_reuse_projects_actual_status_into_new_ledger(isolated_store):
    sid = _assessment(isolated_store)
    with isolated_store._db.cursor() as cur:
        isolated_store._db.execute(cur, "UPDATE scan_rule_traces SET fix_mode='ai-assisted' WHERE scan_id=%s", (sid,))
    items = isolated_store.queue_hitl_items(sid)
    for item in items:
        isolated_store.update_hitl_item(item['id'], 'rejected')
    batch = _batch(isolated_store, sid)
    isolated_store.seed_finding_dispositions(sid, batch)
    assert isolated_store.queue_hitl_items(sid) == []
    summary = isolated_store.finding_reconciliation(sid, batch)
    assert summary['exact'] and summary['unchanged_no_fix'] == 5


def test_completed_30_finding_run_repairs_11_missing_without_changing_13_verified(isolated_store):
    sid = _assessment(isolated_store)
    with isolated_store._db.cursor() as cur:
        isolated_store._db.execute(cur, "UPDATE scan_rule_traces SET finding_count=CASE rule_id "
                                  "WHEN '1.1.1' THEN 13 ELSE 17 END WHERE scan_id=%s", (sid,))
    batch = _batch(isolated_store, sid)
    isolated_store.seed_finding_dispositions(sid, batch)
    isolated_store.record_remediation_diffs(sid, 'a.docx', [
        {'rule_id': '1.1.1', 'before': 'missing', 'after': 'verified description'}])
    isolated_store.queue_hitl_review_for_file(sid, 'a.docx', [{'rule_id': '2.4.4', 'finding_count': 6}])
    before = isolated_store.finding_reconciliation(sid, batch)
    assert (before['assessed'], before['resolved_verified'], before['awaiting_review'], before['unaccounted']) == (30, 13, 6, 11)
    with isolated_store._db.cursor() as cur:
        isolated_store._db.execute(cur, "UPDATE jobs SET status='done' WHERE batch_id=%s", (batch,))
        isolated_store._db.execute(cur, "UPDATE stage_executions SET state='succeeded' WHERE execution_id=%s", (batch,))
    assert isolated_store.reconcile_completed_remediation_reviews(sid) == []
    after = isolated_store.finding_reconciliation(sid, batch)
    assert after['exact']
    assert (after['resolved_verified'], after['awaiting_review'], after['unaccounted']) == (13, 17, 0)


def test_completed_repair_cannot_mutate_a_concurrently_started_batch(isolated_store, monkeypatch):
    sid = _assessment(isolated_store)
    old = _batch(isolated_store, sid)
    isolated_store.seed_finding_dispositions(sid, old)
    with isolated_store._db.cursor() as cur:
        isolated_store._db.execute(cur, "UPDATE jobs SET status='done' WHERE batch_id=%s", (old,))
        isolated_store._db.execute(cur, "UPDATE stage_executions SET state='succeeded' WHERE execution_id=%s", (old,))
    original = isolated_store.queue_hitl_review_for_file
    new_batches = []
    def concurrent_start(*args, **kwargs):
        if not new_batches:
            fresh = _batch(isolated_store, sid, 'concurrent-new')
            new_batches.append(fresh)
            isolated_store.seed_finding_dispositions(sid, fresh)
        return original(*args, **kwargs)
    monkeypatch.setattr(isolated_store, 'queue_hitl_review_for_file', concurrent_start)
    isolated_store.reconcile_completed_remediation_reviews(sid)
    assert all(r['disposition'] is None for r in isolated_store.list_finding_dispositions(sid, new_batches[0]))
    assert isolated_store.finding_reconciliation(sid, old)['exact']
