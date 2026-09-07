"""The canonical workflow-stage contract: identity, revisions, replay and accounting."""
from __future__ import annotations

import pytest

OWNER = "owner@example.org"


def _scan(store, sid="wf-stage-1"):
    store.enqueue_scan(sid, "sharepoint", OWNER, "scan_discover", {"scan_id": sid},
                       inputs={"source": "sharepoint"})
    return sid


def _submit(store, sid, *, intent=None, snapshot="snapshot-a"):
    fingerprint = store.canonical_request_fingerprint(intent or {"mode": "safe", "defaults": True})
    return store.enqueue_stage_batch(
        sid, "remediate", "remediate_file",
        [{"scan_id": sid, "file": "a.docx"}, {"scan_id": sid, "file": "b.docx"}],
        snapshot_id=snapshot, request_fingerprint=fingerprint)


def test_discover_acceptance_and_dynamic_fanout_share_one_execution(isolated_store):
    sid = "discover-canonical"
    returned, entry_job_id = isolated_store.enqueue_scan(
        sid, "sharepoint", OWNER, "scan_discover", {"scan_id": sid},
        inputs={"source": "sharepoint", "folder_ids": ["root"]})
    assert returned == sid
    workflow = isolated_store.workflow_for_scan(sid, OWNER)
    execution = isolated_store.current_stage_execution(workflow["id"], "discover", owner=OWNER)
    assert execution["state"] == "queued"
    assert execution["expected_items"] == 1
    entry = isolated_store.get_job(entry_job_id)
    assert entry["batch_id"] == execution["execution_id"]
    assert entry["payload"]["stage_execution_id"] == execution["execution_id"]

    child_id = isolated_store.enqueue_job(
        "scan_folder", {"scan_id": sid, "folder_id": "folder-a"}, scan_id=sid)
    finalizer_id = isolated_store.enqueue_job("scan_finalize", {"scan_id": sid}, scan_id=sid)
    current = isolated_store.get_stage_execution(execution["execution_id"], owner=OWNER)
    assert current["expected_items"] == 3
    with isolated_store._db.cursor() as cur:
        isolated_store._db.execute(cur,
            "SELECT job_id FROM stage_work_items WHERE execution_id=%s ORDER BY job_id",
            (execution["execution_id"],))
        job_ids = {row["job_id"] for row in isolated_store._db.fetchall(cur)}
    assert job_ids == {entry_job_id, child_id, finalizer_id}


def test_canonical_json_and_immutable_input_define_execution_identity(isolated_store):
    sid = _scan(isolated_store)
    left = isolated_store.canonical_request_fingerprint({"policy": {"b": 2, "a": 1}})
    right = isolated_store.canonical_request_fingerprint({"policy": {"a": 1, "b": 2}})
    assert left == right

    first = _submit(isolated_store, sid, intent={"policy": {"b": 2, "a": 1}})
    replay = _submit(isolated_store, sid, intent={"policy": {"a": 1, "b": 2}})
    assert replay["batch_id"] == first["batch_id"]
    assert replay["reused"] is True


def test_work_item_identity_is_stable_and_partition_is_exact(isolated_store):
    sid = _scan(isolated_store)
    execution = _submit(isolated_store, sid)
    with isolated_store._db.cursor() as cur:
        isolated_store._db.execute(cur,
            "SELECT work_item_id,input_id FROM stage_work_items WHERE execution_id=%s ORDER BY input_id",
            (execution["batch_id"],))
        items = isolated_store._db.fetchall(cur)
    assert [row["input_id"] for row in items] == ["a.docx", "b.docx"]
    assert items[0]["work_item_id"] == isolated_store._work_item_identity(
        execution["batch_id"], "a.docx")
    snapshot = isolated_store.stage_execution_snapshot(execution["batch_id"], owner=OWNER)
    assert snapshot["counts"]["work_items"]["total"] == 2
    assert snapshot["integrity"] == {"ok": True, "affected": [], "violations": []}


