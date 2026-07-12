"""Stopping a wedged scan — found LIVE 2026-07-11.

A deploy swapped the container mid-scan: the workers died, the scan_runs row stayed
'running' forever, the UI reconnected to it eternally ("scanning…") and there was NO way
to stop it. Two fixes, both here:

  * cancel_scan  — an owner can stop their in-flight scan: outstanding jobs are killed,
                   the run closes as 'cancelled', already-analysed files keep their records.
  * active_scan  — SELF-HEALS: a 'running' scan with zero outstanding jobs past a grace
                   period is dead by definition (fan-out scans always have job rows) and is
                   marked 'interrupted' instead of wedging the UI. A scan whose jobs are
                   merely orphaned (rows still queued/running) is left alone — the stuck-job
                   sweeper reclaims those and the scan genuinely resumes.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


def _iso(dt):
    return dt.isoformat()


def _running_scan(store, sid, owner="a@x.io", started_ago_s=0, jobs=0):
    started = _iso(datetime.now(timezone.utc) - timedelta(seconds=started_ago_s))
    store.init_scan_run(sid, "drive", total=5, started_at=started,
                        rubric_name="r", rubric_hash="h", owner=owner)
    for i in range(jobs):
        store.enqueue_job("scan_file", {"scan_id": sid, "file": f"f{i}.docx"}, scan_id=sid)
    return sid


# ── cancel_scan ─────────────────────────────────────────────────────────────────

def test_cancel_kills_jobs_and_closes_the_run(isolated_store):
    s = isolated_store
    _running_scan(s, "scanA", jobs=3)
    assert s.cancel_scan("scanA", owner="a@x.io") is True
    run = s.get_scan("scanA")["run"]
    assert run["status"] == "cancelled" and run["completed_at"]
    # every outstanding job is dead — no worker will pick the scan back up
    assert s.job_stats().get("queued", 0) == 0
    assert s.job_stats().get("dead", 0) == 3
    # and the UI no longer sees an active scan
    assert s.active_scan(owner="a@x.io") is None


def test_cancel_is_owner_scoped_and_only_for_running_scans(isolated_store):
    s = isolated_store
    _running_scan(s, "scanB", owner="a@x.io", jobs=1)
    assert s.cancel_scan("scanB", owner="intruder@x.io") is False   # not yours
    assert s.cancel_scan("nope", owner="a@x.io") is False           # doesn't exist
    assert s.cancel_scan("scanB", owner="a@x.io") is True
    assert s.cancel_scan("scanB", owner="a@x.io") is False          # already closed


# ── active_scan self-heal ───────────────────────────────────────────────────────

def test_dead_scan_past_grace_is_marked_interrupted(isolated_store):
    s = isolated_store
    # 'running' for 20 min with ZERO job rows — the exact live wedge (jobs finished/died,
    # finalize lost in a deploy).
    _running_scan(s, "wedged", started_ago_s=1200, jobs=0)
    assert s.active_scan(owner="a@x.io") is None
    assert s.get_scan("wedged")["run"]["status"] == "interrupted"


def test_young_scan_without_jobs_is_left_alone(isolated_store):
    s = isolated_store
    # Discover may not have enqueued per-file jobs yet — never heal inside the grace window.
    _running_scan(s, "fresh", started_ago_s=5, jobs=0)
    active = s.active_scan(owner="a@x.io")
    assert active and active["id"] == "fresh"
    assert s.get_scan("fresh")["run"]["status"] == "running"


def test_scan_with_orphaned_but_reclaimable_jobs_is_left_alone(isolated_store):
    s = isolated_store
    # Old scan, but its jobs still exist (queued) — the sweeper's territory, not ours.
    _running_scan(s, "resumable", started_ago_s=1200, jobs=2)
    active = s.active_scan(owner="a@x.io")
    assert active and active["id"] == "resumable"
    assert s.get_scan("resumable")["run"]["status"] == "running"
