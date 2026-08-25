"""Reconciliation sweeper (ADR 0004 step 5): periodic queue/scan consistency repair.

Tests:
- sweep_exhausted_jobs() dead-letters queued jobs at max_attempts
- sweep_orphaned_scans() marks stranded running scans 'interrupted'
- run_sweep() orchestrates all four checks and returns accurate counts
- Sweeper class runs the loop and stops cleanly
"""
import sys
import time
import threading
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import sweeper as sw


def _enqueue(st, **kw):
    return st.enqueue_job("test", {"x": 1}, **kw)


def _make_scan(st, sid="s1", *, status="running", started_at=None):
    now = started_at or datetime.now(timezone.utc).isoformat()
    with st._db.cursor() as cur:
        st._db.execute(cur,
            "INSERT INTO scan_runs(id, status, started_at, source, files) "
            "VALUES(%s,%s,%s,%s,%s)",
            (sid, status, now, "local", 0))
    return sid


# ── sweep_exhausted_jobs ──────────────────────────────────────────────────────

def test_sweep_exhausted_jobs_dead_letters_at_max(isolated_store):
    st = isolated_store
    jid = _enqueue(st)
    # Manually set attempts = max_attempts while keeping status='queued'
    with st._db.cursor() as cur:
        st._db.execute(cur,
            "UPDATE jobs SET attempts=max_attempts WHERE id=%s", (jid,))
    count = st.sweep_exhausted_jobs()
    assert count == 1
    assert st.get_job(jid)["status"] == "dead"


def test_sweep_exhausted_jobs_skips_below_max(isolated_store):
    st = isolated_store
    jid = _enqueue(st)
    with st._db.cursor() as cur:
        st._db.execute(cur,
            "UPDATE jobs SET attempts=max_attempts-1 WHERE id=%s", (jid,))
    assert st.sweep_exhausted_jobs() == 0
    assert st.get_job(jid)["status"] == "queued"


def test_sweep_exhausted_jobs_skips_running(isolated_store):
    """Running jobs with max attempts must NOT be dead-lettered by the sweeper
    (the worker's fail_job call handles that when the job finishes)."""
    st = isolated_store
    jid = _enqueue(st)
    st.claim_job("w1")
    with st._db.cursor() as cur:
        st._db.execute(cur,
            "UPDATE jobs SET attempts=max_attempts WHERE id=%s", (jid,))
    assert st.sweep_exhausted_jobs() == 0
    assert st.get_job(jid)["status"] == "running"


def test_sweep_exhausted_jobs_skips_done(isolated_store):
    st = isolated_store
    jid = _enqueue(st)
    st.claim_job("w1")
    st.complete_job(jid)
    with st._db.cursor() as cur:
        st._db.execute(cur,
            "UPDATE jobs SET attempts=max_attempts WHERE id=%s", (jid,))
    assert st.sweep_exhausted_jobs() == 0
    assert st.get_job(jid)["status"] == "done"


def test_sweep_exhausted_jobs_multiple(isolated_store):
    st = isolated_store
    jid1 = _enqueue(st)
    jid2 = _enqueue(st)
    jid3 = _enqueue(st)
    with st._db.cursor() as cur:
        st._db.execute(cur,
            "UPDATE jobs SET attempts=max_attempts WHERE id IN (%s,%s)",
            (jid1, jid2))
    count = st.sweep_exhausted_jobs()
    assert count == 2
    assert st.get_job(jid1)["status"] == "dead"
    assert st.get_job(jid2)["status"] == "dead"
    assert st.get_job(jid3)["status"] == "queued"


def test_sweep_exhausted_jobs_error_message_mentions_sweeper(isolated_store):
    st = isolated_store
    jid = _enqueue(st)
    with st._db.cursor() as cur:
        st._db.execute(cur,
            "UPDATE jobs SET attempts=max_attempts WHERE id=%s", (jid,))
    st.sweep_exhausted_jobs()
    assert "sweeper" in (st.get_job(jid)["last_error"] or "").lower()


# ── sweep_orphaned_scans ──────────────────────────────────────────────────────

