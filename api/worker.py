"""Durable job-queue worker (ADR 0004).

A worker claims the next eligible job from the `jobs` table, dispatches it to a
registered handler, and marks it done — or, on failure, requeues it with capped,
jittered exponential backoff until `max_attempts`, then dead-letters it.

Handlers register themselves by job type:

    from worker import handler

    @handler("scan_file")
    def _scan_file(payload, job):
        ...                      # raise to retry; raise FatalJobError to dead-letter now

This module is intentionally infrastructure-only: it does not yet replace
`scanner.run_scan` (see ADR 0004 — that integration carries a Drive-token-at-rest
design question and is the next step). It can be exercised today via the store
queue methods and the tests in tests/test_jobs.py.
"""
from __future__ import annotations
import random
import threading
import time
import uuid

# Registry: job type -> handler(payload: dict, job: dict) -> None
HANDLERS: dict[str, callable] = {}


class FatalJobError(Exception):
    """Raise from a handler to dead-letter the job immediately (no retry)."""


def handler(job_type: str):
    """Decorator registering a handler for a job type."""
    def _wrap(fn):
        HANDLERS[job_type] = fn
        return fn
    return _wrap


def _backoff_seconds(attempts: int, base: float = 2.0, cap: float = 300.0) -> float:
    """Capped exponential backoff with full jitter."""
    raw = min(cap, base * (2 ** max(0, attempts - 1)))
    return random.uniform(0, raw)


class JobWorker:
    def __init__(self, store, *, worker_id: str | None = None, poll_interval: float = 2.0):
        self.store = store
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self.poll_interval = poll_interval
        self._running = False

    def run_once(self) -> bool:
        """Claim and process at most one job. Returns True if a job was handled
        (success or failure), False if the queue was empty."""
        job = self.store.claim_job(self.worker_id)
        if job is None:
            return False
        fn = HANDLERS.get(job["type"])
        if fn is None:
            self.store.fail_job(job["id"], f"no handler for job type '{job['type']}'",
                                backoff_seconds=_backoff_seconds(job["attempts"]))
            return True
        # Heartbeat: extend the lease every 2 min while the handler runs, so a
        # slow-but-alive job (e.g. a long PII scan) isn't reclaimed by the sweeper.
        stop_hb = threading.Event()
        def _heartbeat():
            while not stop_hb.wait(120):
                try:
                    self.store.touch_job(job["id"])
                except Exception:
                    pass
        threading.Thread(target=_heartbeat, daemon=True, name="job-heartbeat").start()
        try:
            fn(job.get("payload", {}), job)
            self.store.complete_job(job["id"])
        except FatalJobError as e:
            self.store.fail_job(job["id"], f"fatal: {e}", force_dead=True)
        except Exception as e:  # retryable
            self.store.fail_job(job["id"], str(e),
                                backoff_seconds=_backoff_seconds(job["attempts"]))
        finally:
            stop_hb.set()
        return True

    def run_forever(self, stop=lambda: False) -> None:
        """Poll-claim-process loop. `stop()` lets a caller request shutdown."""
        self._running = True
        while self._running and not stop():
            try:
                did = self.run_once()
            except Exception as e:  # never let the loop die on an unexpected error
                print(f"[worker {self.worker_id}] loop error: {e}", flush=True)
                did = False
            if not did:
                time.sleep(self.poll_interval)

    def stop(self) -> None:
        self._running = False
