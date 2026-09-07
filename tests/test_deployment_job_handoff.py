"""A worker rollout hands checkpoint-safe work back without duplicating or failing it."""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


def _threaded_turn(worker):
    thread = threading.Thread(target=worker.run_once, daemon=True)
    thread.start()
    return thread


def test_shutdown_requeues_at_a_safe_checkpoint_without_spending_a_retry(isolated_store):
    import worker as worker_mod
    store = isolated_store

    started = threading.Event()

    @worker_mod.handler("deployment_checkpoint")
    def _checkpoint(_payload, _job):
        started.set()
        while True:
            worker_mod.check_cancel()
            time.sleep(0.005)

    sid = "deployment-scan"
    store.init_scan_run(sid, "sharepoint", 1, "2026-09-05T00:00:00Z", "r", "h",
                        owner="pilot@example.com", status="running")
    jid = store.enqueue_job("deployment_checkpoint", {"scan_id": sid}, max_attempts=2,
                            scan_id=sid)
    notices = []
    w = worker_mod.JobWorker(store, worker_id="old-revision",
                             on_retry=lambda job_id, patch: notices.append((job_id, patch)))
    thread = _threaded_turn(w)
    assert started.wait(2), "the old revision never entered the handler"

    w.stop()
    thread.join(2)

    assert not thread.is_alive(), "checkpoint-safe work did not drain promptly"
    row = store.get_job(jid)
    assert row["status"] == "queued"
    assert row["locked_by"] is None and row["lease_expires_at"] is None
    assert row["attempts"] == 1 and row["max_attempts"] == 3
    assert row["max_attempts"] - row["attempts"] == 2, \
        "a planned rollout consumed the customer's retry budget"
    assert row["phase"] == store.DEPLOYMENT_REQUEUE_PHASE
    assert notices == [(jid, {"phase": "deployment_requeue", "attempt": 1,
                              "max_attempts": 3})]
    events = store.list_scan_events(sid)
    handoff = [event for event in events if event["kind"] == "scan.interrupted"]
    assert len(handoff) == 1
    assert handoff[0]["phase"] == "deployment_requeue"
    assert handoff[0]["worker_id"] == "old-revision"
    assert handoff[0]["detail"]["reason"] == "planned deployment handoff"

    replacement = store.claim_job("new-revision")
    assert replacement["id"] == jid and replacement["attempts"] == 2


def test_canonical_stage_follows_a_planned_handoff_through_replacement(isolated_store):
    """A rollout is waiting work, not a failure and not still-active processing."""
    import worker as worker_mod
    store = isolated_store

    started = threading.Event()

    @worker_mod.handler("deployment_stage_checkpoint")
    def _checkpoint(_payload, job):
        if job["locked_by"] == "old-revision":
            started.set()
            while True:
                worker_mod.check_cancel()
                time.sleep(0.005)

    sid = "deployment-stage-scan"
    owner = "pilot@example.com"
    store.init_scan_run(sid, "sharepoint", 1, "2026-09-05T00:00:00Z", "r", "h",
                        owner=owner, status="running")
    execution = store.enqueue_stage_batch(
        sid, "assess", "deployment_stage_checkpoint", [{"scan_id": sid, "file": "one.pdf"}],
        snapshot_id="discover-manifest-1", request_fingerprint="assess-request-1")
    execution_id = execution["batch_id"]
    work_item_id = store.stage_execution_snapshot(execution_id, owner=owner)[
        "counts"]["work_items"]

    old_worker = worker_mod.JobWorker(store, worker_id="old-revision")
    thread = _threaded_turn(old_worker)
    assert started.wait(2), "the old revision never entered the canonical stage handler"

    old_worker.stop()
    thread.join(2)

    assert not thread.is_alive(), "canonical stage work did not hand off promptly"
    queued = store.stage_execution_snapshot(execution_id, owner=owner)
    assert queued["state"] == "queued"
    assert queued["counts"]["work_items"] == {
        **work_item_id, "terminal": 0, "queued": 1, "processing": 0,
    }
    assert queued["attempts"]["terminal"] == 1
    with store._db.cursor() as cur:
        store._db.execute(cur,
            "SELECT worker_id,state,outcome FROM stage_attempts WHERE execution_id=%s ORDER BY started_at",
            (execution_id,))
        assert store._db.fetchall(cur) == [{
            "worker_id": "old-revision", "state": "terminal",
            "outcome": "deployment_handoff",
        }]

    replacement = worker_mod.JobWorker(store, worker_id="new-revision")
    assert replacement.run_once() is True

    completed = store.stage_execution_snapshot(execution_id, owner=owner)
    assert completed["state"] == "succeeded"
    assert completed["reconciliation"]["exact"] is True
    assert completed["counts"]["work_items"]["completed"] == 1
    assert completed["counts"]["work_items"]["terminal"] == 1
    assert completed["output_manifest_id"]
    manifest = store.get_stage_output_manifest(completed["output_manifest_id"], owner=owner)
    assert manifest["item_count"] == 1
    with store._db.cursor() as cur:
        store._db.execute(cur,
            "SELECT worker_id,state,outcome FROM stage_attempts WHERE execution_id=%s ORDER BY started_at",
            (execution_id,))
        assert store._db.fetchall(cur) == [
            {"worker_id": "old-revision", "state": "terminal",
             "outcome": "deployment_handoff"},
            {"worker_id": "new-revision", "state": "terminal", "outcome": "completed"},
        ]


def test_handoff_is_fenced_against_a_replacement_claim(isolated_store):
    store = isolated_store
    jid = store.enqueue_job("deployment_fence", {})
    old = store.claim_job("old-revision")
    assert store.requeue_job_for_deployment(
        jid, worker_id="old-revision", attempt=old["attempts"]) == "queued"
    replacement = store.claim_job("new-revision")

    assert store.requeue_job_for_deployment(
        jid, worker_id="old-revision", attempt=old["attempts"]) == "stale"
    row = store.get_job(jid)
    assert row["status"] == "running" and row["locked_by"] == "new-revision"
    assert row["attempts"] == replacement["attempts"]


def test_shutdown_does_not_interrupt_work_without_a_declared_checkpoint(isolated_store):
    import worker as worker_mod
    store = isolated_store

    started = threading.Event()
    release = threading.Event()

    @worker_mod.handler("deployment_no_checkpoint")
    def _atomic_section(_payload, _job):
        started.set()
        assert release.wait(2)

    jid = store.enqueue_job("deployment_no_checkpoint", {})
    w = worker_mod.JobWorker(store, worker_id="old-revision")
    thread = _threaded_turn(w)
    assert started.wait(2)
    w.stop()
    release.set()
    thread.join(2)

    assert not thread.is_alive()
    assert store.get_job(jid)["status"] == "done"


def test_user_cancellation_wins_over_deployment_handoff(isolated_store):
    import worker as worker_mod
    store = isolated_store

    started = threading.Event()
    proceed = threading.Event()

    @worker_mod.handler("deployment_cancel_priority")
    def _checkpoint(_payload, _job):
        started.set()
        assert proceed.wait(2)
        worker_mod.check_cancel()

    jid = store.enqueue_job("deployment_cancel_priority", {})
    w = worker_mod.JobWorker(store, worker_id="old-revision")
    thread = _threaded_turn(w)
    assert started.wait(2)
    store.request_job_cancellation(jid)
    w.stop()
    proceed.set()
    thread.join(2)

    assert store.get_job(jid)["status"] == "cancelled"
