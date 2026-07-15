"""Worker-tier heartbeat (#113 follow-up — the "no workers running" live regression).

In the split topology the API container runs ACP_WORKERS=0 by design, but its scan-start
guard reported that local pool to the client, which refused a perfectly manned queue. The
fix: worker_main beats a timestamp into the shared store; store.worker_tier_alive() checks
freshness; scan routes report it; the client guard accepts either an in-process pool OR a
live worker tier. Liveness is a real heartbeat, never a config flag — a dead worker goes
stale and the guard correctly refuses again.
"""
from __future__ import annotations

import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


def _stamp(delta_s: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=delta_s)).isoformat()


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


def test_worker_main_loop_beats(monkeypatch, isolated_store):
    # The real loop writes the heartbeat (first beat immediately on entry).
    import core
    import worker_main
    monkeypatch.setattr(core, "get_store", lambda: isolated_store)
    monkeypatch.setattr(core, "reload_scheduler", lambda: None)
    monkeypatch.setattr(core, "start_scheduler", lambda: None)
    monkeypatch.setattr(core, "start_workers", lambda: 2)
    monkeypatch.setattr(core, "stop_workers", lambda: None)
    monkeypatch.setattr(core, "stop_scheduler", lambda: None)

    worker_main._stop.clear()
    t = threading.Thread(target=lambda: worker_main.run(poll_seconds=0.02, _install_signals=False))
    t.start()
    time.sleep(0.15)
    worker_main._stop.set()
    t.join(timeout=2)
    assert not t.is_alive()
    assert isolated_store.worker_tier_alive() is True


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