def _old_timestamp(seconds_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat()


def test_sweep_orphaned_scans_marks_interrupted(isolated_store):
    st = isolated_store
    old = _old_timestamp(1200)
    _make_scan(st, "s1", started_at=old)
    count = st.sweep_orphaned_scans(grace_seconds=600)
    assert count == 1
    with st._db.cursor() as cur:
        st._db.execute(cur, "SELECT status FROM scan_runs WHERE id=%s", ("s1",))
        row = st._db.fetchone(cur)
    assert row["status"] == "interrupted"


def test_sweep_orphaned_scans_skips_within_grace(isolated_store):
    st = isolated_store
    recent = _old_timestamp(60)
    _make_scan(st, "s1", started_at=recent)
    assert st.sweep_orphaned_scans(grace_seconds=600) == 0
    with st._db.cursor() as cur:
        st._db.execute(cur, "SELECT status FROM scan_runs WHERE id=%s", ("s1",))
        row = st._db.fetchone(cur)
    assert row["status"] == "running"


def test_sweep_orphaned_scans_skips_scan_with_active_jobs(isolated_store):
    st = isolated_store
    old = _old_timestamp(1200)
    _make_scan(st, "s1", started_at=old)
    _enqueue(st, scan_id="s1")  # active queued job
    assert st.sweep_orphaned_scans(grace_seconds=600) == 0
    with st._db.cursor() as cur:
        st._db.execute(cur, "SELECT status FROM scan_runs WHERE id=%s", ("s1",))
        row = st._db.fetchone(cur)
    assert row["status"] == "running"


def test_sweep_orphaned_scans_skips_non_running(isolated_store):
    st = isolated_store
    old = _old_timestamp(1200)
    _make_scan(st, "s1", status="done", started_at=old)
    assert st.sweep_orphaned_scans(grace_seconds=600) == 0


def test_sweep_orphaned_scans_multiple(isolated_store):
    st = isolated_store
    old = _old_timestamp(1200)
    _make_scan(st, "s1", started_at=old)
    _make_scan(st, "s2", started_at=old)
    _make_scan(st, "s3", status="done", started_at=old)
    count = st.sweep_orphaned_scans(grace_seconds=600)
    assert count == 2


# ── run_sweep (integration) ───────────────────────────────────────────────────

def test_run_sweep_returns_counts(isolated_store):
    st = isolated_store
    # Exhausted job
    jid = _enqueue(st)
    with st._db.cursor() as cur:
        st._db.execute(cur,
            "UPDATE jobs SET attempts=max_attempts WHERE id=%s", (jid,))
    # Orphaned scan
    old = _old_timestamp(1200)
    _make_scan(st, "s1", started_at=old)

    result = sw.run_sweep(st, lease_seconds=600, grace_seconds=600)
    assert result["exhausted_dead"] == 1
    assert result["scans_interrupted"] == 1
    assert result["reclaimed"] == 0
    assert result["scans_rescued"] == 0


def test_run_sweep_empty_queue_returns_zeros(isolated_store):
    result = sw.run_sweep(isolated_store, lease_seconds=600, grace_seconds=600)
    assert all(v == 0 for v in result.values())


def test_run_sweep_counts_reclaimed(isolated_store):
    st = isolated_store
    jid = _enqueue(st)
    st.claim_job("w1")
    # Backdate locked_at to simulate a stuck job
    stale = _old_timestamp(700)
    with st._db.cursor() as cur:
        st._db.execute(cur, "UPDATE jobs SET locked_at=%s WHERE id=%s", (stale, jid))

    result = sw.run_sweep(st, lease_seconds=600, grace_seconds=600)
    assert result["reclaimed"] == 1
    assert st.get_job(jid)["status"] == "queued"


# ── Sweeper class ─────────────────────────────────────────────────────────────

def test_sweeper_runs_at_least_once(isolated_store):
    st = isolated_store
    ran = threading.Event()
    original_run_sweep = sw.run_sweep

    def _patched(store, **kw):
        result = original_run_sweep(store, **kw)
        ran.set()
        return result

    sw.run_sweep = _patched
    try:
        sweeper = sw.Sweeper(st, interval_s=1)
        sweeper.start()
        assert ran.wait(timeout=5), "Sweeper did not call run_sweep within 5s"
        sweeper.stop()
    finally:
        sw.run_sweep = original_run_sweep


def test_sweeper_stops_cleanly(isolated_store):
    sweeper = sw.Sweeper(isolated_store, interval_s=60)
    sweeper.start()
    time.sleep(0.1)
    sweeper.stop(timeout=2.0)
    assert not sweeper._thread.is_alive()
