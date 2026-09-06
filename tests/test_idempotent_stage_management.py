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
    manifest = isolated_store.seal_stage_output_manifest(
        execution["batch_id"], [{"effect_id": receipt["effect_id"], "document": "a.docx"}],
        expected_revision=current["revision"], owner=OWNER)
    final = isolated_store.get_stage_execution(execution["batch_id"], owner=OWNER)
    assert final["state"] == "succeeded"
    assert final["output_manifest_id"] == manifest["manifest_id"]


def test_sealed_manifest_is_required_and_carried_across_stage_handoff(isolated_store):
    sid = _scan(isolated_store)
    upstream = _submit(isolated_store, sid)
    with isolated_store._db.cursor() as cur:
        isolated_store._db.execute(cur,
            "SELECT work_item_id,revision FROM stage_work_items WHERE execution_id=%s ORDER BY input_id",
            (upstream["batch_id"],))
        items = isolated_store._db.fetchall(cur)
    for index, item in enumerate(items):
        isolated_store.apply_stage_event(
            event_id=f"handoff-complete-{index}", execution_id=upstream["batch_id"],
            work_item_id=item["work_item_id"], event_type="work_item.completed",
            expected_revision=item["revision"], payload={"result_digest": f"result:{index}"})
    current = isolated_store.get_stage_execution(upstream["batch_id"], owner=OWNER)
    manifest = isolated_store.seal_stage_output_manifest(
        upstream["batch_id"], [{"document": "a.docx"}, {"document": "b.docx"}],
        expected_revision=current["revision"], owner=OWNER)

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