def test_snapshot_publishes_every_bucket_used_by_its_reconciliation_equation(isolated_store):
    sid = _scan(isolated_store, "stage-skipped-visible")
    execution = _submit(isolated_store, sid)
    with isolated_store._db.cursor() as cur:
        isolated_store._db.execute(cur,
            "UPDATE stage_work_items SET state='skipped' WHERE execution_id=%s AND input_id=%s",
            (execution["batch_id"], "a.docx"))
    snapshot = isolated_store.stage_execution_snapshot(execution["batch_id"], owner=OWNER)
    work = snapshot["counts"]["work_items"]
    assert work["skipped"] == 1
    assert snapshot["reconciliation"]["accounted"] == sum(
        work[key] for key in ("queued", "processing", "completed", "failed", "cancelled", "skipped"))


def test_duplicate_event_is_noop_and_payload_collision_fails_closed(isolated_store):
    sid = _scan(isolated_store)
    execution = _submit(isolated_store, sid)
    with isolated_store._db.cursor() as cur:
        isolated_store._db.execute(cur,
            "SELECT work_item_id,revision FROM stage_work_items WHERE execution_id=%s ORDER BY input_id LIMIT 1",
            (execution["batch_id"],))
        item = isolated_store._db.fetchone(cur)
    payload = {"result_digest": "sha256:good"}
    first = isolated_store.apply_stage_event(
        event_id="stable-event", execution_id=execution["batch_id"],
        work_item_id=item["work_item_id"], event_type="work_item.completed",
        expected_revision=item["revision"], payload=payload)
    replay = isolated_store.apply_stage_event(
        event_id="stable-event", execution_id=execution["batch_id"],
        work_item_id=item["work_item_id"], event_type="work_item.completed",
        expected_revision=item["revision"], payload=payload)
    assert first["duplicate"] is False and replay["duplicate"] is True

    with pytest.raises(ValueError, match="different payload"):
        isolated_store.apply_stage_event(
            event_id="stable-event", execution_id=execution["batch_id"],
            work_item_id=item["work_item_id"], event_type="work_item.completed",
            expected_revision=item["revision"], payload={"result_digest": "sha256:evil"})
    assert isolated_store.get_stage_execution(execution["batch_id"])["state"] == "integrity_failed"


def test_controls_use_compare_and_set_revision(isolated_store):
    sid = _scan(isolated_store)
    execution = _submit(isolated_store, sid)
    current = isolated_store.get_stage_execution(execution["batch_id"], owner=OWNER)
    paused = isolated_store.control_stage_execution(
        execution["batch_id"], "pause", expected_revision=current["revision"], owner=OWNER)
    assert paused["state"] == "paused"
    with pytest.raises(RuntimeError, match="revision conflict"):
        isolated_store.control_stage_execution(
            execution["batch_id"], "resume", expected_revision=current["revision"], owner=OWNER)
    resumed = isolated_store.control_stage_execution(
        execution["batch_id"], "resume", expected_revision=paused["revision"], owner=OWNER)
    assert resumed["state"] == "processing"


