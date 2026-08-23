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
import os
import random
import threading
import time
import uuid

# Registry: job type -> handler(payload: dict, job: dict) -> None
HANDLERS: dict[str, callable] = {}

# How often the heartbeat extends a running job's lease.
HEARTBEAT_INTERVAL_S = 120


def max_unverified_lease_s() -> int:
    """How long we will keep extending a lease on the heartbeat's word alone, in seconds.

    THE HEARTBEAT PROVES LIVENESS, NOT PROGRESS. It runs on its own daemon thread and calls
    `touch_job` on a timer; it never asks the handler whether anything is actually happening. So a
    worker whose handler is wedged — blocked on a socket with no timeout, spinning, deadlocked —
    goes on extending its own lease forever, and `store.reclaim_stuck_jobs` (which only reclaims
    leases that have gone STALE) can never reach it. The 30-minute lease protects against a worker
    that DIES. It does nothing about one that hangs, which is the failure that leaves a queue
    showing "N active · 0 waiting" and draining nothing.

    So the extensions are bounded. Past this ceiling the heartbeat stops touching the job, the
    lease goes stale on its own, and the sweeper reclaims it like any other dead worker. The
    ceiling is generous by default because the cost of getting it wrong in the other direction is
    worse: reclaiming a job whose handler is still running means two workers do the same work.
    That risk already exists in the 30-minute path — this does not add it, it just makes a hung
    job reachable at all.

    0 disables the ceiling entirely (extend forever, the pre-existing behaviour).
    """
    try:
        return max(0, int(os.environ.get("ACP_JOB_MAX_LEASE_S", "3600") or "3600"))
    except ValueError:
        return 3600


class FatalJobError(Exception):
    """Raise from a handler to dead-letter the job immediately (no retry)."""


# Shown to the person, not to the log. The queue panel renders `last_error` verbatim, so a
# dead-letter reason has to say what happened and what to do — never quote a library's
# internals. It replaced: "The credentials do not contain the necessary fields need to refresh
# the access token. You must specify refresh_token, token_uri, client_id, and client_secret."
DRIVE_SESSION_EXPIRED = ("Your Google Drive session expired while this job was queued. "
                         "Reconnect Drive in Settings → Integrations, then re-run the scan.")


def drive_session_expired(exc: BaseException) -> str | None:
    """The human reason when `exc` means "this job's Drive token is dead", else None.

    A Drive token cannot come back to life inside a job: the GIS implicit flow issues an
    access token with no refresh_token, so every retry re-sends the same dead credential.
    Retrying is guaranteed waste — five attempts with backoff, then a dead-letter quoting
    google-auth at the user. Both shapes are terminal:

      * RefreshError — google-auth tried to refresh a credential that cannot be refreshed.
        After the `expiry` fix this should be unreachable from our own call sites; it stays
        classified because any future caller that sets an expiry would resurrect it.
      * HttpError 401 — Drive itself rejected the token. This is the real path now.

    Deliberately NOT terminal: 403 (rate limit / quota — retry works), 5xx, timeouts. And an
    unrecognised error returns None, so it keeps its retries. Misclassifying a transient
    failure as terminal loses work; the default must be to retry."""
    try:
        from google.auth.exceptions import RefreshError
        if isinstance(exc, RefreshError):
            return DRIVE_SESSION_EXPIRED
    except ImportError:                      # google-auth absent (unit tests, no-Drive deploy)
        pass
    try:
        from googleapiclient.errors import HttpError
        if isinstance(exc, HttpError) and getattr(exc, "status_code", None) == 401:
            return DRIVE_SESSION_EXPIRED
        # Older google-api-python-client exposes the code only on the response.
        if isinstance(exc, HttpError) and getattr(getattr(exc, "resp", None), "status", None) == 401:
            return DRIVE_SESSION_EXPIRED
    except ImportError:
        pass
    return None


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
        # slow-but-alive job (e.g. a long PII scan) isn't reclaimed by the sweeper —
        # but only up to max_unverified_lease_s(), because this thread can only prove
        # the PROCESS is alive, never that the WORK is moving. See that function.
        stop_hb = threading.Event()
        ceiling = max_unverified_lease_s()
        started = time.monotonic()
        def _heartbeat():
            while not stop_hb.wait(HEARTBEAT_INTERVAL_S):
                if ceiling and (time.monotonic() - started) >= ceiling:
                    # Say it once, then stop extending. The sweeper takes it from here; without
                    # this line a job that goes quiet here looks identical to one that finished.
                    print(f"[worker] job {job['id']} ({job.get('type')}) has held its lease for "
                          f"{ceiling}s without completing — no longer extending it, so the sweeper "
                          f"can reclaim it. The handler may still be running.", flush=True)
                    return
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
        except Exception as e:
            # An expired Drive token is terminal: the same dead credential is re-sent on every
            # retry, so the only thing backoff buys is four more failures and a confusing
            # dead-letter. Dead-letter it once, in words the reviewer can act on.
            expired = drive_session_expired(e)
            if expired:
                self.store.fail_job(job["id"], expired, force_dead=True)
            else:  # retryable
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
