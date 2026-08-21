"""The default (session-scoped) scan path must prove it is still alive during a long,
silent crawl — not just at the start and the end.

Live incident (2026-08-21): a scan's in-process thread died mid-crawl (most likely a
redeploy recycling its replica) and the job sat at phase="queued" forever with no error.
The fix is core.get_job_state's staleness check (test_job_state_cross_replica.py), but that
check is only trustworthy if something keeps `updated_at` moving WHILE the scan is doing
real, silent work — otherwise a legitimately slow crawl of a large estate would falsely read
as dead the moment it out-lived the staleness threshold.

These tests pin the heartbeat companion thread in routes/scans.py's work(): it has to tick
during a long _scan_discover call (proving liveness independent of scan progress), and it has
to stop once work() finishes, one way or another — success, exception, or early return.
"""
from __future__ import annotations
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))


@pytest.fixture()
def client(monkeypatch, isolated_store):
    import core
    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "_JOB_HEARTBEAT_SECONDS", 0.03)
    monkeypatch.setattr(core, "_JOB_STALE_SECONDS", 9999)   # not what this file is testing
    from fastapi.testclient import TestClient
    from app import app
    return TestClient(app), core


def _wait_until(predicate, timeout=3.0, interval=0.02):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def test_the_heartbeat_ticks_during_a_long_silent_discover_call(client, monkeypatch):
    """The load-bearing case. _scan_discover makes exactly one update_job call, at the very
    end — during the call itself, updated_at must still move, or a large estate's genuine crawl
    time would be indistinguishable from a dead replica."""
    c, core = client
    started = threading.Event()
    finish = threading.Event()

    def slow_discover(payload, job):
        started.set()
        finish.wait(timeout=2)             # held open so the test can observe heartbeats

    import handlers
    monkeypatch.setattr(handlers, "_defer_analysis_to_assess", lambda: True)
    monkeypatch.setattr(handlers, "_scan_discover", slow_discover)

    r = c.post("/scans?source=drive")
    assert r.status_code == 200
    job_id = r.json()["job_id"]

    assert _wait_until(started.is_set), "the scan thread never started"

    first = core.get_job_state(job_id)["updated_at"]
    # Two heartbeat intervals (0.03s each) is enough for at least one extra tick; give it margin.
    assert _wait_until(lambda: core.get_job_state(job_id)["updated_at"] != first, timeout=1.0), (
        "updated_at never moved while the scan was silently working — a slow-but-alive scan "
        "would be indistinguishable from a dead replica under the staleness check"
    )
    # The job must still read as unfinished and un-erred while the heartbeat is the only signal.
    mid = core.get_job_state(job_id)
    assert mid["done"] is False and mid.get("error") is None

    finish.set()
    assert _wait_until(lambda: core.get_job_state(job_id)["done"] is True), "the job never completed"


def test_the_heartbeat_stops_once_the_job_completes(client, monkeypatch):
    """A heartbeat that outlives the job it was proving liveness for is a leaked thread, and one
    that keeps writing after done=True would let a late tick paper over a genuinely stuck retry
    that reused the same job_id (it can't, ids are uuids, but the invariant should hold anyway)."""
    c, core = client
    import handlers
    monkeypatch.setattr(handlers, "_defer_analysis_to_assess", lambda: True)
    monkeypatch.setattr(handlers, "_scan_discover", lambda payload, job: None)  # returns immediately

    r = c.post("/scans?source=drive")
    job_id = r.json()["job_id"]

    assert _wait_until(lambda: core.get_job_state(job_id)["done"] is True)
    after_done = core.get_job_state(job_id)["updated_at"]
    # If the heartbeat were still running it would tick again well within this window.
    time.sleep(0.15)
    assert core.get_job_state(job_id)["updated_at"] == after_done, (
        "updated_at kept changing after done=True — the heartbeat thread did not stop"
    )


def test_the_heartbeat_stops_when_the_scan_raises(client, monkeypatch):
    c, core = client
    import handlers
    monkeypatch.setattr(handlers, "_defer_analysis_to_assess", lambda: True)

    def boom(payload, job):
        raise RuntimeError("simulated scan failure")
    monkeypatch.setattr(handlers, "_scan_discover", boom)

    r = c.post("/scans?source=drive")
    job_id = r.json()["job_id"]

    assert _wait_until(lambda: core.get_job_state(job_id)["done"] is True)
    got = core.get_job_state(job_id)
    assert got["phase"] == "error" and "simulated scan failure" in got["error"]
    after_done = got["updated_at"]
    time.sleep(0.15)
    assert core.get_job_state(job_id)["updated_at"] == after_done
