"""Standalone worker entrypoint (#113 prep).

worker_main.run() must boot the pool + scheduler, block until stopped, then drain — reusing
core.start_workers/stop_workers, so the split is a deploy-config change (a second container
running `python worker_main.py`), not a code fork. This tests the lifecycle in isolation with
core mocked, so no real threads/DB are needed.
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import worker_main  # noqa: E402


def test_run_boots_then_drains(monkeypatch):
    import core
    calls = []
    monkeypatch.setattr(core, "get_store", lambda: calls.append("store"))
    monkeypatch.setattr(core, "reload_scheduler", lambda: calls.append("reload"))
    monkeypatch.setattr(core, "start_scheduler", lambda: calls.append("start_sched"))
    monkeypatch.setattr(core, "start_workers", lambda: calls.append("start_workers") or 4)
    monkeypatch.setattr(core, "stop_workers", lambda: calls.append("stop_workers"))
    monkeypatch.setattr(core, "stop_scheduler", lambda: calls.append("stop_sched"))

    worker_main._stop.clear()
    t = threading.Thread(target=lambda: worker_main.run(poll_seconds=0.02, _install_signals=False))
    t.start()
    time.sleep(0.1)
    worker_main._stop.set()          # simulate SIGTERM
    t.join(timeout=2)
    assert not t.is_alive()

    # boot order, then a clean drain
    assert calls[:4] == ["store", "reload", "start_sched", "start_workers"]
    assert "stop_workers" in calls and "stop_sched" in calls
    # drain came AFTER boot
    assert calls.index("stop_workers") > calls.index("start_workers")


def test_defaults_workers_when_unset(monkeypatch):
    import os
    monkeypatch.delenv("ACP_WORKERS", raising=False)
    import core
    monkeypatch.setattr(core, "get_store", lambda: None)
    monkeypatch.setattr(core, "reload_scheduler", lambda: None)
    monkeypatch.setattr(core, "start_scheduler", lambda: None)
    seen = {}
    monkeypatch.setattr(core, "start_workers", lambda: seen.setdefault("workers", os.environ.get("ACP_WORKERS")) or 4)
    monkeypatch.setattr(core, "stop_workers", lambda: None)
    monkeypatch.setattr(core, "stop_scheduler", lambda: None)
    worker_main._stop.set()          # exit the loop immediately
    worker_main.run(poll_seconds=0.01, _install_signals=False)
    assert seen["workers"] == "12"   # a worker container defaults to 12 (safe range for 2vCPU)


def test_drain_error_still_exits(monkeypatch):
    import core
    monkeypatch.setattr(core, "get_store", lambda: None)
    monkeypatch.setattr(core, "reload_scheduler", lambda: None)
    monkeypatch.setattr(core, "start_scheduler", lambda: None)
    monkeypatch.setattr(core, "start_workers", lambda: 1)
    monkeypatch.setattr(core, "stop_workers", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(core, "stop_scheduler", lambda: None)
    worker_main._stop.set()
    worker_main.run(poll_seconds=0.01, _install_signals=False)   # must not raise
