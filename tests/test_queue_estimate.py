"""Store.queue_estimate — "when will my work actually begin?" for one scan's Discover/Assess/
Remediate job, the data source for the queue-status panel on those three tabs.

What this pins:
  * no live job of the requested kind -> {"available": False}
  * a running job -> "claimed", carrying worker_assigned_at/phase, no wait math
  * a queued job whose run_after is still in the future -> "scheduled", carrying the exact time
  * fewer than 3 recent completions of this kind -> "insufficient_history", no earliest/latest
  * enough recent completions -> "estimated", with an earliest/latest range around
    compatible_jobs_ahead ÷ recent throughput, and confidence banded by sample size
  * compatible_jobs_ahead / compatible_workers_busy only count jobs of the SAME kind — a queued
    remediate_file job must not be inflated by queued scan_batch jobs
  * claim order is respected — a job ahead in (priority, run_after) counts as "ahead"; one behind
    it does not
  * ready_workers=0 short-circuits to "no_worker_available" before any wait math runs
  * owner scoping: a foreign owner's request finds no job, exactly like get_scan
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest


def _iso(dt):
    return dt.isoformat()


def _now():
    return datetime.now(timezone.utc)


def _seed_scan(st, sid, owner="demo"):
    st.init_scan_run(sid, "drive", 1, _iso(_now()), "default", "rh", owner=owner, status="running")


def _enqueue(st, jtype, sid, *, status="queued", run_after=None, priority=100,
            locked_at=None, phase=None, updated_at=None):
    jid = st.enqueue_job(jtype, {"scan_id": sid}, priority=priority,
                         run_after=run_after or _iso(_now()), scan_id=sid)
    with st._db.cursor() as cur:
        st._db.execute(cur, "UPDATE jobs SET status=%s, locked_at=%s, phase=%s WHERE id=%s",
                       (status, locked_at, phase, jid))
        if updated_at is not None:
            st._db.execute(cur, "UPDATE jobs SET updated_at=%s WHERE id=%s", (updated_at, jid))
    return jid


# ── no live job ────────────────────────────────────────────────────────────────

def test_no_job_of_this_kind_is_unavailable(isolated_store):
    _seed_scan(isolated_store, "s1")
    assert isolated_store.queue_estimate("s1", "remediate") == {"available": False}


def test_unknown_kind_raises(isolated_store):
    with pytest.raises(ValueError):
        isolated_store.queue_estimate("s1", "publish")


# ── claimed ──────────────────────────────────────────────────────────────────

def test_running_job_is_claimed_not_estimated(isolated_store):
    _seed_scan(isolated_store, "s1")
    when = _iso(_now())
    _enqueue(isolated_store, "scan_batch", "s1", status="running", locked_at=when, phase="listing")

    r = isolated_store.queue_estimate("s1", "discover")
    assert r["available"] is True
    assert r["state"] == "claimed"
    assert r["job_type"] == "scan_batch"
    assert r["worker_assigned_at"] == when
    assert r["phase"] == "listing"
    assert "compatible_jobs_ahead" not in r, "a claimed job has no wait to estimate"


# ── scheduled (future run_after — retry backoff) ───────────────────────────────

def test_queued_job_with_future_run_after_is_scheduled(isolated_store):
    _seed_scan(isolated_store, "s1")
    future = _iso(_now() + timedelta(minutes=5))
    _enqueue(isolated_store, "remediate_file", "s1", run_after=future)

    r = isolated_store.queue_estimate("s1", "remediate")
    assert r["state"] == "scheduled"
    assert r["run_after"] == future


# ── no worker available ────────────────────────────────────────────────────────

def test_zero_ready_workers_short_circuits_before_wait_math(isolated_store):
    _seed_scan(isolated_store, "s1")
    _enqueue(isolated_store, "scan_assess", "s1")

    r = isolated_store.queue_estimate("s1", "assess", ready_workers=0)
    assert r["state"] == "no_worker_available"
    assert r["ready_workers"] == 0


# ── insufficient history ────────────────────────────────────────────────────────

def test_fewer_than_three_recent_completions_is_insufficient_history(isolated_store):
    _seed_scan(isolated_store, "s1")
    _seed_scan(isolated_store, "s-done", owner="demo")
    _enqueue(isolated_store, "remediate_file", "s1")
    # Only 2 completions in the window — below the 3-sample floor.
    for _ in range(2):
        _enqueue(isolated_store, "remediate_file", "s-done", status="done",
                updated_at=_iso(_now() - timedelta(minutes=5)))

    r = isolated_store.queue_estimate("s1", "remediate", ready_workers=2)
    assert r["state"] == "insufficient_history"
    assert r["earliest_at"] is None and r["latest_at"] is None and r["confidence"] is None


# ── estimated, with real counts ────────────────────────────────────────────────

def test_estimated_with_jobs_ahead_and_confidence_band(isolated_store):
    _seed_scan(isolated_store, "s1")
    _seed_scan(isolated_store, "s-other", owner="demo")

    # 2 queued remediate_file jobs strictly ahead in claim order (created first, same priority).
    _enqueue(isolated_store, "remediate_file", "s-other")
    _enqueue(isolated_store, "remediate_file", "s-other")
    # This scan's own job — the one being asked about.
    this_job = _enqueue(isolated_store, "remediate_file", "s1")
    # A running remediate_file job elsewhere — counts as a busy worker.
    _enqueue(isolated_store, "remediate_file", "s-other", status="running")
    # 5 completed remediate_file jobs in the last 30 minutes — enough for "medium" confidence.
    for _ in range(5):
        _enqueue(isolated_store, "remediate_file", "s-other", status="done",
                updated_at=_iso(_now() - timedelta(minutes=10)))

    r = isolated_store.queue_estimate("s1", "remediate", ready_workers=3)
    assert r["available"] is True
    assert r["state"] == "estimated"
    assert r["job_type"] == "remediate_file"
    assert r["compatible_jobs_ahead"] == 2
    assert r["compatible_workers_busy"] == 1
    assert r["ready_workers"] == 3
    assert r["confidence"] == "medium"
    assert r["basis"] == "recent_remediate_throughput"
    assert r["earliest_at"] < r["latest_at"]
    assert r["estimated_at"]


def test_ten_or_more_completions_is_high_confidence(isolated_store):
    _seed_scan(isolated_store, "s1")
    _seed_scan(isolated_store, "s-other", owner="demo")
    _enqueue(isolated_store, "scan_assess", "s1")
    for _ in range(10):
        _enqueue(isolated_store, "scan_assess", "s-other", status="done",
                updated_at=_iso(_now() - timedelta(minutes=5)))

    r = isolated_store.queue_estimate("s1", "assess", ready_workers=1)
    assert r["confidence"] == "high"


def test_a_completion_outside_the_window_does_not_count(isolated_store):
    _seed_scan(isolated_store, "s1")
    _seed_scan(isolated_store, "s-other", owner="demo")
    _enqueue(isolated_store, "scan_assess", "s1")
    for _ in range(5):
        _enqueue(isolated_store, "scan_assess", "s-other", status="done",
                updated_at=_iso(_now() - timedelta(minutes=5)))
    # Well outside a 1800s (30 min) window.
    for _ in range(5):
        _enqueue(isolated_store, "scan_assess", "s-other", status="done",
                updated_at=_iso(_now() - timedelta(hours=3)))

    r = isolated_store.queue_estimate("s1", "assess", ready_workers=1, window_s=1800)
    assert r["confidence"] == "medium", "only the 5 in-window completions should count"


# ── kind isolation ──────────────────────────────────────────────────────────────

def test_a_different_kinds_queued_jobs_do_not_count_as_ahead(isolated_store):
    _seed_scan(isolated_store, "s1")
    _seed_scan(isolated_store, "s-other", owner="demo")
    # Three queued DISCOVER jobs elsewhere — must not inflate a REMEDIATE estimate.
    for _ in range(3):
        _enqueue(isolated_store, "scan_batch", "s-other")
    _enqueue(isolated_store, "remediate_file", "s1")
    for _ in range(3):
        _enqueue(isolated_store, "remediate_file", "s-other", status="done",
                updated_at=_iso(_now() - timedelta(minutes=5)))

    r = isolated_store.queue_estimate("s1", "remediate", ready_workers=2)
    assert r["compatible_jobs_ahead"] == 0


# ── claim-order respected ────────────────────────────────────────────────────────

def test_a_lower_priority_number_job_counts_as_ahead_a_higher_one_does_not(isolated_store):
    _seed_scan(isolated_store, "s1")
    _seed_scan(isolated_store, "s-other", owner="demo")
    _enqueue(isolated_store, "scan_batch", "s-other", priority=50)   # ahead: lower number
    _enqueue(isolated_store, "scan_batch", "s-other", priority=200)  # behind: higher number
    _enqueue(isolated_store, "scan_batch", "s1", priority=100)
    for _ in range(3):
        _enqueue(isolated_store, "scan_batch", "s-other", status="done",
                updated_at=_iso(_now() - timedelta(minutes=5)))

    r = isolated_store.queue_estimate("s1", "discover", ready_workers=1)
    assert r["compatible_jobs_ahead"] == 1


# ── owner scoping ───────────────────────────────────────────────────────────────

def test_a_foreign_owners_scan_finds_no_job(isolated_store):
    _seed_scan(isolated_store, "s-theirs", owner="someone-else@x")
    _enqueue(isolated_store, "remediate_file", "s-theirs")

    r = isolated_store.queue_estimate("s-theirs", "remediate", owner="demo")
    assert r == {"available": False}
