"""Standalone worker-process entrypoint (#113 — split the worker off the API container).

Runs ONLY the durable job pool + the stuck-job/finalize sweeper + the scheduler — no uvicorn,
no HTTP. Lets a deploy run a dedicated worker container (`python worker_main.py`) beside the
API tier, so a UI/API deploy that swaps the API container never restarts running scans (the
incident this whole night circled around). The API container then sets ACP_WORKERS=0 and
stops carrying the pool.

Nothing changes for the current single-container deploy: app.py still starts the pool
in-process when ACP_WORKERS>0, and this module is inert unless it is the process entrypoint.
Draining on SIGTERM mirrors app.py's shutdown hook, so the graceful-drain guarantee holds
here too (ACA sends SIGTERM then waits ~30s before SIGKILL).
"""
from __future__ import annotations

import os
import signal
import sys
import threading
import time
from datetime import datetime, timezone

# Same sys.path convention app.py relies on, so `python worker_main.py` resolves siblings.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_stop = threading.Event()


def _handle_term(signum, _frame):
    print(f"[worker_main] signal {signum} — draining", flush=True)
    _stop.set()


def run(poll_seconds: float = 2.0, _install_signals: bool = True) -> None:
    """Boot store + scheduler + worker pool, block until SIGTERM/SIGINT, then drain. Returns
    after a clean drain. `_install_signals=False` is for tests (signals need the main thread)."""
    import core

    # A worker container with ACP_WORKERS=0 would boot and do nothing — almost certainly a
    # misconfig — so default the pool to a sensible size here rather than idle silently.
    if not os.environ.get("ACP_WORKERS"):
        os.environ["ACP_WORKERS"] = "12"

    if _install_signals:
        signal.signal(signal.SIGTERM, _handle_term)
        signal.signal(signal.SIGINT, _handle_term)

    core.get_store()
    core.reload_scheduler()
    core.start_scheduler()
    n = core.start_workers()
    print(f"[worker_main] started {n} job worker(s) + sweeper + scheduler; awaiting work", flush=True)

    # Heartbeat: in the split topology the API tier runs ACP_WORKERS=0, so its "are there
    # workers?" scan guard can't look at its own pool. A fresh timestamp in the shared store is
    # real liveness the API can check (worker_tier_alive) — not a config flag that could lie.
    # Throttled and best-effort: a transient DB blip must never kill the pool.
    last_beat = 0.0
    while not _stop.is_set():
        now = time.monotonic()
        if now - last_beat >= 15:
            last_beat = now
            try:
                core.get_store().set_setting(
                    "worker_tier_heartbeat",
                    datetime.now(timezone.utc).isoformat(),
                )
            except Exception:
                pass
        time.sleep(poll_seconds)

    try:
        core.stop_workers()
        core.stop_scheduler()
        print("[worker_main] drained; exiting", flush=True)
    except Exception as e:  # a failed drain must still let the process exit
        print(f"[worker_main] drain error: {e}", flush=True)


if __name__ == "__main__":
    run()
