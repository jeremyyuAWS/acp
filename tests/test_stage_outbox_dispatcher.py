from __future__ import annotations

from stage_outbox import dispatch_database_jobs_once, dispatch_once


OWNER = "outbox@example.org"


def _outbox(store, sid="outbox-scan"):
    store.enqueue_scan(sid, "sharepoint", OWNER, "scan_discover", {"scan_id": sid},
                       inputs={"source": "sharepoint"})
    result = store.enqueue_stage_batch(
        sid, "remediate", "remediate_file", [{"file": "a.docx"}],
        snapshot_id="snapshot", request_fingerprint="request")
    with store._db.cursor() as cur:
        store._db.execute(cur, "SELECT message_id FROM stage_outbox WHERE execution_id=%s",
                          (result["batch_id"],))
        message_id = store._db.fetchone(cur)["message_id"]
    return result["batch_id"], message_id


def test_claim_ack_and_replay_are_idempotent(isolated_store):
    _, message_id = _outbox(isolated_store)
    claimed = isolated_store.claim_stage_outbox("dispatcher-a")
    assert len(claimed) == 1
    assert claimed[0]["payload"]["work_item_id"]
    assert claimed[0]["attempts"] == 1
    assert isolated_store.claim_stage_outbox("dispatcher-b") == []

    assert isolated_store.acknowledge_stage_outbox(
        message_id, "dispatcher-a", delivery_ack="broker-offset-7") is True
    assert isolated_store.acknowledge_stage_outbox(
        message_id, "dispatcher-a", delivery_ack="broker-offset-7") is True
    assert isolated_store.claim_stage_outbox("dispatcher-b") == []


def test_expired_claim_can_be_recovered_but_stale_owner_cannot_ack(isolated_store):
    _, message_id = _outbox(isolated_store)
    isolated_store.claim_stage_outbox("crashed")
    with isolated_store._db.cursor() as cur:
        isolated_store._db.execute(cur,
            "UPDATE stage_outbox SET lease_expires_at='2000-01-01T00:00:00+00:00' "
            "WHERE message_id=%s", (message_id,))
    recovered = isolated_store.claim_stage_outbox("replacement")
    assert recovered[0]["attempts"] == 2
    assert isolated_store.acknowledge_stage_outbox(message_id, "crashed") is False
    assert isolated_store.acknowledge_stage_outbox(message_id, "replacement") is True


def test_failure_retries_then_dead_letters(isolated_store):
    _, message_id = _outbox(isolated_store)
    isolated_store.claim_stage_outbox("dispatcher")
    assert isolated_store.fail_stage_outbox(
        message_id, "dispatcher", "broker unavailable", max_attempts=2,
        backoff_seconds=0) == "retry"
    retry = isolated_store.claim_stage_outbox("dispatcher")
    assert retry[0]["attempts"] == 2
    assert isolated_store.fail_stage_outbox(
        message_id, "dispatcher", "still unavailable", max_attempts=2,
        backoff_seconds=0) == "dead"
    assert isolated_store.claim_stage_outbox("dispatcher") == []
    health = isolated_store.stage_outbox_health(owner=OWNER)
    assert health["dead_lettered"] == 1
    assert health["retrying"] == 0


def test_dispatch_once_acknowledges_transport_receipt(isolated_store):
    _, message_id = _outbox(isolated_store)
    calls = []

    def publish(topic, payload, stable_id):
        calls.append((topic, payload, stable_id))
        return "ack-1"

    result = dispatch_once(isolated_store, publish, dispatcher_id="one-shot")
    assert result.claimed == result.delivered == 1
    assert calls[0][2] == message_id
    health = isolated_store.stage_outbox_health()
    assert health["delivered"] == 1
    assert health["oldest_undelivered_at"] is None
    snapshot = isolated_store.stage_execution_snapshot(calls[0][1]["execution_id"], owner=OWNER)
    assert snapshot["delivery"]["delivered"] == 1
    assert snapshot["delivery"]["pending"] == 0


def test_dispatch_once_records_failure_without_losing_message(isolated_store):
    _outbox(isolated_store)

    def unavailable(_topic, _payload, _message_id):
        raise ConnectionError("offline")

    first = dispatch_once(isolated_store, unavailable, dispatcher_id="dispatcher",
                          max_attempts=2, backoff_seconds=0)
    second = dispatch_once(isolated_store, unavailable, dispatcher_id="dispatcher",
                           max_attempts=2, backoff_seconds=0)
    assert first.retrying == 1
    assert second.dead_lettered == 1


def test_production_database_transport_acknowledges_only_matching_durable_job(isolated_store):
    batch_id, message_id = _outbox(isolated_store, "database-transport")
    result = dispatch_database_jobs_once(
        isolated_store, dispatcher_id="runtime-dispatcher")
    assert result.claimed == result.delivered == 1
    with isolated_store._db.cursor() as cur:
        isolated_store._db.execute(cur,
            "SELECT delivery_ack FROM stage_outbox WHERE message_id=%s", (message_id,))
        ack = isolated_store._db.fetchone(cur)["delivery_ack"]
    assert ack.startswith("database-job:")
    snapshot = isolated_store.stage_execution_snapshot(batch_id, owner=OWNER)
    assert snapshot["delivery"]["delivered"] == 1


def test_production_database_transport_retries_corrupt_identity(isolated_store):
    _, message_id = _outbox(isolated_store, "database-transport-corrupt")
    with isolated_store._db.cursor() as cur:
        isolated_store._db.execute(cur,
            "UPDATE stage_outbox SET topic='wrong-stage' WHERE message_id=%s", (message_id,))
    result = dispatch_database_jobs_once(
        isolated_store, dispatcher_id="runtime-dispatcher", backoff_seconds=0)
    assert result.retrying == 1
    assert isolated_store.stage_outbox_health(owner=OWNER)["retrying"] == 1
