"""Durable job-queue tests (ADR 0004) — store methods + JobWorker.

Runs against a fresh SQLite database. The schema's Postgres-only
`ALTER TABLE ... ADD COLUMN IF NOT EXISTS` migration statements are filtered out
for SQLite (their columns already exist in the CREATE TABLE for a fresh DB).
"""
from __future__ import annotations
import sys
import tempfile
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))


@pytest.fixture()
def store():
    import store as store_mod
    tmp = Path(tempfile.mkdtemp()) / "jobs-test.db"
    store_mod._SQLITE_PATH = tmp
    store_mod._SCHEMA[:] = [s for s in store_mod._SCHEMA
                            if not s.strip().upper().startswith("ALTER TABLE")]
    return store_mod.Store()


def test_enqueue_claim_complete(store):
    jid = store.enqueue_job("scan_file", {"file": "a.docx"}, scan_id="s1")
    assert store.get_job(jid)["status"] == "queued"

    job = store.claim_job("w1")
    assert job["id"] == jid
    assert job["status"] == "running"
    assert job["attempts"] == 1
    assert job["payload"] == {"file": "a.docx"}      # JSON round-trips to a dict

    # Queue is now empty — nothing else to claim.
    assert store.claim_job("w1") is None

    store.complete_job(jid)
    assert store.get_job(jid)["status"] == "done"


def test_priority_order(store):
    store.enqueue_job("t", {"n": 1}, priority=100)
    store.enqueue_job("t", {"n": 2}, priority=10)     # higher priority (lower number)
    first = store.claim_job("w1")
    assert first["payload"]["n"] == 2


def test_retry_then_dead_letter(store):
    jid = store.enqueue_job("t", {}, max_attempts=2)

    store.claim_job("w1")                              # attempt 1
    assert store.fail_job(jid, "boom", backoff_seconds=0) == "queued"
    assert store.get_job(jid)["status"] == "queued"
    assert store.get_job(jid)["last_error"] == "boom"

    store.claim_job("w1")                              # attempt 2 == max
    assert store.fail_job(jid, "boom again", backoff_seconds=0) == "dead"
    assert store.get_job(jid)["status"] == "dead"


def test_force_dead(store):
    jid = store.enqueue_job("t", {}, max_attempts=10)
    store.claim_job("w1")
    assert store.fail_job(jid, "fatal", force_dead=True) == "dead"
    assert store.get_job(jid)["status"] == "dead"


def test_backoff_gate_hides_job(store):
    jid = store.enqueue_job("t", {})
    store.claim_job("w1")
    store.fail_job(jid, "transient", backoff_seconds=3600)   # run_after in the future
    # Not eligible yet → claim returns nothing.
    assert store.claim_job("w1") is None


def test_reclaim_stuck(store):
    jid = store.enqueue_job("t", {})
    store.claim_job("w1")                              # now 'running'
    assert store.get_job(jid)["status"] == "running"
    # Lease 0 → the running job is immediately considered stuck.
    assert store.reclaim_stuck_jobs(lease_seconds=0) == 1
    assert store.get_job(jid)["status"] == "queued"


def test_job_stats(store):
    a = store.enqueue_job("t", {})
    store.enqueue_job("t", {})
    store.claim_job("w1")
    store.complete_job(a) if store.get_job(a)["status"] == "running" else None
    stats = store.job_stats()
    assert stats.get("queued", 0) + stats.get("done", 0) >= 1


def test_worker_runs_handler(store):
    import worker
    seen = []

    @worker.handler("greet")
    def _greet(payload, job):
        seen.append(payload["name"])

    jid = store.enqueue_job("greet", {"name": "ada"})
    w = worker.JobWorker(store, worker_id="w-test")
    assert w.run_once() is True                        # handled one
    assert seen == ["ada"]
    assert store.get_job(jid)["status"] == "done"
    assert w.run_once() is False                       # queue empty


def test_worker_retries_then_dead(store):
    import worker

    @worker.handler("always_fail")
    def _boom(payload, job):
        raise ValueError("nope")

    jid = store.enqueue_job("always_fail", {}, max_attempts=3)
    w = worker.JobWorker(store, worker_id="w-test")
    for _ in range(3):
        w.run_once()
        # Clear the backoff gate so the requeued job is eligible on the next claim.
        if store.get_job(jid)["status"] == "queued":
            with store._db.cursor() as cur:
                store._db.execute(cur, "UPDATE jobs SET run_after=%s WHERE id=%s",
                                  (store._now(), jid))
    assert store.get_job(jid)["status"] == "dead"


def test_worker_no_handler_dead_letters_eventually(store):
    import worker
    jid = store.enqueue_job("unknown_type", {}, max_attempts=1)
    w = worker.JobWorker(store, worker_id="w-test")
    w.run_once()
    assert store.get_job(jid)["status"] == "dead"
