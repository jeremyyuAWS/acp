"""Live worker/queue/lane state for the Assess running screen (Live Assessment Experience).

The running-screen KPIs (completed / findings / need-attention / unable-to-assess) and the funnel come
from the authoritative snapshot (live_snapshot.py / _fill_run_aggregate). This module is the OTHER half
the frontend cannot derive on its own: **what the worker pool is doing right now** — how many documents
are in flight, how many are queued behind them, and which document/criterion is currently being worked.

It is a pure, READ-ONLY composition over state the pipeline already publishes:
  * the run summary (`store.get_scan`): total files + files_done,
  * `activity.current(scan_id)`: the live in-flight set (already tracked race-free in-process and
    published — see activity._render_inflight), giving `in_flight`, the current file/criterion/action,
    the phase, and the publish timestamp `at`.

It touches NOTHING in the scan hot path (scanner/handlers) — so it can ship without racing that thread.
Throughput / ETA / percent are intentionally NOT recomputed here: the frontend already derives them from
files_done + elapsed (assessmentProgress.js). This block is strictly the queue/worker/lane view.
"""
from __future__ import annotations

import time

# Activity older than this (seconds since its last publish) means no worker has reported progress
# recently — the pool is idle between phases, the scan finished, or it is genuinely stuck. The running
# screen shows that as "not currently processing" rather than a stale in-flight count that reads as live.
STALE_AFTER = 120.0


def compose(run: dict | None, activity: dict | None, *, pool_max: int | None = None,
            now: float | None = None) -> dict:
    """The live worker/queue/lane block. PURE — the load-bearing bit, unit-tested with plain dicts.

    `run` is a scan_runs summary ({files, files_done, phase, status}); `activity` is the
    activity.current(scan_id) payload ({in_flight, file, sc, sc_name, action, phase, at}); `pool_max`
    is the assessment concurrency cap when known. Everything degrades to a safe, honest zero — a scan
    with no activity yet, or a finished one, reads as 0 in-flight, not as an error.
    """
    now = time.time() if now is None else now
    run = run or {}
    act = activity or {}

    total = _nonneg(run.get("files"))
    done = min(_nonneg(run.get("files_done")), total) if total else _nonneg(run.get("files_done"))

    at = act.get("at")
    fresh = isinstance(at, (int, float)) and (now - at) <= STALE_AFTER
    # A stale activity payload is not live progress: report 0 in flight and no current lane, so the
    # screen never shows a document as "being assessed" minutes after its worker went away.
    in_flight = _nonneg(act.get("in_flight")) if fresh else 0
    # Queued = discovered but neither finished nor currently in a worker. Clamp so a lagging/duplicated
    # activity count can never drive it negative.
    queued = max(0, total - done - in_flight) if total else 0

    current = None
    if fresh and (act.get("text") or act.get("file")):
        current = {
            "text": act.get("text"),                 # the rendered headline ("Assessing X for 1.4.3 …")
            "file": act.get("file"),
            "criterion": act.get("sc"),
            "criterion_name": act.get("sc_name"),
            "action": act.get("action"),
        }

    workers = {"busy": in_flight}
    if pool_max is not None and pool_max >= 0:
        workers["max"] = int(pool_max)
        workers["idle"] = max(0, int(pool_max) - in_flight)

    return {
        "phase": act.get("phase") or run.get("phase") or run.get("status"),
        "total": total,
        "done": done,
        "in_flight": in_flight,       # documents being assessed right now
        "queued": queued,             # discovered, waiting for a worker
        "workers": workers,
        "current": current,           # the oldest in-flight document (the "is it stuck?" one) or None
        "processing": fresh and in_flight > 0,   # is a worker actively reporting progress?
        "stale": bool(at) and not fresh,         # activity exists but is old → not live
    }


def _nonneg(x) -> int:
    return int(x) if isinstance(x, (int, float)) and x > 0 else 0


def for_scan(store, scan_id: str, *, pool_max: int | None = None, now: float | None = None) -> dict:
    """Fetch-and-compose wrapper. Defended so a live-queue read can never raise into a running screen:
    a missing scan, an unavailable activity store, or a bad pool value all degrade to the safe zero
    block rather than a 500. Owner-scoping is the caller's job (the route gates on get_scan first)."""
    try:
        run = store.get_scan(scan_id)
    except Exception:
        run = None
    try:
        import activity as _activity
        act = _activity.current(scan_id)
    except Exception:
        act = None
    if pool_max is None:
        try:
            import core
            pool_max = int(getattr(core, "WORKERS", 0) or 0) or None
        except Exception:
            pool_max = None
    return compose(run, act, pool_max=pool_max, now=now)
