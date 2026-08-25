"""Reconciliation sweeper (ADR 0004 step 5).

Periodic process that corrects inconsistencies the job queue can accumulate when
workers crash, are interrupted by deploys, or fail to finalise their scan runs:

  1. Expired leases   — jobs stuck in 'running' past their lease window are requeued
                        so a new worker can claim them.
  2. Exhausted jobs   — queued jobs that already hit max_attempts are dead-lettered.
                        reclaim_stuck_jobs() requeues without checking attempts; this
                        pass catches the stragglers.
  3. Orphaned scans   — scan_runs still 'running' with zero outstanding jobs past the
                        grace window are marked 'interrupted'.
  4. Unfinalized scans — 'running' scans where every file_record is persisted but
                         scan_finalize was never enqueued get a fresh finalize job.

Typical use: call run_sweep(store) once per tick from a background thread or cron.
The function is idempotent and safe to call concurrently — each sub-sweep uses
row-level predicates that are safe under concurrent writers.

Environment variables:
  ACP_SWEEP_LEASE_S    — lease window for reclaim_stuck_jobs (default 600)
  ACP_SWEEP_GRACE_S    — orphan grace window for sweep_orphaned_scans (default 600)
"""
from __future__ import annotations
import os
import time


def _int_env(name: str, default: int) -> int:
    try:
        return max(0, int(os.environ.get(name, str(default)) or str(default)))
    except ValueError:
        return default


def run_sweep(store, *, lease_seconds: int | None = None,
              grace_seconds: int | None = None) -> dict[str, int]:
    """Run all reconciliation checks once and return per-check counts.

    Parameters override the corresponding env vars when provided.

    Returns a dict with keys:
      reclaimed          — jobs moved from 'running' → 'queued' (expired lease)
      exhausted_dead     — jobs moved from 'queued' → 'dead' (attempts >= max)
      scans_interrupted  — scan_runs moved from 'running' → 'interrupted'
      scans_rescued      — scan_runs re-enqueued with a fresh scan_finalize job
    """
    lease_s = lease_seconds if lease_seconds is not None else _int_env("ACP_SWEEP_LEASE_S", 600)
    grace_s = grace_seconds if grace_seconds is not None else _int_env("ACP_SWEEP_GRACE_S", 600)

    reclaimed = store.reclaim_stuck_jobs(lease_seconds=lease_s)
    exhausted = store.sweep_exhausted_jobs()
    interrupted = store.sweep_orphaned_scans(grace_seconds=grace_s)
    rescued = store.rescue_unfinalized_scans()

    result = {
        "reclaimed": reclaimed,
        "exhausted_dead": exhausted,
        "scans_interrupted": interrupted,
        "scans_rescued": rescued,
    }
    total = sum(result.values())
    if total:
        parts = ", ".join(f"{k}={v}" for k, v in result.items() if v)
        print(f"[sweeper] tick: {parts}", flush=True)
    return result


class Sweeper:
    """Background thread that calls run_sweep(store) every `interval_s` seconds.

    Usage::

        sweeper = Sweeper(store, interval_s=60)
        sweeper.start()
        ...
        sweeper.stop()

    The thread is a daemon so it does not prevent process exit.
    """

    def __init__(self, store, *, interval_s: int = 60,
                 lease_seconds: int | None = None, grace_seconds: int | None = None):
        self.store = store
        self.interval_s = interval_s
        self.lease_seconds = lease_seconds
        self.grace_seconds = grace_seconds
        self._stop = False
        self._thread = None

    def start(self) -> None:
        import threading
        self._stop = False
        self._thread = threading.Thread(target=self._loop, daemon=True, name="sweeper")
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop = True
        if self._thread:
            self._thread.join(timeout=timeout)

    def _loop(self) -> None:
        while not self._stop:
            try:
                run_sweep(self.store,
                          lease_seconds=self.lease_seconds,
                          grace_seconds=self.grace_seconds)
            except Exception as e:
                print(f"[sweeper] error: {e}", flush=True)
            # Sleep in short increments so stop() is responsive
            for _ in range(self.interval_s * 2):
                if self._stop:
                    return
                time.sleep(0.5)
