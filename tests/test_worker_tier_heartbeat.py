"""Worker-tier heartbeat (#113 follow-up — the "no workers running" live regression).

In the split topology the API container runs ACP_WORKERS=0 by design, but its scan-start
guard reported that local pool to the client, which refused a perfectly manned queue. The
fix: worker_main beats a timestamp into the shared store; store.worker_tier_alive() checks
freshness; scan routes report it; the client guard accepts either an in-process pool OR a
live worker tier. Liveness is a real heartbeat, never a config flag — a dead worker goes
stale and the guard correctly refuses again.

The heartbeat also carries the worker container's own `core.WORKERS` pool size — a JSON
envelope `{"at": iso, "pool_size": int}` — so "ACP-ready worker slots" can be reported
honestly instead of the API tier's own (0-in-split-topology) pool. That has to round-trip
across a rolling deploy: an OLD worker_main (bare-ISO writer) talking to NEW store.py, or a
NEW worker_main talking to OLD store.py mid-rollout, must both keep working.
"""
from __future__ import annotations

import json
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


def _stamp(delta_s: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=delta_s)).isoformat()


def _envelope(delta_s: float, pool_size: int | None = 12) -> str:
    body = {"at": _stamp(delta_s)}
    if pool_size is not None:
        body["pool_size"] = pool_size
    return json.dumps(body)