def test_output_manifest_is_sealed_from_deterministic_effect_receipts(isolated_store):
    sid = _scan(isolated_store)
    execution = _submit(isolated_store, sid)
    with isolated_store._db.cursor() as cur:
        isolated_store._db.execute(cur,
            "SELECT work_item_id,revision FROM stage_work_items WHERE execution_id=%s ORDER BY input_id",
            (execution["batch_id"],))
        items = isolated_store._db.fetchall(cur)
    for index, item in enumerate(items):
        isolated_store.apply_stage_event(
            event_id=f"complete-{index}", execution_id=execution["batch_id"],
            work_item_id=item["work_item_id"], event_type="work_item.completed",
            expected_revision=item["revision"], payload={"result_digest": f"sha256:{index}"})
    current = isolated_store.get_stage_execution(execution["batch_id"], owner=OWNER)
    assert current["state"] == "processing_complete"
    receipt = isolated_store.record_side_effect_receipt(
        execution_id=execution["batch_id"], work_item_id=items[0]["work_item_id"],
        effect_type="publish", destination="drive:item-a", content_digest="sha256:0",
        receipt={"provider_id": "item-a"})
    replay = isolated_store.record_side_effect_receipt(
        execution_id=execution["batch_id"], work_item_id=items[0]["work_item_id"],
        effect_type="publish", destination="drive:item-a", content_digest="sha256:0")
    assert replay["effect_id"] == receipt["effect_id"] and replay["reused"] is True
    with pytest.raises(ValueError, match="unknown side-effect receipt"):
        isolated_store.seal_stage_output_manifest(
            execution["batch_id"], [{"work_item_id": items[1]["work_item_id"],
                                     "effect_ids": [receipt["effect_id"]]}],
            expected_revision=current["revision"], owner=OWNER)
    manifest = isolated_store.seal_stage_output_manifest(
        execution["batch_id"], [{"work_item_id": items[0]["work_item_id"],
                                 "effect_ids": [receipt["effect_id"]],
                                 "document": "a.docx"}],
        expected_revision=current["revision"], owner=OWNER)
    final = isolated_store.get_stage_execution(execution["batch_id"], owner=OWNER)
    assert final["state"] == "succeeded"
    assert final["output_manifest_id"] == manifest["manifest_id"]


def test_side_effect_is_reserved_before_write_and_completed_by_fencing_token(isolated_store):
    reservation = isolated_store.reserve_side_effect(
        execution_id="release-execution", work_item_id="release-item",
        effect_type="sharepoint.publish", destination="graph:drive:folder:a.docx",
        content_digest="sha256:corrected", worker_id="worker-1",
        now="2026-09-06T10:00:00+00:00")
    assert reservation["acquired"] is True
    assert reservation["status"] == "reserved"

    busy = isolated_store.reserve_side_effect(
        execution_id="release-execution", work_item_id="release-item",
        effect_type="sharepoint.publish", destination="graph:drive:folder:a.docx",
        content_digest="sha256:corrected", worker_id="worker-2",
        now="2026-09-06T10:01:00+00:00")
    assert busy["acquired"] is False and busy["status"] == "reserved"

    completed = isolated_store.finalize_side_effect(
        reservation["effect_id"], reservation["reservation_token"],
        {"provider_id": "copy-1", "verified": True},
        now="2026-09-06T10:02:00+00:00")
    assert completed["status"] == "completed"
    assert completed["receipt"] == {"provider_id": "copy-1", "verified": True}

    replay = isolated_store.reserve_side_effect(
        execution_id="release-execution", work_item_id="release-item",
        effect_type="sharepoint.publish", destination="graph:drive:folder:a.docx",
        content_digest="sha256:corrected", worker_id="worker-2",
        now="2026-09-06T10:03:00+00:00")
    assert replay["acquired"] is False and replay["reused"] is True
    assert replay["receipt"]["provider_id"] == "copy-1"


def test_side_effect_collision_and_stale_owner_fail_closed(isolated_store):
    first = isolated_store.reserve_side_effect(
        execution_id="release-execution", work_item_id="release-item",
        effect_type="sharepoint.publish", destination="graph:drive:folder:a.docx",
        content_digest="sha256:first", worker_id="worker-1",
        now="2026-09-06T10:00:00+00:00", lease_seconds=60)
    with pytest.raises(ValueError, match="different content"):
        isolated_store.reserve_side_effect(
            execution_id="release-execution", work_item_id="release-item",
            effect_type="sharepoint.publish", destination="graph:drive:folder:a.docx",
            content_digest="sha256:second", worker_id="worker-2",
            now="2026-09-06T10:02:00+00:00")

    successor = isolated_store.reserve_side_effect(
        execution_id="release-execution", work_item_id="release-item",
        effect_type="sharepoint.publish", destination="graph:drive:folder:a.docx",
        content_digest="sha256:first", worker_id="worker-2",
        now="2026-09-06T10:02:00+00:00")
    assert successor["acquired"] is True
    with pytest.raises(RuntimeError, match="stale"):
        isolated_store.finalize_side_effect(
            first["effect_id"], first["reservation_token"], {"provider_id": "zombie"})


