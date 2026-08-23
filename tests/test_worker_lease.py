"""The job heartbeat proves liveness, not progress — so its lease extensions are bounded.

`store.reclaim_stuck_jobs` only reclaims leases that have gone STALE. The heartbeat thread runs
on a timer and never asks the handler whether anything is happening, so a worker whose handler is
WEDGED (blocked socket, spin, deadlock) kept extending its own lease forever and could never be
reclaimed. The 30-minute lease covers a worker that dies; it did nothing for one that hangs —
which is the failure that leaves a queue reading "N active · 0 waiting" and draining nothing.

These pin the ceiling that makes a hung job reachable, and the escape hatch that restores the old
extend-forever behaviour.
"""
from __future__ import annotations
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))


@pytest.fixture()
def store(monkeypatch):
    import store as store_mod
    tmp = Path(tempfile.mkdtemp()) / "lease-test.db"
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", tmp)
    return store_mod.Store()


# ── the ceiling's own configuration ──────────────────────────────────────────
def test_ceiling_defaults_to_an_hour(monkeypatch):
    import worker
    monkeypatch.delenv("ACP_JOB_MAX_LEASE_S", raising=False)
    assert worker.max_unverified_lease_s() == 3600


def test_ceiling_is_configurable(monkeypatch):
    import worker
    monkeypatch.setenv("ACP_JOB_MAX_LEASE_S", "120")
    assert worker.max_unverified_lease_s() == 120


def test_zero_disables_the_ceiling(monkeypatch):
    # The escape hatch: extend forever, exactly as before this change.
    import worker
    monkeypatch.setenv("ACP_JOB_MAX_LEASE_S", "0")
    assert worker.max_unverified_lease_s() == 0


def test_a_junk_ceiling_falls_back_rather_than_crashing_the_worker(monkeypatch):
    # A typo in an env var must not take the worker pool down on boot.
    import worker
    monkeypatch.setenv("ACP_JOB_MAX_LEASE_S", "not-a-number")
    assert worker.max_unverified_lease_s() == 3600
    monkeypatch.setenv("ACP_JOB_MAX_LEASE_S", "-5")
    assert worker.max_unverified_lease_s() == 0      # clamped, never negative


# ── the behaviour that matters ───────────────────────────────────────────────
def _blocking_handler(release: threading.Event):
    """A handler that hangs until the test lets it go — a wedged worker, exactly."""
    def _fn(payload, job):
        release.wait(5)
    return _fn


def test_a_wedged_job_stops_having_its_lease_extended(store, monkeypatch, capsys):
    import worker
    monkeypatch.setattr(worker, "HEARTBEAT_INTERVAL_S", 0.01)
    # A ceiling smaller than one heartbeat interval: the first beat is already past it.
    monkeypatch.setattr(worker, "max_unverified_lease_s", lambda: 0.001)

    touches = []
    monkeypatch.setattr(store, "touch_job", lambda jid: touches.append(jid))

    release = threading.Event()
    worker.HANDLERS["wedged"] = _blocking_handler(release)
    try:
        store.enqueue_job("wedged", {}, scan_id="s1")
        w = worker.JobWorker(store, worker_id="w1")
        t = threading.Thread(target=w.run_once, daemon=True)
        t.start()
        time.sleep(0.2)          # several heartbeat intervals
        # The lease was never extended: the job is now reclaimable by the sweeper.
        assert touches == []
        assert "no longer extending it" in capsys.readouterr().out
    finally:
        release.set()
        t.join(timeout=5)
        worker.HANDLERS.pop("wedged", None)


def test_a_slow_but_healthy_job_still_gets_its_lease_extended(store, monkeypatch):
    # The behaviour the ceiling must NOT break: a long-running job below the ceiling keeps its
    # lease, so the sweeper does not reclaim work that is genuinely in progress.
    import worker
    monkeypatch.setattr(worker, "HEARTBEAT_INTERVAL_S", 0.01)
    monkeypatch.setattr(worker, "max_unverified_lease_s", lambda: 3600)

    touches = []
    monkeypatch.setattr(store, "touch_job", lambda jid: touches.append(jid))

    release = threading.Event()
    worker.HANDLERS["slow"] = _blocking_handler(release)
    try:
        jid = store.enqueue_job("slow", {}, scan_id="s1")
        w = worker.JobWorker(store, worker_id="w1")
        t = threading.Thread(target=w.run_once, daemon=True)
        t.start()
        time.sleep(0.2)
        assert touches, "a healthy job below the ceiling must keep its lease"
        assert set(touches) == {jid}
    finally:
        release.set()
        t.join(timeout=5)
        worker.HANDLERS.pop("slow", None)


def test_the_ceiling_makes_a_wedged_job_reclaimable_end_to_end(store, monkeypatch):
    """The point of the whole change: sweeper + stopped heartbeat = the job comes back."""
    import worker
    monkeypatch.setattr(worker, "HEARTBEAT_INTERVAL_S", 0.01)
    monkeypatch.setattr(worker, "max_unverified_lease_s", lambda: 0.001)

    release = threading.Event()
    worker.HANDLERS["wedged2"] = _blocking_handler(release)
    try:
        jid = store.enqueue_job("wedged2", {}, scan_id="s1")
        w = worker.JobWorker(store, worker_id="w1")
        t = threading.Thread(target=w.run_once, daemon=True)
        t.start()
        time.sleep(0.2)
        assert store.get_job(jid)["status"] == "running"     # still held by the wedged worker
        # The sweeper can now see it, because nothing refreshed locked_at.
        assert store.reclaim_stuck_jobs(lease_seconds=0) == 1
        assert store.get_job(jid)["status"] == "queued"      # back in the queue, drainable
    finally:
        release.set()
        t.join(timeout=5)
        worker.HANDLERS.pop("wedged2", None)