def _wait_until(predicate, timeout=5.0, interval=0.01):
    """Wait for the thing under test to actually happen, rather than sleeping a guess.

    WHY THIS REPLACED A FIXED SLEEP. `worker_main.run` writes its first heartbeat INSIDE
    `while not _stop.is_set()`, and reaches that loop only after `import core` pulls in
    apscheduler, the store and the scheduler stack. The old `time.sleep(0.15)` was the entire
    margin for all of that: when `_stop.set()` won the race the loop body never ran, no beat was
    ever written, and `worker_tier_alive()` was correctly False. That is how this test failed CI
    on 2026-09-05 during an unrelated frontend-only PR (#1412) while passing everywhere else.

    A longer fixed sleep would be the same race with a bigger constant. The timeout here is a
    ceiling on failure, not a duration the happy path pays: a beat that lands in 20 ms is waited
    on for 20 ms.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def test_alive_when_beat_is_fresh(isolated_store):
    s = isolated_store
    s.set_setting("worker_tier_heartbeat", _stamp(5))
    assert s.worker_tier_alive() is True


def test_stale_beat_means_dead(isolated_store):
    # A crashed/deleted worker container must not keep passing the guard forever.
    s = isolated_store
    s.set_setting("worker_tier_heartbeat", _stamp(600))
    assert s.worker_tier_alive() is False
    assert s.worker_tier_alive(window_s=3600) is True   # window is the caller's call


def test_missing_or_garbage_beat_means_dead(isolated_store):
    s = isolated_store
    assert s.worker_tier_alive() is False               # never beaten (pre-split deploys)
    s.set_setting("worker_tier_heartbeat", "not-a-timestamp")
    assert s.worker_tier_alive() is False               # corrupt value fails closed


def test_naive_timestamp_treated_as_utc(isolated_store):
    # Defensive: if a beat ever lands without tzinfo, treat it as UTC instead of raising.
    s = isolated_store
    s.set_setting("worker_tier_heartbeat", datetime.utcnow().isoformat())
    assert s.worker_tier_alive() is True


def test_json_envelope_heartbeat_round_trips_pool_size(isolated_store):
    """The new format: worker_tier_status() unwraps the JSON envelope and reports pool_size,
    and worker_tier_alive() still reads the freshness out of it correctly."""
    s = isolated_store
    s.set_setting("worker_tier_heartbeat", _envelope(5, pool_size=12))
    status = s.worker_tier_status()
    assert status["alive"] is True
    assert status["pool_size"] == 12
    assert status["ever_seen"] is True
    assert 4 <= status["age_s"] <= 6
    assert s.worker_tier_alive() is True


def test_role_heartbeats_report_stage_capacity_independently(isolated_store):
    from worker_stage_capacity import worker_role_alive
    isolated_store.set_setting("worker_tier_heartbeat:assess", _envelope(5, pool_size=3))
    isolated_store.set_setting("worker_tier_heartbeat:remediate", _envelope(600, pool_size=2))
    assert worker_role_alive(isolated_store, "assess") is True
    assert worker_role_alive(isolated_store, "remediate") is False


def test_role_heartbeat_falls_back_to_global_during_rolling_deploy(isolated_store):
    from worker_stage_capacity import worker_role_alive
    isolated_store.set_setting("worker_tier_heartbeat", _envelope(5, pool_size=2))
    assert worker_role_alive(isolated_store, "assess") is True
    assert worker_role_alive(isolated_store, "remediate") is True


def test_old_bare_timestamp_heartbeat_still_works_with_pool_size_none(isolated_store):
    """Rolling-deploy compatibility: an old worker_main container (bare-ISO writer) hasn't
    redeployed yet, or the value predates this change. Must read as alive, with pool_size
    None rather than a crash or a false 'not alive'."""
    s = isolated_store
    s.set_setting("worker_tier_heartbeat", _stamp(5))
    status = s.worker_tier_status()
    assert status["alive"] is True
    assert status["pool_size"] is None
    assert s.worker_tier_alive() is True


def test_json_envelope_missing_pool_size_reads_as_none(isolated_store):
    # A JSON envelope that never carried pool_size (partial rollout, older new-format writer)
    # must not crash and must not fabricate a number.
    s = isolated_store
    s.set_setting("worker_tier_heartbeat", _envelope(5, pool_size=None))
    status = s.worker_tier_status()
    assert status["alive"] is True
    assert status["pool_size"] is None


def test_garbage_heartbeat_still_handled_the_same_way_with_json_parsing_added(isolated_store):
    """The pre-existing garbage-timestamp branch (worker_tier_status's 'unparseable: ...'
    report) must not regress now that JSON parsing sits in front of it — garbage is neither
    valid JSON nor a valid ISO timestamp, so it falls through both and is reported, not
    swallowed."""
    s = isolated_store
    s.set_setting("worker_tier_heartbeat", "not-a-timestamp")
    status = s.worker_tier_status()
    assert status["alive"] is False
    assert status["pool_size"] is None
    assert "unparseable" in status["heartbeat_at"]
    assert s.worker_tier_alive() is False


def test_worker_main_loop_beats(monkeypatch, isolated_store):
    # The real loop writes the heartbeat (first beat immediately on entry), now as a JSON
    # envelope carrying the worker container's own pool size.
    import core
    import worker_main
    monkeypatch.setattr(core, "get_store", lambda: isolated_store)
    monkeypatch.setattr(core, "reload_scheduler", lambda: None)
    monkeypatch.setattr(core, "start_scheduler", lambda: None)
    monkeypatch.setattr(core, "start_workers", lambda: 2)
    monkeypatch.setattr(core, "stop_workers", lambda: None)
    monkeypatch.setattr(core, "stop_scheduler", lambda: None)
    monkeypatch.setattr(core, "WORKERS", 12)

    worker_main._stop.clear()
    t = threading.Thread(target=lambda: worker_main.run(poll_seconds=0.02, _install_signals=False))
    t.start()
    # Wait for the beat this test is about, not for a fixed interval — see _wait_until.
    beat_written = _wait_until(lambda: bool(isolated_store.get_setting("worker_tier_heartbeat")))
    worker_main._stop.set()
    t.join(timeout=2)
    # Asserted separately so a timeout says "no beat in 5s" rather than surfacing as a confusing
    # `alive is False` further down.
    assert beat_written, "worker_main.run wrote no heartbeat within the timeout"
    assert not t.is_alive()
    assert isolated_store.worker_tier_alive() is True
    assert isolated_store.worker_tier_status()["pool_size"] == 12
    from worker_stage_capacity import worker_role_alive
    assert worker_role_alive(isolated_store, "mixed") is True


def test_routes_report_tier_and_client_guard_accepts_it():
    # The wiring that actually fixes the live failure: routes expose worker_tier_alive and
    # both client guards treat a live tier as "manned" (workers || worker_tier_alive).
    root = Path(__file__).resolve().parent.parent
    scans = (root / "api" / "routes" / "scans.py").read_text()
    assert scans.count("worker_tier_alive") >= 3        # scan-start, remediate, deferred assess
    jobs = (root / "api" / "routes" / "system.py").read_text()
    assert "worker_tier_alive" in jobs                  # Monitor sees the tier too

    app = (root / "frontend" / "src" / "App.jsx").read_text()
    assert "!workers && !worker_tier_alive" in app      # scan guard no longer refuses the split
    rem = (root / "frontend" / "src" / "Remediate.jsx").read_text()
    assert "!r.workers && !r.worker_tier_alive" in rem  # remediate guard likewise