def test_failed_side_effect_can_be_reclaimed_with_a_new_token(isolated_store):
    first = isolated_store.reserve_side_effect(
        execution_id="release-execution", work_item_id="release-item",
        effect_type="sharepoint.publish", destination="graph:drive:folder:a.docx",
        content_digest="sha256:corrected", worker_id="worker-1")
    failed = isolated_store.fail_side_effect(
        first["effect_id"], first["reservation_token"], "provider unavailable")
    assert failed["status"] == "failed"
    successor = isolated_store.reserve_side_effect(
        execution_id="release-execution", work_item_id="release-item",
        effect_type="sharepoint.publish", destination="graph:drive:folder:a.docx",
        content_digest="sha256:corrected", worker_id="worker-2")
    assert successor["acquired"] is True
    assert successor["reservation_token"] != first["reservation_token"]


def test_successful_runtime_batch_seals_output_automatically(isolated_store):
    sid = _scan(isolated_store, "runtime-seal")
    execution = _submit(isolated_store, sid)
    receipt_id = None
    receipt_input_id = None
    for worker in ("worker-1", "worker-2"):
        job = isolated_store.claim_job(worker, job_types=("remediate_file",))
        assert job is not None
        item = isolated_store.stage_work_item_for_job(job["id"])
        if receipt_id is None:
            receipt_input_id = item["input_id"]
            receipt_id = isolated_store.record_side_effect_receipt(
                execution_id=execution["batch_id"], work_item_id=item["work_item_id"],
                effect_type="publish", destination="drive:item-a", content_digest="sha256:0",
            )["effect_id"]
        assert isolated_store.complete_job(
            job["id"], worker_id=worker, attempt=int(job["attempts"])) is True

    current = isolated_store.get_stage_execution(execution["batch_id"], owner=OWNER)
    assert current["state"] == "succeeded"
    manifest = isolated_store.get_stage_output_manifest(current["output_manifest_id"], owner=OWNER)
    assert manifest["item_count"] == 2
    assert {entry["input_id"] for entry in manifest["entries"]} == {"a.docx", "b.docx"}
    assert {entry["outcome"] for entry in manifest["entries"]} == {"completed"}
    assert [entry for entry in manifest["entries"] if entry.get("effect_ids")] == [{
        "work_item_id": isolated_store._work_item_identity(execution["batch_id"], receipt_input_id),
        "input_id": receipt_input_id, "outcome": "completed", "result_digest": None,
        "effect_ids": [receipt_id],
    }]


def test_release_lineage_freezes_the_exact_upstream_finding_partition(isolated_store):
    sid = "release-lineage"
    workflow_id = f"workflow-{sid}"
    with isolated_store._db.cursor() as cur:
        isolated_store._db.execute(cur,
            "INSERT INTO scan_runs(id,source,status,owner_email,workflow_id,workflow_revision) "
            "VALUES(%s,'sharepoint','done',%s,%s,1)", (sid, OWNER, workflow_id))
        isolated_store._db.execute(cur,
            "INSERT INTO file_records(scan_id,file,drive_file_id,checksum) "
            "VALUES(%s,'a.docx','provider-a','content-a')", (sid,))
        isolated_store._db.execute(cur,
            "INSERT INTO scan_rule_traces(scan_id,file,rule_id,outcome,finding_count) "
            "VALUES(%s,'a.docx','1.1.1','FAIL',2)", (sid,))
    remediate = isolated_store.enqueue_stage_batch(
        sid, "remediate", "remediate_file", [{"file": "a.docx"}],
        snapshot_id="assessment-snapshot", request_fingerprint="remediate-lineage")
    findings = isolated_store.seed_finding_dispositions(
        sid, remediate["batch_id"], snapshot_id="assessment-snapshot")
    job = isolated_store.claim_job("remediate-worker", job_types=("remediate_file",))
    assert isolated_store.complete_job(
        job["id"], worker_id="remediate-worker", attempt=int(job["attempts"])) is True
    upstream = isolated_store.current_stage_output_manifest(sid, "remediate")
    release = isolated_store.enqueue_stage_batch(
        sid, "release", "publish_file", [{"file": "a.docx"}],
        snapshot_id=upstream["manifest_id"], input_manifest_id=upstream["manifest_id"],
        request_fingerprint="release-lineage")

    lineage = isolated_store.release_finding_lineage(release["batch_id"], "a.docx")
    assert lineage == {
        "upstream_execution_id": remediate["batch_id"],
        "snapshot_id": "assessment-snapshot",
        "findings": [{"finding_id": row["finding_id"], "disposition": None, "revision": 0}
                     for row in sorted(findings, key=lambda row: row["finding_id"])],
    }


