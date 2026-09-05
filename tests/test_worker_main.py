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


def _wait_until(predicate, timeout=5.0, interval=0.01):
    """Wait for a condition instead of sleeping a fixed guess. See the fuller note on the copy in
    tests/test_worker_tier_heartbeat.py — same race, same reason, and this file's 0.1s margin was
    the tighter of the two."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


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
    # Wait for the boot sequence this test asserts on, rather than sleeping a guess. The same race
    # as tests/test_worker_tier_heartbeat.py's (see _wait_until there): `import core` happens on
    # the thread, and if `_stop.set()` wins, `calls` is still short and the boot-order assertion
    # below fails for a reason that has nothing to do with boot order.
    booted = _wait_until(lambda: "start_workers" in calls)
    worker_main._stop.set()          # simulate SIGTERM
    t.join(timeout=2)
    assert booted, "worker_main.run did not reach start_workers within the timeout"
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


def test_the_acp_workers_default_is_set_before_core_is_imported():
    """Regression for the live bug found 2026-08-29: core.py computes its module-level `WORKERS`
    int from os.environ AT IMPORT TIME, and core.start_workers() spawns off that already-latched
    value — it never re-reads the environment. `run()` used to `import core` first and only set
    the ACP_WORKERS default afterward, so on a genuinely fresh worker container (no ACP_WORKERS in
    its env) the default write landed too late: `core.WORKERS` was already 0. The container then
    ran its heartbeat (so Monitor showed it "online") while spawning zero worker threads — nothing
    ever claimed a queued job.

    `test_defaults_workers_when_unset` above can't catch this: it mocks `core.start_workers`
    entirely, so it only proves the env var is set by the time SOMETHING calls start_workers, not
    that the REAL core.py (imported fresh, no ACP_WORKERS set) would have honored it. And a
    behavioural re-import test is unreliable in-process — `core` is almost certainly already
    cached in sys.modules from another test file's own `import core` by the time this one runs, so
    a second `import core` here would be a no-op regardless of ordering. A source-order assertion
    is the one check that actually pins the fix, the same reasoning frontend/src's App.jsx
    source-shape tests use for logic that is impractical to exercise by literally re-running it.
    """
    import inspect
    import re
    import worker_main
    src = inspect.getsource(worker_main.run)
    default_idx = src.index('os.environ["ACP_WORKERS"] = "12"')
    # Line-anchored so this matches only the real `import core` statement, not this file's own
    # explanatory comment mentioning "import core" in prose (which sits earlier in the text).
    m = re.search(r"^\s*import core\s*$", src, re.MULTILINE)
    assert m, "run() should still contain a top-level `import core` statement"
    assert default_idx < m.start(), (
        "the ACP_WORKERS default must be written to os.environ BEFORE `import core` runs — "
        "core.py reads it into a module-level int at import time and never looks again"
    )


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


def test_process_registry_records_lifecycle_and_busy_slots(monkeypatch):
    import core
    rows = []

    class Store:
        def set_setting(self, *_args): pass
        def upsert_worker_instance(self, worker_id, **fields):
            rows.append({"worker_id": worker_id, **fields})

    class Worker:
        job_types = ("scan_assess",)
        active_job_id = "opaque-job-id"

    monkeypatch.setattr(core, "get_store", lambda: Store())
    monkeypatch.setattr(core, "reload_scheduler", lambda: None)
    monkeypatch.setattr(core, "start_scheduler", lambda: None)
    monkeypatch.setattr(core, "start_workers", lambda: 2)
    monkeypatch.setattr(core, "stop_workers", lambda: setattr(core, "WORKERS", 0))
    monkeypatch.setattr(core, "stop_scheduler", lambda: None)
    monkeypatch.setattr(core, "WORKERS", 2)
    monkeypatch.setattr(core, "_worker_handles", [(Worker(), object())])
    monkeypatch.setattr(core, "worker_process_instance_id", lambda role: f"{role}:replica-1:proc-1")
    monkeypatch.setattr(core, "_replica_id", lambda: "replica-1")
    worker_main._stop.set()
    worker_main.run(poll_seconds=0.01, _install_signals=False)

    assert [row["state"] for row in rows] == ["starting", "ready", "draining", "offline"]
    assert rows[1]["worker_id"] == "mixed:replica-1:proc-1"
    assert rows[1]["concurrency_limit"] == 2
    assert rows[1]["active_job_count"] == 1
    assert rows[1]["available_slots"] == 1
    assert rows[1]["last_claimed_job_id"] == "opaque-job-id"
