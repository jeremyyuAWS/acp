"""Standalone worker entrypoint — ADR 0013 item 2 (worker-process isolation).

Runs the durable job-queue worker pool WITHOUT serving HTTP, so the worker tier can be its
own Container App replica set, scaled independently of the API. CPU-bound scan/remediation
work (OOXML/PII/office analysers) then no longer holds the GIL against the API's event loop
in the same process.

Deploy topology (see ADR 0013 §2 for the provisioning runbook):
  - API Container App:    command runs `uvicorn app:app`, env `ACP_WORKERS=0` (serve only).
  - Worker Container App:  command runs `python -m worker_main`, env `ACP_WORKERS=N`.
  - Both share `REDIS_URL` so per-scan/-remediate tokens survive cross-replica
    (core.register_scan_tokens falls back to per-process memory without it — which does NOT
    work once the API and workers are different processes, so REDIS_URL is REQUIRED here).

Same image as the API; only the command + env differ. No HTTP port is opened.
"""
from __future__ import annotations

import os
import signal
import threading

import core


def main() -> None:
    import handlers  # noqa: F401 — importing registers the job handlers with the worker pool

    # A worker container with 0 workers is pointless; default to a small pool if the deploy
    # didn't set ACP_WORKERS. (core.WORKERS is read from the env at import time.)
    if core.WORKERS < 1:
        core.WORKERS = int(os.environ.get("ACP_WORKERS") or "2") or 2

    if not core.REDIS_URL:
        # Not fatal (a single worker replica still works), but cross-replica token durability
        # depends on Redis — warn loudly so a misconfigured multi-replica deploy is visible.
        print("[acp-worker] WARNING: REDIS_URL not set — scan/remediate tokens are per-process; "
              "multi-replica or API-separated deploys need Redis (ADR 0013).", flush=True)

    n = core.start_workers()
    print(f"[acp-worker] started {n} worker(s) + sweeper (standalone, no HTTP)", flush=True)

    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_a: stop.set())
    stop.wait()   # block the main thread; daemon workers + sweeper run until a signal arrives

    print("[acp-worker] shutdown signal received — draining workers", flush=True)
    try:
        core.stop_workers()   # graceful drain + Langfuse flush (mirrors the API shutdown hook)
    except Exception as e:
        print(f"[acp-worker] drain error: {e}", flush=True)


if __name__ == "__main__":
    main()