def test_current_stage_output_manifest_exposes_only_successfully_sealed_output(isolated_store):
    sid = _scan(isolated_store, "sealed-reader")
    assert isolated_store.current_stage_output_manifest(sid, "discover") is None
    job = isolated_store.claim_job("discover-worker", job_types=("scan_discover",))
    assert isolated_store.complete_job(
        job["id"], worker_id="discover-worker", attempt=int(job["attempts"])) is True
    manifest = isolated_store.current_stage_output_manifest(sid, "discover")
    assert manifest is not None
    assert manifest["stage"] == "discover"


def test_sealed_manifest_is_required_and_carried_across_stage_handoff(isolated_store):
    sid = _scan(isolated_store)
    job = isolated_store.claim_job("discover-handoff", job_types=("scan_discover",))
    assert isolated_store.complete_job(
        job["id"], worker_id="discover-handoff", attempt=job["attempts"])
    manifest = isolated_store.current_stage_output_manifest(sid, "discover")

    downstream = isolated_store.enqueue_stage_batch(
        sid, "assess", "scan_assess", [{"file": "a.docx"}, {"file": "b.docx"}],
        snapshot_id=manifest["manifest_id"], input_manifest_id=manifest["manifest_id"],
        request_fingerprint=isolated_store.canonical_request_fingerprint({"policy": "wcag22"}))
    execution = isolated_store.get_stage_execution(downstream["batch_id"], owner=OWNER)
    assert execution["input_manifest_id"] == manifest["manifest_id"]
    assert execution["provenance"] == "observed"

    with pytest.raises(ValueError, match="input snapshot"):
        isolated_store.enqueue_stage_batch(
            sid, "release", "publish_file", [{"file": "a.docx"}],
            snapshot_id="mutable-alias", input_manifest_id=manifest["manifest_id"],
            request_fingerprint=isolated_store.canonical_request_fingerprint({"target": "drive"}))


def test_stage_snapshot_publishes_one_intuitive_reconciliation_equation(isolated_store):
    sid = _scan(isolated_store)
    execution = _submit(isolated_store, sid)
    snapshot = isolated_store.stage_execution_snapshot(execution["batch_id"], owner=OWNER)
    assert snapshot["reconciliation"] == {
        "unit": "work items", "scope": "this execution",
        "equation": "total = queued + processing + completed + failed + cancelled + skipped",
        "total": 2, "accounted": 2, "unaccounted": 0, "exact": True,
    }
    lineage = isolated_store.canonical_stage_lineage(sid, owner=OWNER)
    assert lineage["available"] is True
    assert lineage["integrity"]["ok"] is False
    assert [stage["stage"] for stage in lineage["stages"]] == ["discover", "remediate"]
    assert lineage["stages"][0]["reconciliation"]["exact"] is True
    assert {stage["stage"]: stage["reconciliation_status"] for stage in lineage["stages"]} == {
        "discover": "partial", "remediate": "unavailable"}
    assert lineage["integrity"]["inconsistent_stages"] == []
    assert lineage["integrity"]["partial_stages"] == ["discover"]
    assert lineage["integrity"]["unavailable_stages"] == ["remediate"]


