"""core.start_workers()'s background sweep thread must delegate to sweeper.run_sweep().

Found live 2026-08-27: api/sweeper.py already implemented and tested all four reconciliation
checks (reclaim_stuck_jobs, sweep_exhausted_jobs, sweep_orphaned_scans, rescue_unfinalized_scans)
via run_sweep()/Sweeper, but nothing in production ever imported the module — start_workers()'s
inline sweep loop called only reclaim_stuck_jobs() and rescue_unfinalized_scans() directly, so a
queued job past max_attempts was never dead-lettered and a 'running' scan with zero outstanding
jobs was never marked 'interrupted'. Both sat silently stuck with no error surfaced anywhere.

This test pins the wiring, not the sweep logic itself (that's test_reconciliation_sweeper.py):
start_workers()'s sweep thread must call sweeper.run_sweep(), not reimplement a subset of it.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import core
import sweeper as sweeper_module
import content_workspace_retention as retention_module


class _ImmediateExit(BaseException):
    """Not Exception — escapes the sweep loop's `except Exception` so a single run_sweep()
    call is observable without actually looping forever or sleeping in a test."""


def test_sweep_thread_calls_run_sweep_not_a_reimplemented_subset(monkeypatch):
    monkeypatch.setenv("ACP_WORKERS", "0")
    monkeypatch.setattr(core, "_worker_handles", [], raising=False)

    captured = {}

    class _FakeThread:
        def __init__(self, target=None, daemon=None, name=None):
            captured["target"] = target

        def start(self):
            pass

    monkeypatch.setattr(core.threading, "Thread", _FakeThread)

    calls = []

    def fake_run_sweep(store, *, lease_seconds=None, grace_seconds=None):
        calls.append({"lease_seconds": lease_seconds, "grace_seconds": grace_seconds})
        raise _ImmediateExit

    monkeypatch.setattr(sweeper_module, "run_sweep", fake_run_sweep)
    monkeypatch.setattr(core, "get_store", lambda: object())

    core.start_workers()
    sweep_target = captured.get("target")
    assert sweep_target is not None, "start_workers() did not hand threading.Thread a sweep target"

    with pytest.raises(_ImmediateExit):
        sweep_target()

    assert len(calls) == 1
    # 30-min lease preserved from the pre-wiring inline call — large-estate scans legitimately
    # run 10-15 min, so this must not silently drop to sweeper.py's own 600s module default.
    assert calls[0]["lease_seconds"] == 1800


def test_sweep_thread_survives_a_run_sweep_exception_and_keeps_looping(monkeypatch):
    """A single failed sweep tick (e.g. a transient DB error) must not kill the sweep thread —
    it's a daemon loop expected to run for the life of the process."""
    monkeypatch.setenv("ACP_WORKERS", "0")
    monkeypatch.setattr(core, "_worker_handles", [], raising=False)

    captured = {}

    class _FakeThread:
        def __init__(self, target=None, daemon=None, name=None):
            captured["target"] = target

        def start(self):
            pass

    monkeypatch.setattr(core.threading, "Thread", _FakeThread)

    ticks = {"n": 0}

    def flaky_run_sweep(store, *, lease_seconds=None, grace_seconds=None):
        ticks["n"] += 1
        if ticks["n"] == 1:
            raise RuntimeError("transient DB error")
        raise _ImmediateExit   # second tick: stop the test, not the loop

    monkeypatch.setattr(sweeper_module, "run_sweep", flaky_run_sweep)
    monkeypatch.setattr(core, "get_store", lambda: object())

    # time.sleep(60) sits between ticks in the real loop — no-op it so the test doesn't wait.
    import time as real_time
    monkeypatch.setattr(real_time, "sleep", lambda *_: None)

    core.start_workers()
    sweep_target = captured["target"]

    with pytest.raises(_ImmediateExit):
        sweep_target()

    assert ticks["n"] == 2   # the RuntimeError on tick 1 was caught, not fatal


def test_sweep_thread_also_calls_the_content_workspace_retention_sweep(monkeypatch):
    """ADR 0044 / PRD §28: content_workspace_retention.py exists and is fully tested
    (test_content_workspace_retention.py) the same way sweeper.py once was before the fix this
    file's own docstring describes — pin the wiring here too, so it can't sit built and unused
    the same way."""
    monkeypatch.setenv("ACP_WORKERS", "0")
    monkeypatch.setattr(core, "_worker_handles", [], raising=False)

    captured = {}

    class _FakeThread:
        def __init__(self, target=None, daemon=None, name=None):
            captured["target"] = target

        def start(self):
            pass

    monkeypatch.setattr(core.threading, "Thread", _FakeThread)

    calls = []
    monkeypatch.setattr(sweeper_module, "run_sweep", lambda store, **kw: None)

    def fake_retention_sweep(store, **kw):
        calls.append(store)
        raise _ImmediateExit

    monkeypatch.setattr(retention_module, "run_content_workspace_retention_sweep",
                        fake_retention_sweep)
    monkeypatch.setattr(core, "get_store", lambda: object())

    core.start_workers()
    sweep_target = captured.get("target")
    assert sweep_target is not None

    with pytest.raises(_ImmediateExit):
        sweep_target()

    assert len(calls) == 1
