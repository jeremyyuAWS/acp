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
    assert row["attempts"] == 0, "a planned rollout consumed the customer's retry budget"
    assert row["phase"] == store.DEPLOYMENT_REQUEUE_PHASE
    assert notices == [(jid, {"phase": "deployment_requeue", "attempt": 0,
                              "max_attempts": 2})]
    events = store.list_scan_events(sid)
    handoff = [event for event in events if event["kind"] == "scan.interrupted"]
    assert len(handoff) == 1
    assert handoff[0]["phase"] == "deployment_requeue"
    assert handoff[0]["worker_id"] == "old-revision"
    assert handoff[0]["detail"]["reason"] == "planned deployment handoff"

    replacement = store.claim_job("new-revision")
    assert replacement["id"] == jid and replacement["attempts"] == 1


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