def test_handoff_rejects_wrong_stage_and_stale_same_workflow_manifests(isolated_store):
    sid = _scan(isolated_store, "strict-stage-links")
    first_job = isolated_store.claim_job("discover-1", job_types=("scan_discover",))
    assert isolated_store.complete_job(
        first_job["id"], worker_id="discover-1", attempt=first_job["attempts"])
    first_manifest = isolated_store.current_stage_output_manifest(sid, "discover")

    with pytest.raises(ValueError, match="sealed remediate output"):
        isolated_store.enqueue_stage_batch(
            sid, "release", "publish_file", [{"file": "a.docx"}],
            snapshot_id=first_manifest["manifest_id"],
            input_manifest_id=first_manifest["manifest_id"],
            request_fingerprint="wrong-stage")

    second = isolated_store.enqueue_stage_batch(
        sid, "discover", "scan_discover", [{"scan_id": sid}], snapshot_id="inventory-v2",
        request_fingerprint="discover-v2")
    second_job = isolated_store.claim_job("discover-2", job_types=("scan_discover",))
    assert second_job["batch_id"] == second["batch_id"]
    assert isolated_store.complete_job(
        second_job["id"], worker_id="discover-2", attempt=second_job["attempts"])

    with pytest.raises(ValueError, match="not the current sealed discover output"):
        isolated_store.enqueue_stage_batch(
            sid, "assess", "scan_assess", [{"file": "a.docx"}],
            snapshot_id=first_manifest["manifest_id"],
            input_manifest_id=first_manifest["manifest_id"],
            request_fingerprint="stale-discover")


def test_lineage_flags_legacy_missing_link_and_terminal_nonexact_reconciliation(isolated_store):
    sid = _scan(isolated_store, "lineage-honesty")
    execution = _submit(isolated_store, sid)
    with isolated_store._db.cursor() as cur:
        isolated_store._db.execute(cur,
            "UPDATE stage_executions SET state='failed',expected_items=3,terminal_items=2 "
            "WHERE execution_id=%s", (execution["batch_id"],))

    lineage = isolated_store.canonical_stage_lineage(sid, owner=OWNER)
    remediate = next(row for row in lineage["stages"] if row["stage"] == "remediate")
    assert remediate["reconciliation_status"] == "inconsistent"
    assert remediate["reconciliation_consistent"] is False
    assert "terminal_reconciliation_not_exact" in remediate["integrity"]["affected"]
    assert lineage["integrity"]["ok"] is False
    assert {link["reason"] for link in lineage["integrity"]["broken_manifest_links"]} == {
        "unavailable"}


def test_historical_backfill_is_idempotent_and_never_invents_evidence(isolated_store):
    sid = _scan(isolated_store, "historical-stage")
    batch = "historical-batch"
    first_job = isolated_store.enqueue_job(
        "scan_file", {"file": "first.docx"}, scan_id=sid, batch_id=batch)
    second_job = isolated_store.enqueue_job(
        "scan_file", {"file": "second.docx"}, scan_id=sid, batch_id=batch)
    with isolated_store._db.cursor() as cur:
        isolated_store._db.execute(cur,
            "UPDATE jobs SET status='done',attempts=1 WHERE id=%s", (first_job,))
        isolated_store._db.execute(cur,
            "UPDATE jobs SET status='dead',attempts=3,error_class='provider' WHERE id=%s",
            (second_job,))

    first = isolated_store.backfill_stage_executions()
    replay = isolated_store.backfill_stage_executions()
    assert first["executions_created"] == 1 and first["work_items_created"] == 2
    assert replay["executions_created"] == 0 and replay["work_items_created"] == 0
    execution = isolated_store.get_stage_execution(batch, owner=OWNER)
    assert execution["provenance"] == "inferred"
    assert execution["state"] == "failed"
    snapshot = isolated_store.stage_execution_snapshot(batch, owner=OWNER)
    assert snapshot["reconciliation"]["exact"] is True
    assert snapshot["counts"]["work_items"]["completed"] == 1
    assert snapshot["counts"]["work_items"]["failed"] == 1
    assert snapshot["attempts"]["total"] == 0


