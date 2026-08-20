"""Authoritative live-run snapshot for the Assess running screen (Live Assessment Experience PRD §8).

The snapshot is the single source of truth for progress and KPIs WHILE an assessment runs. It is
composed at read-time from the scan's own run summary — never from a browser event tally (PRD §8
reliability requirement).

The one honesty invariant that governs this whole file (and the bug it prevents): the running screen
must never show numbers that disagree with the final certification. So the outcome tally here is read
from the SAME source the completed numbers use — `store._fill_run_aggregate` populates the scan_runs
summary (`certifiable` / `uncertain` / `error` / `files` / `files_done`) that `finalize_scan_run`
finalises, and that the live progress panel (`assessmentProgress.outcomesFromRun`) already renders.
The fixed mapping is theirs, not a new one: `certifiable → passed`, `uncertain → needs review`,
`error → couldn't be assessed`, `processing = files − completed`. Deriving KPIs from a different path
(e.g. re-tallying `scan_rule_traces`) is exactly the divergence this reuses the source to avoid.

Honest by construction (ADR 0016): the canonical denominator is the assessment-eligible count — the
same figure `ScopeFunnel` shows via `estate_inventory.funnel_facts` — and the three denominators
(`discovered ≥ eligible ≥ completed`) are kept separate, never blended into one moving percentage.
KPIs that need live job-queue introspection (the leased/queued split, per-worker activity, pool
throughput) or a separate trace pass (a per-finding count) are NOT invented here — they are named in
`kpis_pending` for the running-screen/queue layer to supply. A number this module cannot prove from
the run summary, it does not show.
"""
from __future__ import annotations

# States in which the assessment is still doing work (vs. a terminal outcome).
_ACTIVE_STATES = {"preparing", "running", "degraded", "pausing", "paused", "finalizing"}
_TERMINAL_STATES = {"completed", "canceled", "cancelled", "failed"}


def _pos_int(v) -> int:
    """The run summary carries NULLs (a scan mid-flight, or one cancelled before aggregation) and the
    occasional float; treat anything not a positive number as 0, exactly as outcomesFromRun does."""
    try:
        return int(round(v)) if v and float(v) > 0 else 0
    except (TypeError, ValueError):
        return 0


def _eligible_denominator(run: dict, total_files: int) -> tuple[int, int]:
    """(discovered, eligible). Eligible is the assessment-eligible count from the scan's OWN recorded
    estate funnel — the same figure ScopeFunnel uses — falling back to the scan's queued file count
    when no inventory was recorded (older / local scans); the two reconcile, since the scan queues the
    assessable files. Never raises: a malformed scope degrades to the queued count."""
    scope = run.get("scope")
    inv = scope.get("inventory") if isinstance(scope, dict) else None
    if inv:
        try:
            import estate_inventory as _ei
            funnel = _ei.funnel_facts(inv)
            if funnel:
                return int(funnel.get("discovered", total_files) or total_files), \
                    int(funnel.get("assessable", total_files) or total_files)
        except Exception:
            pass
    return total_files, total_files


def _live_queue_block(store, scan_id: str):
    """The live worker/queue/lane block (in_flight / queued / workers / current / stale), owned by the
    running-screen/queue layer (`api/live_queue.py`). Imported guardedly so this module composes ONE
    snapshot object when that layer is present and degrades cleanly to persisted-results-only when it
    is not — letting the two land independently. Never raises into the snapshot."""
    try:
        import live_queue  # noqa: PLC0415 — optional, may not be on this branch yet
    except Exception:
        return None
    try:
        return live_queue.for_scan(store, scan_id)
    except Exception:
        return None


def _phase(state: str, eligible: int, completed: int) -> str:
    """Preparing → Assessing → Finalizing (PRD §4.2), derived from real progress, never a
    UI-invented boundary: Preparing until the eligible scope is known; Finalizing once every eligible
    file is accounted for but the run has not yet flipped terminal; `done` when it has."""
    if state in _TERMINAL_STATES:
        return "done"
    if not eligible:
        return "preparing"
    if completed >= eligible:
        return "finalizing"
    return "assessing"


def build_snapshot(store, scan_id: str, owner: str | None = None, now_iso: str | None = None) -> dict:
    """Compose the authoritative run snapshot, or `{"available": False, ...}` for an unknown scan.

    Owner-scoped and never raises, so the running screen degrades rather than erroring. `now_iso` is
    injected (not read from the clock) so a snapshot is deterministic to test and reproducible.
    """
    scan = store.get_scan(scan_id, owner=owner)
    if scan is None:
        return {"available": False, "reason": "scan_not_found"}
    # get_scan returns {"run": <summary>, "files": [...]}; the reconciled run summary (certifiable /
    # uncertain / error / files / files_done / status / scope, filled by _fill_run_aggregate) lives
    # under "run". Tolerate a flat summary dict too, so a caller holding the summary still works.
    run = scan["run"] if isinstance(scan, dict) and isinstance(scan.get("run"), dict) else scan

    # The reconciled file-outcome tally — read straight from the run summary, the SAME buckets
    # finalize_scan_run computes and the live progress panel renders (see the module docstring).
    passed = _pos_int(run.get("certifiable"))       # no blocking findings
    review = _pos_int(run.get("uncertain"))         # a check could not be evaluated → needs review
    failed = _pos_int(run.get("error"))             # the file could not be assessed at all
    total_files = _pos_int(run.get("files"))        # files the scan queued (assessment-eligible)
    files_done = _pos_int(run.get("files_done"))
    completed = min(files_done, total_files) if total_files else files_done
    processing = max(0, total_files - completed)     # leased + queued combined (the split needs the
                                                     # job queue — see kpis_pending)

    discovered, eligible = _eligible_denominator(run, total_files)
    state = (run.get("status") or "").strip().lower() or "running"
    phase = _phase(state, eligible, completed)

    # Named, not faked — each needs live job-queue state or a separate trace pass this module does not
    # do. The queue layer (below) supplies the first three when present, leaving only the finding count.
    pending = ["queued", "throughput", "findings_so_far", "workers"]

    snap = {
        "available": True,
        "run_id": scan_id,
        "source": run.get("source"),
        "state": state,
        "phase": phase,
        "active": state in _ACTIVE_STATES,
        # discovered ≥ eligible ≥ completed — three honest denominators, never blended into one %.
        "totals": {"discovered": discovered, "eligible": eligible},
        # PRD KPIs mapped onto the reconciled buckets (outcomesFromRun's fixed mapping):
        "kpis": {
            "completed": completed,
            "processing": processing,
            "need_attention": review,          # uncertain → needs review
            "unable_to_assess": failed,        # error → could not be assessed
        },
        # The raw reconciled tally, so the UI and a test can pin snapshot == run summary == final cert.
        "outcomes": {"passed": passed, "review": review, "failed": failed, "processing": processing},
        # Monotonic reconnect marker (PRD §8): completed only ever grows within a run.
        "sequence": completed,
        "generated_at": now_iso,
    }

    # Fold in the live worker/queue/lane block when the queue layer is present. Its authoritative
    # leased/queued split and per-worker activity supply the KPIs this persisted-results module can't,
    # so those drop out of `kpis_pending` (leaving only the per-finding count).
    queue = _live_queue_block(store, scan_id)
    if queue is not None:
        snap["queue"] = queue
        pending = [k for k in pending if k not in ("queued", "throughput", "workers")]
    snap["kpis_pending"] = pending
    return snap
