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