def test_observed_legacy_downstream_stage_exposes_unavailable_lineage(isolated_store):
    sid = _scan(isolated_store, "legacy-assess-lineage")
    batch = "legacy-assess-batch"
    job_id = isolated_store.enqueue_job(
        "scan_assess", {"file": "legacy.docx"}, scan_id=sid, batch_id=batch)
    with isolated_store._db.cursor() as cur:
        isolated_store._db.execute(cur,
            "UPDATE jobs SET status='done',attempts=1 WHERE id=%s", (job_id,))
    isolated_store.backfill_stage_executions()

    lineage = isolated_store.canonical_stage_lineage(sid, owner=OWNER)
    assess = next(row for row in lineage["stages"] if row["stage"] == "assess")
    assert assess["reconciliation"]["exact"] is True
    assert assess["reconciliation_status"] == "unavailable"
    assert assess["reconciliation_consistent"] is False
    assert next(link for link in lineage["integrity"]["broken_manifest_links"]
                if link["stage"] == "assess")["reason"] == "unavailable"
    assert "assess" in lineage["integrity"]["unavailable_stages"]


def test_stop_is_requested_then_acknowledged_not_instantly_claimed(isolated_store):
    sid = _scan(isolated_store)
    execution = _submit(isolated_store, sid)
    running = isolated_store.claim_job("worker-1", job_types=("remediate_file",))
    current = isolated_store.get_stage_execution(execution["batch_id"], owner=OWNER)

    requested = isolated_store.control_stage_execution(
        execution["batch_id"], "cancel", expected_revision=current["revision"], owner=OWNER)
    assert requested["cancel_requested_at"]
    assert requested["state"] == "processing", (
        "a leased attempt was only asked to stop, so the execution is not cancelled yet")
    snapshot = isolated_store.stage_execution_snapshot(execution["batch_id"], owner=OWNER)
    assert snapshot["control"]["cancel_requested"] is True
    assert snapshot["counts"]["work_items"]["processing"] == 1
    assert snapshot["counts"]["work_items"]["cancelled"] == 1

    assert isolated_store.mark_job_cancelled(
        running["id"], worker_id="worker-1", attempt=running["attempts"]) is True
    finished = isolated_store.get_stage_execution(execution["batch_id"], owner=OWNER)
    assert finished["state"] == "cancelled"
    assert finished["terminal_items"] == 2


def test_worker_attempts_are_append_only_across_retry(isolated_store):
    sid = _scan(isolated_store)
    execution = _submit(isolated_store, sid)
    first = isolated_store.claim_job("worker-1", job_types=("remediate_file",))
    assert isolated_store.fail_job(
        first["id"], "temporary", worker_id="worker-1", attempt=first["attempts"]) == "queued"
    other = isolated_store.claim_job("worker-2", job_types=("remediate_file",))
    assert isolated_store.complete_job(
        other["id"], worker_id="worker-2", attempt=other["attempts"])
    second = isolated_store.claim_job("worker-2", job_types=("remediate_file",))
    assert second["id"] == first["id"] and second["attempts"] == 2
    with isolated_store._db.cursor() as cur:
        isolated_store._db.execute(cur,
            "SELECT attempt,worker_id,state,outcome FROM stage_attempts WHERE job_id=%s ORDER BY attempt",
            (first["id"],))
        attempts = isolated_store._db.fetchall(cur)
    assert attempts == [
        {"attempt": 1, "worker_id": "worker-1", "state": "terminal", "outcome": "retrying"},
        {"attempt": 2, "worker_id": "worker-2", "state": "processing", "outcome": None},
    ]
    snapshot = isolated_store.stage_execution_snapshot(execution["batch_id"], owner=OWNER)
    assert snapshot["attempts"]["total"] == 3
    assert snapshot["attempts"]["processing"] == 1
    assert snapshot["attempts"]["terminal"] == 2
    event_types = [event["event_type"] for event in
                   isolated_store.stage_execution_events(execution["batch_id"], owner=OWNER)]
    assert "attempt.started" in event_types
    assert "attempt.retrying" in event_types


