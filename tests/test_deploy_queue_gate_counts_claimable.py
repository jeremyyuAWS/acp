"""The deploy gate must count work a worker can actually take.

FOUND IN PRODUCTION, 2026-09-09. `/readyz` reported `queue: {queued: 1, running: 0, active: 1}`
unchanged across forty minutes while all three worker roles heartbeated within seconds, and four
consecutive deploys died on redeploy.sh's

    ✗ 1 queued/running job(s) are active; wait for queues to drain

Nothing was draining because the row was not claimable, and nothing was at risk because nothing
was running. `job_stats` counts every `status='queued'` row; `claim_job` only ever takes one whose
`run_after` is due and whose `attempts` are below `max_attempts`. A row failing either test is
invisible to every worker and permanent in the count — so it wedges deploys forever.

The gate now counts running work plus CLAIMABLE queued work. A claimable job is about to be picked
up and a running one already has been, so the protection this guard exists for is intact.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))


def _iso(**delta) -> str:
    return (datetime.now(timezone.utc) + timedelta(**delta)).isoformat()


def _set(store, job_id: str, **columns) -> None:
    """Put a row into a state the public API reaches only through failure paths."""
    assignments = ",".join(f"{name}=%s" for name in columns)
    with store._db.cursor() as cur:
        store._db.execute(cur, f"UPDATE jobs SET {assignments} WHERE id=%s",
                          (*columns.values(), job_id))


def test_a_deferred_or_exhausted_row_is_queued_but_not_claimable(isolated_store):
    store = isolated_store
    ready = store.enqueue_job("scan_file", {"file": "a.docx"})
    deferred = store.enqueue_job("scan_file", {"file": "b.docx"}, run_after=_iso(hours=1))
    exhausted = store.enqueue_job("scan_file", {"file": "c.docx"}, max_attempts=3)
    _set(store, exhausted, attempts=3)

    # All three are queued rows — that count is a true fact about the table and stays.
    assert store.job_stats().get("queued") == 3
    # Only one of them can be claimed, and it is the one claim_job actually takes.
    assert store.claimable_job_count() == 1
    claimed = store.claim_job("worker-1")
    assert claimed["id"] == ready
    assert deferred != claimed["id"] and exhausted != claimed["id"]
    # With the only eligible row now running, nothing further is claimable — but two rows remain
    # queued, which is exactly the state that used to block every deploy.
    assert store.claimable_job_count() == 0
    assert store.job_stats().get("queued") == 2


def test_readyz_active_counts_running_plus_claimable_only(monkeypatch, isolated_store):
    import core
    from fastapi.testclient import TestClient

    from app import app

    store = isolated_store
    stuck = store.enqueue_job("scan_file", {"file": "stuck.docx"}, run_after=_iso(hours=1))
    monkeypatch.setattr(core, "store", store)

    queue = TestClient(app).get("/readyz").json()["queue"]
    assert queue["available"] is True
    assert queue["queued"] == 1, "the row is still reported — this is not hiding it"
    assert queue["claimable"] == 0
    assert queue["running"] == 0
    # The number redeploy.sh gates on. A production deploy proceeds here; before this fix the
    # same state refused four in a row.
    assert queue["active"] == 0, f"a job no worker can claim must not block a deploy: {queue}"

    _set(store, stuck, run_after=store._now())
    queue = TestClient(app).get("/readyz").json()["queue"]
    assert (queue["claimable"], queue["active"]) == (1, 1), "due work still holds the gate shut"

    store.claim_job("worker-1")
    queue = TestClient(app).get("/readyz").json()["queue"]
    assert (queue["running"], queue["claimable"], queue["active"]) == (1, 0, 1), \
        "a RUNNING job is exactly what the cutover would interrupt"
