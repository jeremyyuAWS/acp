"""POST /discovery/preflight — a read-only check on the SPECIFIC source + scope a user has
selected, run at the moment they are about to click "Start Scan", before any scan row exists.

WHY THIS IS SEPARATE FROM /readyz. /readyz (routes/system.py) answers "can this deployment do
work at all right now" — worker tier alive, PDF/vision engines, SMB config. It has no scan_id and
no idea which folder was picked, so it cannot answer the question that actually determines whether
THIS scan will return anything: is the credential still valid, do the selected roots still exist,
can the account actually list them, and is the queue in a state to accept the work. A deployment
can be perfectly /readyz and still return "0 documents" because the folder the user picked was
deleted, or their Drive token expired between page load and click.

DELIBERATELY READ-ONLY. No scan row, no job, no full enumeration — one bounded existence check per
selected root (never a folder listing, never the BFS walk scanner.py runs for real), plus the same
cheap worker/queue checks /readyz already does. Matches the durable start path's own single-flight
semantics: this never creates state, so calling it twice in a row is free.
"""
from __future__ import annotations
import os

from fastapi import APIRouter, Request

import core

router = APIRouter()

# How many QUEUED (not yet claimed) jobs the durable queue can carry before a fresh scan should be
# flagged as "will sit waiting" rather than silently enqueued behind an unbounded backlog. No such
# threshold existed anywhere in the codebase before this (checked: no MAX_QUEUE/backlog constant).
# Expressed as an env var, same pattern as ACP_CHECKPOINT_INTERVAL_S, so an operator can tune it
# per-deployment without a code change; the default is generous — this is a "something is
# seriously backed up" signal, not a routine throttle.
MAX_QUEUE_BACKLOG = int(os.environ.get("ACP_MAX_QUEUE_BACKLOG", "50") or "50")


def inline_discover_enabled() -> bool:
    """Does this deployment run Discover in the API process instead of the worker tier?

    Off by default: the durable queue stays the shipped behaviour, and a deployment opts in with
    ACP_INLINE_DISCOVER=1. See routes/scans.start_scan for what the mode gives up (restart
    survival and automatic retry, for the discover stage only) and what it does not (single
    flight, which _scan_discover enforces itself via the durable discovery guard).

    Read per call, never latched at import — same reason api/scan_formats.formats() is: a
    module-level read wins over an env var set afterwards, and the failure is silent.
    """
    return os.environ.get("ACP_INLINE_DISCOVER", "").strip().lower() in ("1", "true", "yes", "on")


@router.post("/discovery/preflight")
def discovery_preflight(request: Request, source: str, folder: str | None = None,
                        folders: list[str] | None = None):
    """Ready / degraded / blocked verdict for starting a Discover scan of this source + scope.

    - blocked: the scan would fail immediately or return nothing — bad credential, an unreachable
      selected root, or no worker capacity to ever claim the job.
    - degraded: the scan would likely work but not promptly — the durable queue has a backlog.
    - ready: nothing found wrong.

    source/folder/folders mirror start_scan's own params exactly (routes/scans.py) so the caller
    sends the same request it is about to make to POST /scans, plus the same X-Drive-Token /
    X-Sp-Token headers. `local` has no credential or roots to check — its readiness is entirely
    the worker/queue checks below.
    """
    roots = list(folders) if folders else ([folder] if folder else None)

    reasons: list[str] = []
    degraded_reasons: list[str] = []
    src: dict = {"ready": True}
    if source == "drive":
        from .drive import describe_drive_readiness
        src = describe_drive_readiness(request, roots)
    elif source == "sharepoint":
        from .sharepoint import describe_sharepoint_readiness
        src = describe_sharepoint_readiness(request, roots)
    # 'local' (the bundled demo corpus) has no external credential or roots to validate.
    if not src.get("ready"):
        reasons.append(src.get("reason") or "source is not ready")

    workers = core.store.worker_tier_status()
    local_pool = int(getattr(core, "WORKERS", 0) or 0)
    inline = inline_discover_enabled()

    queue_stats = core.store.job_stats(owner=None)
    queued = int(queue_stats.get("queued") or 0)
    queue_backlogged = queued >= MAX_QUEUE_BACKLOG

    if inline:
        # Worker-free Discover: this scan will run in the API process, so the worker tier and the
        # queue depth cannot determine whether it can start. Reporting them as blocking here was
        # the hardest dependency in the discover path — a deployment whose worker tier had never
        # come up could not begin a listing that needs no worker at all.
        #
        # They are still REPORTED, not dropped. Assess runs on workers whatever this stage does,
        # so an operator reading a preflight for a dead worker tier should still see that, and a
        # caller that treats capacity as advisory keeps every signal it had. Only the verdict
        # changes.
        capacity_state = "inline"
        if not (bool(local_pool) or workers["alive"]):
            degraded_reasons.append(
                "no workers — Discover will run in the API process; Assess will wait for a worker")
    else:
        # Capacity state — distinguishes "starting" (ever seen, not alive right now, allow queuing)
        # from "unavailable" (never started, infrastructure issue, block). "starting" is allowed
        # through because the durable queue will hold the scan until a worker is ready.
        if bool(local_pool) or workers["alive"]:
            capacity_state = "ready"
        elif workers["ever_seen"]:
            # Workers have heartbeated before but are not responding now. The scan can be durably
            # queued — it will start automatically when a worker comes up. Show a notice, don't block.
            capacity_state = "starting"
            degraded_reasons.append("no_workers")
        else:
            # No worker has ever heartbeated — the worker tier was never started. Block until it is.
            capacity_state = "unavailable"
            reasons.append("worker_tier_never_started")

        if queue_backlogged:
            degraded_reasons.append(
                f"queue has {queued} jobs waiting — this scan will queue behind them")
            if capacity_state == "ready":
                capacity_state = "busy"

    blocked = bool(reasons)
    verdict = "blocked" if blocked else ("degraded" if degraded_reasons else "ready")
    return {
        "verdict": verdict,
        "capacity_state": capacity_state,
        # "inline" — runs in the API process, needs no worker. "queued" — needs the worker tier.
        # Stated rather than implied: the same `verdict: ready` means two different things about
        # what must be alive for the scan to start, and only this field tells them apart.
        "discover_execution": "inline" if inline else "queued",
        "blocked_reasons": reasons,
        "degraded_reasons": degraded_reasons,
        "source": src,
        "workers": {**workers, "local_pool": local_pool},
        "queue": {"queued": queued, "backlogged": queue_backlogged, "threshold": MAX_QUEUE_BACKLOG},
    }