def test_workers_publish_direct_replay_safe_lifecycle_events(isolated_store):
    sid = _scan(isolated_store)
    execution = _submit(isolated_store, sid)
    job = isolated_store.claim_job("worker-1", job_types=("remediate_file",))
    events = isolated_store.stage_execution_events(execution["batch_id"], owner=OWNER)
    started = [event for event in events if event["event_type"] == "attempt.started"]
    assert len(started) == 1
    assert not [event for event in events if event["event_type"] == "work_item.processing"]

    replay = isolated_store.publish_worker_stage_event(
        job["id"], "worker-1", job["attempts"], "attempt.started",
        occurred_at=job["claimed_at"])
    assert replay["duplicate"] is True
    assert isolated_store.complete_job(
        job["id"], worker_id="worker-1", attempt=job["attempts"])
    types = [event["event_type"] for event in
             isolated_store.stage_execution_events(execution["batch_id"], owner=OWNER)]
    assert types.count("attempt.started") == 1
    assert types.count("attempt.completed") == 1
    assert "work_item.completed" not in types


def test_stale_attempt_cannot_publish_for_replacement(isolated_store):
    sid = _scan(isolated_store)
    execution = _submit(isolated_store, sid)
    old = isolated_store.claim_job("worker-old", job_types=("remediate_file",))
    assert isolated_store.fail_job(
        old["id"], "retry", worker_id="worker-old", attempt=old["attempts"]) == "queued"
    isolated_store.claim_job("worker-other", job_types=("remediate_file",))
    replacement = isolated_store.claim_job("worker-new", job_types=("remediate_file",))
    assert replacement["id"] == old["id"]

    refused = isolated_store.publish_worker_stage_event(
        old["id"], "worker-old", old["attempts"], "attempt.completed")
    assert refused == {"applied": False, "duplicate": False, "stale": True}
    with isolated_store._db.cursor() as cur:
        isolated_store._db.execute(cur,
            "SELECT state,attempt,lease_owner FROM stage_work_items WHERE job_id=%s", (old["id"],))
        item = isolated_store._db.fetchone(cur)
    assert item == {"state": "processing", "attempt": replacement["attempts"],
                    "lease_owner": "worker-new"}
    assert not [event for event in isolated_store.stage_execution_events(
        execution["batch_id"], owner=OWNER)
        if event["event_type"] == "attempt.completed"
        and event["payload"]["worker_id"] == "worker-old"]


def test_cancellation_deadline_escalates_without_claiming_worker_stopped(
        isolated_store, monkeypatch):
    monkeypatch.setenv("ACP_CANCEL_ACK_DEADLINE_S", "30")
    sid = _scan(isolated_store)
    execution = _submit(isolated_store, sid)
    running = isolated_store.claim_job("worker-1", job_types=("remediate_file",))
    current = isolated_store.get_stage_execution(execution["batch_id"], owner=OWNER)
    isolated_store.control_stage_execution(
        execution["batch_id"], "cancel", expected_revision=current["revision"], owner=OWNER)
    pending = isolated_store.stage_execution_snapshot(execution["batch_id"], owner=OWNER)
    assert pending["control"]["awaiting_acknowledgement"] == 1
    assert pending["control"]["acknowledgement_deadline_at"]

    escalated = isolated_store.escalate_overdue_stage_cancellations(
        now="9999-01-01T00:00:00+00:00")
    assert len(escalated) == 1
    assert isolated_store.escalate_overdue_stage_cancellations(
        now="9999-01-01T00:00:00+00:00") == []
    still_running = isolated_store.stage_execution_snapshot(execution["batch_id"], owner=OWNER)
    assert still_running["state"] == "processing"
    assert still_running["control"]["awaiting_acknowledgement"] == 1
    assert still_running["control"]["escalated_attempts"] == 1
    events = isolated_store.stage_execution_events(execution["batch_id"], owner=OWNER)
    assert sum(event["event_type"] == "attempt.cancellation_deadline_exceeded"
               for event in events) == 1

    assert isolated_store.mark_job_cancelled(
        running["id"], worker_id="worker-1", attempt=running["attempts"])
    stopped = isolated_store.stage_execution_snapshot(execution["batch_id"], owner=OWNER)
    assert stopped["state"] == "cancelled"
    assert stopped["control"]["awaiting_acknowledgement"] == 0
