"""Stage snapshots reconcile in stable domain units as well as queue work items."""
from __future__ import annotations


OWNER = "stage-integrity@example.org"


def _scan(store, sid: str) -> tuple[str, str]:
    store.enqueue_scan(sid, "sharepoint", OWNER, "scan_discover", {"scan_id": sid},
                       inputs={"source": "sharepoint"})
    workflow = store.workflow_for_scan(sid, OWNER)
    return sid, workflow["id"]


def _execution(store, sid: str, stage: str, items: list[dict]) -> dict:
    return store.enqueue_stage_batch(
        sid, stage, {"assess": "scan_assess", "remediate": "remediate_file",
                     "release": "publish_file"}[stage], items,
        snapshot_id=f"{stage}-snapshot",
        request_fingerprint=store.canonical_request_fingerprint({"stage": stage}))


def test_discover_reconciles_the_durable_inventory_lifecycle_partition(isolated_store):
    sid, workflow_id = _scan(isolated_store, "domain-discover")
    isolated_store.add_inventory(sid, [{"file": "active.docx"}, {"file": "old.docx"}])
    with isolated_store._db.cursor() as cur:
        isolated_store._db.execute(cur,
            "UPDATE scan_inventory SET lifecycle_status='Archive Candidate' "
            "WHERE scan_id=%s AND file='old.docx'", (sid,))
    execution = isolated_store.current_stage_execution(workflow_id, "discover", owner=OWNER)

    domain = isolated_store.stage_execution_snapshot(
        execution["execution_id"], owner=OWNER)["domain_reconciliation"]

    assert domain == {
        "unit": "inventory documents", "scope": "discovered inventory",
        "equation": "inventory = sum(lifecycle status buckets)",
        "total": 2, "partitioned": 2, "unaccounted": 0,
        "buckets": {"Active": 1, "Archive Candidate": 1}, "exact": True,
    }


def test_assess_reconciles_every_eligible_input_without_using_discover_total(isolated_store):
    sid, _ = _scan(isolated_store, "domain-assess")
    execution = _execution(isolated_store, sid, "assess", [
        {"file": "assessed.docx"}, {"file": "skipped.pdf"}, {"file": "waiting.pptx"}])
    with isolated_store._db.cursor() as cur:
        isolated_store._db.execute(cur,
            "UPDATE stage_work_items SET state='completed' WHERE execution_id=%s AND input_id=%s",
            (execution["batch_id"], "assessed.docx"))
        isolated_store._db.execute(cur,
            "UPDATE stage_work_items SET state='skipped' WHERE execution_id=%s AND input_id=%s",
            (execution["batch_id"], "skipped.pdf"))

    domain = isolated_store.stage_execution_snapshot(
        execution["batch_id"], owner=OWNER)["domain_reconciliation"]

    assert domain["total"] == 3
    assert domain["buckets"] == {"waiting": 1, "processing": 0, "assessed": 1,
                                  "failed": 0, "cancelled": 0, "skipped": 1}
    assert domain["accounted"] == 3 and domain["exact"] is True


def test_remediate_reconciles_assessed_findings_by_current_disposition(isolated_store):
    sid, _ = _scan(isolated_store, "domain-remediate")
    with isolated_store._db.cursor() as cur:
        isolated_store._db.execute(cur,
            "INSERT INTO file_records(scan_id,file,drive_file_id,checksum) "
            "VALUES(%s,'a.docx','provider-a','sha-a')", (sid,))
        isolated_store._db.execute(cur,
            "INSERT INTO scan_rule_traces(scan_id,file,rule_id,outcome,finding_count) "
            "VALUES(%s,'a.docx','1.1.1','FAIL',2)", (sid,))
    execution = _execution(
        isolated_store, sid, "remediate", [{"file": "a.docx", "scan_id": sid}])
    rows = isolated_store.seed_finding_dispositions(
        sid, execution["batch_id"], snapshot_id="remediate-snapshot")
    isolated_store.transition_finding_disposition(
        sid, execution["batch_id"], rows[0]["finding_id"], "resolved_verified",
        expected_revision=0, event_id="finding-resolved", fix_evidence_ids=["diff:1"],
        verified_at="2026-09-07T00:00:00+00:00")
    isolated_store.transition_finding_disposition(
        sid, execution["batch_id"], rows[1]["finding_id"], "excluded_by_policy",
        expected_revision=0, event_id="finding-excluded")

    domain = isolated_store.stage_execution_snapshot(
        execution["batch_id"], owner=OWNER)["domain_reconciliation"]

    assert domain["total"] == 2 and domain["accounted"] == 2
    assert domain["buckets"]["resolved_verified"] == 1
    assert domain["buckets"]["excluded"] == 1
    assert domain["exact"] is True


def test_release_published_count_requires_a_verified_completed_receipt(isolated_store):
    sid, _ = _scan(isolated_store, "domain-release")
    execution = _execution(isolated_store, sid, "release", [
        {"file": "published.docx"}, {"file": "unverified.docx"}, {"file": "waiting.docx"}])
    with isolated_store._db.cursor() as cur:
        isolated_store._db.execute(cur,
            "UPDATE stage_work_items SET state='completed' WHERE execution_id=%s "
            "AND input_id IN (%s,%s)",
            (execution["batch_id"], "published.docx", "unverified.docx"))
        isolated_store._db.execute(cur,
            "SELECT work_item_id,input_id FROM stage_work_items WHERE execution_id=%s",
            (execution["batch_id"],))
        item_ids = {row["input_id"]: row["work_item_id"]
                    for row in isolated_store._db.fetchall(cur)}
    isolated_store.record_side_effect_receipt(
        execution_id=execution["batch_id"], work_item_id=item_ids["published.docx"],
        effect_type="sharepoint.publish", destination="published.docx",
        content_digest="sha-published", receipt={"verified": True})
    isolated_store.record_side_effect_receipt(
        execution_id=execution["batch_id"], work_item_id=item_ids["unverified.docx"],
        effect_type="sharepoint.publish", destination="unverified.docx",
        content_digest="sha-unverified", receipt={"verified": False})

    domain = isolated_store.stage_execution_snapshot(
        execution["batch_id"], owner=OWNER)["domain_reconciliation"]

    assert domain["total"] == 3 and domain["accounted"] == 3
    assert domain["buckets"] == {"waiting": 1, "processing": 0, "published": 1,
                                  "completed_unverified": 1, "failed": 0,
                                  "cancelled": 0, "skipped": 0}
    assert domain["published_receipt_rule"] == "completed receipt with verified=true"
    assert domain["exact"] is True

