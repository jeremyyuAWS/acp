"""Tests for SKIP LOCKED claim path and lease_expires_at column (ADR 0004, step 2).

Validates:
- claim_job sets lease_expires_at on the claimed row
- touch_job refreshes lease_expires_at
- reclaim_stuck_jobs uses lease_expires_at when set, locked_at fallback when not
- SQLite two-step CAS still returns None when queue is empty
- ACP_JOB_LEASE_S env var controls lease duration
"""
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


def _enqueue(st, *, type="test", run_after=None):
    return st.enqueue_job(type, {"x": 1}, run_after=run_after)


# ── lease_expires_at set on claim ────────────────────────────────────────────

def test_claim_sets_lease_expires_at(isolated_store):
    st = isolated_store
    _enqueue(st)
    job = st.claim_job("w1")
    assert job is not None
    assert job.get("lease_expires_at") is not None
    # lease is in the future
    exp = datetime.fromisoformat(job["lease_expires_at"])
    assert exp > datetime.now(timezone.utc)


def test_claim_empty_queue_returns_none(isolated_store):
    st = isolated_store
    assert st.claim_job("w1") is None


def test_claim_not_yet_runnable_returns_none(isolated_store):
    st = isolated_store
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    _enqueue(st, run_after=future)
    assert st.claim_job("w1") is None


def test_claim_respects_acp_job_lease_s(isolated_store, monkeypatch):
    st = isolated_store
    monkeypatch.setenv("ACP_JOB_LEASE_S", "30")
    _enqueue(st)
    job = st.claim_job("w1")
    assert job is not None
    exp = datetime.fromisoformat(job["lease_expires_at"])
    # Should be ~30s from now, not 600s
    delta = exp - datetime.now(timezone.utc)
    assert 25 < delta.total_seconds() < 40


# ── touch_job refreshes lease ─────────────────────────────────────────────────

def test_touch_job_refreshes_lease(isolated_store, monkeypatch):
    st = isolated_store
    monkeypatch.setenv("ACP_JOB_LEASE_S", "60")
    _enqueue(st)
    job = st.claim_job("w1")
    assert job is not None
    first_exp = job["lease_expires_at"]

    # Advance the env to a longer lease and touch
    monkeypatch.setenv("ACP_JOB_LEASE_S", "3600")
    # Ownership is part of the contract now: only the current holder, on the attempt it claimed,
    # may renew (see tests/test_lease_ownership.py). 'w1' claimed it two lines up, so this is the
    # same refresh this test always asserted — stated explicitly rather than implied by status.
    st.touch_job(job["id"], worker_id="w1", attempt=job["attempts"])

    refreshed = st.get_job(job["id"])
    assert refreshed["lease_expires_at"] != first_exp
    new_delta = (datetime.fromisoformat(refreshed["lease_expires_at"])
                 - datetime.now(timezone.utc))
    assert new_delta.total_seconds() > 3000   # well above the original 60s


# ── reclaim_stuck_jobs ────────────────────────────────────────────────────────

def test_reclaim_uses_lease_expires_at_when_set(isolated_store):
    st = isolated_store
    _enqueue(st)
    job = st.claim_job("w1")
    assert job is not None

    # Manually backdate lease_expires_at to the past
    with st._db.cursor() as cur:
        st._db.execute(cur,
            "UPDATE jobs SET lease_expires_at=%s WHERE id=%s",
            ("2000-01-01T00:00:00+00:00", job["id"]))

    reclaimed = st.reclaim_stuck_jobs(lease_seconds=600)
    assert reclaimed == 1
    assert st.get_job(job["id"])["status"] == "queued"
    assert st.get_job(job["id"])["lease_expires_at"] is None


def test_reclaim_skips_live_lease(isolated_store):
    st = isolated_store
    _enqueue(st)
    job = st.claim_job("w1")
    assert job is not None
    # lease_expires_at is in the future; nothing should be reclaimed
    assert st.reclaim_stuck_jobs(lease_seconds=600) == 0
    assert st.get_job(job["id"])["status"] == "running"


def test_reclaim_falls_back_to_locked_at_when_no_lease_column(isolated_store):
    """Rows that pre-date the migration have lease_expires_at=NULL.
    The sweeper must still reclaim them using locked_at."""
    st = isolated_store
    _enqueue(st)
    job = st.claim_job("w1")
    assert job is not None

    # Erase lease_expires_at to simulate a pre-migration row, and backdate locked_at
    with st._db.cursor() as cur:
        st._db.execute(cur,
            "UPDATE jobs SET lease_expires_at=NULL, locked_at=%s WHERE id=%s",
            ("2000-01-01T00:00:00+00:00", job["id"]))

    reclaimed = st.reclaim_stuck_jobs(lease_seconds=600)
    assert reclaimed == 1
    assert st.get_job(job["id"])["status"] == "queued"


def test_reclaim_clears_lease_expires_at_on_reclaim(isolated_store):
    st = isolated_store
    _enqueue(st)
    job = st.claim_job("w1")

    with st._db.cursor() as cur:
        st._db.execute(cur,
            "UPDATE jobs SET lease_expires_at=%s WHERE id=%s",
            ("2000-01-01T00:00:00+00:00", job["id"]))

    st.reclaim_stuck_jobs()
    requeued = st.get_job(job["id"])
    assert requeued["status"] == "queued"
    assert requeued["lease_expires_at"] is None


# ── claim is idempotent-safe: two workers cannot both claim the same job ──────

def test_two_claim_calls_return_different_jobs(isolated_store):
    st = isolated_store
    jid1 = _enqueue(st)
    jid2 = _enqueue(st)

    j1 = st.claim_job("w1")
    j2 = st.claim_job("w2")

    assert j1 is not None and j2 is not None
    assert j1["id"] != j2["id"]
    assert {j1["id"], j2["id"]} == {jid1, jid2}


def test_third_claim_returns_none_when_queue_exhausted(isolated_store):
    st = isolated_store
    _enqueue(st)
    _enqueue(st)

    st.claim_job("w1")
    st.claim_job("w2")
    assert st.claim_job("w3") is None


# ── complete_job and fail_job clear lease ─────────────────────────────────────

def test_complete_job_leaves_done_status(isolated_store):
    st = isolated_store
    _enqueue(st)
    job = st.claim_job("w1")
    st.complete_job(job["id"])
    assert st.get_job(job["id"])["status"] == "done"


def test_fail_job_requeues_within_attempts(isolated_store):
    st = isolated_store
    _enqueue(st)
    job = st.claim_job("w1")
    result = st.fail_job(job["id"], "transient error", backoff_seconds=0)
    assert result == "queued"
    assert st.get_job(job["id"])["status"] == "queued"
