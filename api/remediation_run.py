"""One remediation run, as the server sees it: state, reconciled counters, invariants.

`store.remediation_status` answers "how much is left" from four independent queries and lets the
browser assemble the rest. That is how the Remediate panel came to show, in one paint, an
"Applying fixes" headline, zero active documents, every document queued, corrected copies already
saved, and a source label naming a provider the run does not use. Each number was true of its own
subsystem. Together they were not an account of anything.

This module is the account. It is PURE — no database, no clock of its own, no HTTP — so the state
machine, the counter partition and the invariants can be tested exhaustively against literals.
`store.remediation_run_facts` gathers the rows; `build_snapshot` turns one consistent read of them
into one revisioned snapshot; the route serves it and the SSE stream pushes it.

THE CLIENT NEVER DERIVES A TERMINAL STATE (PRD §7). It renders what this returns, and asks for a
fresh snapshot when it has missed one. Counter arithmetic in the browser is exactly what produced
"-147 documents remediated" (see store.remediation_status) and "Applying fixes" over an idle queue.
"""
from __future__ import annotations

import datetime as _dt

# ── the vocabulary ───────────────────────────────────────────────────────────

#: The partition of a run's document scope. Every document in scope lands in EXACTLY one of
#: these, which is what makes their sum equal to the total a meaningful check rather than a
#: coincidence. Findings and fixes are counted separately and deliberately — one document
#: carries many findings, and conflating the two units is the other half of the defect this
#: module exists to close.
DOCUMENT_OUTCOMES = ("completed", "processing", "waiting", "review", "failed", "skipped")

#: Every run state the panel can display. `draft` and `accepted` are entry states (no work has
#: been claimed yet); `paused` is declared but NEVER derived — ACP has no pause control for a
#: remediation run, and a state nothing can produce must not be inferred from an idle queue.
#: See PRD §18's first open decision.
RUN_STATES = (
    "draft", "accepted", "running", "waiting", "retry_scheduled", "needs_attention",
    "paused", "stalled", "completing", "completed", "completed_with_exceptions", "failed",
    "cancel_requested", "cancelled",
)

#: PRD §7 state precedence, most severe first. The displayed state is the FIRST applicable entry
#: in this tuple — not whichever query answered last, which is how a queued run came to claim it
#: was applying fixes.
STATE_PRECEDENCE = (
    "failed", "stalled", "needs_attention", "retry_scheduled", "waiting", "running",
    "completing", "completed_with_exceptions", "completed",
)

#: The lifecycle rail (PRD §6B), in order. Phases overlap — a run can be applying fixes to some
#: documents while re-checking others — so this is an ordering, not a cursor.
PHASES = ("preparing", "applying", "rechecking", "saving", "finalizing")

PHASE_LABELS = {
    "preparing": "Preparing",
    "applying": "Applying approved fixes",
    "rechecking": "Re-checking corrected documents",
    "saving": "Saving corrected copies",
    "finalizing": "Finalizing evidence",
}

STATE_MESSAGES = {
    "draft": "Review scope and start",
    "accepted": "Remediation accepted",
    "running": "Remediation in progress",
    "waiting": "Waiting for processing capacity",
    "retry_scheduled": "Temporary issue; retry scheduled",
    "needs_attention": "Review required",
    "paused": "Run paused",
    "stalled": "Progress has stopped",
    "completing": "Finalizing results",
    "completed": "Remediation complete",
    "completed_with_exceptions": "Automatic work complete; exceptions remain",
    "failed": "Remediation failed",
    "cancel_requested": "Stopping safely",
    "cancelled": "Remediation cancelled",
}

#: States in which no further document work will be attempted. A terminal run with an active
#: publish-capable attempt is an invariant violation, not a display quirk.
TERMINAL_STATES = ("completed", "completed_with_exceptions", "failed", "cancelled")

#: How long a run may go without a durable progress event before the server calls it stalled
#: rather than merely slow. Phase-specific thresholds are PRD §18's second open decision; until
#: there is per-phase evidence to set them from, one honest threshold beats five invented ones.
STALL_AFTER_S = 900

#: Grace added to a lease's expiry before its attempt stops counting as active. The sweeper
#: reclaims on the same signal (store.reclaim_stuck_jobs); the grace keeps a snapshot taken
#: between expiry and reclaim from flickering a document out of `processing` and back.
LEASE_GRACE_S = 60

# Ten server buckets cover the five-minute live window. The browser controls presentation
# cadence, but never re-buckets raw events or derives a completion rate itself.
THROUGHPUT_WINDOW_S = 300
THROUGHPUT_BUCKET_S = 30
THROUGHPUT_MIN_SAMPLE = 5

#: Provider labels. "SharePoint / OneDrive" — the label every other surface in this repo uses —
#: is deliberately NOT here: PRD §17.1 is that a SharePoint run must never be labelled OneDrive,
#: and a slash-joined pair naming both providers is precisely the mismatch that made the panel
#: look unreliable. One provider per run, named exactly.
PROVIDER_LABELS = {
    "sharepoint": "SharePoint",
    "onedrive": "OneDrive",
    "drive": "Google Drive",
    "blob": "Azure Blob Storage",
    "local": "Upload",
    "smb": "File share",
}


def _parse(ts) -> _dt.datetime | None:
    """An ISO timestamp as an aware UTC datetime, or None when it is missing or unreadable.

    None is "not known", and every caller treats it that way rather than substituting now() —
    a missing heartbeat that reads as a fresh one is the failure this whole module is about.
    """
    if not ts:
        return None
    if isinstance(ts, _dt.datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=_dt.timezone.utc)
    try:
        out = _dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return out if out.tzinfo else out.replace(tzinfo=_dt.timezone.utc)


def _age_s(ts, now: _dt.datetime) -> float | None:
    parsed = _parse(ts)
    return None if parsed is None else (now - parsed).total_seconds()


def _eta_label(low_minutes: int, high_minutes: int) -> str:
    """A compact range without implying precision the sample does not support."""
    if high_minutes < 90:
        return f"about {low_minutes}–{high_minutes} min left"
    low_hours = max(1, round(low_minutes / 60))
    high_hours = max(low_hours, round(high_minutes / 60))
    return f"about {low_hours}–{high_hours} hr left"


def derive_throughput(completed_at: list, *, remaining: int,
                      now: _dt.datetime) -> tuple[dict | None, dict]:
    """Server-observed successful completion rate and evidence-gated ETA."""
    stamps = [stamp for value in completed_at if (stamp := _parse(value)) is not None]
    current_start = now - _dt.timedelta(seconds=THROUGHPUT_WINDOW_S)
    previous_start = current_start - _dt.timedelta(seconds=THROUGHPUT_WINDOW_S)
    current = [stamp for stamp in stamps if current_start < stamp <= now]
    previous = [stamp for stamp in stamps if previous_start < stamp <= current_start]
    buckets = [0] * (THROUGHPUT_WINDOW_S // THROUGHPUT_BUCKET_S)
    for stamp in current:
        index = min(len(buckets) - 1, int((stamp - current_start).total_seconds()
                                         // THROUGHPUT_BUCKET_S))
        buckets[index] += 1

    if not current:
        return None, {"available": False, "reason": "no_recent_completions"}

    window_minutes = THROUGHPUT_WINDOW_S / 60
    rate = len(current) / window_minutes
    throughput = {
        "window_seconds": THROUGHPUT_WINDOW_S,
        "bucket_seconds": THROUGHPUT_BUCKET_S,
        "documents_per_minute": round(rate, 1),
        "sample_documents": len(current),
        "buckets": buckets,
        "change_percent": None,
    }
    if len(current) >= THROUGHPUT_MIN_SAMPLE and len(previous) >= THROUGHPUT_MIN_SAMPLE:
        previous_rate = len(previous) / window_minutes
        throughput["change_percent"] = round((rate - previous_rate) / previous_rate * 100)

    if remaining <= 0:
        return throughput, {"available": False, "reason": "run_complete"}
    if len(current) < THROUGHPUT_MIN_SAMPLE:
        return throughput, {"available": False, "reason": "insufficient_sample",
                            "sample_documents": len(current),
                            "minimum_documents": THROUGHPUT_MIN_SAMPLE}

    # Approximate 95% Poisson interval for the observed count. It is deliberately wide with five
    # samples and narrows only as evidence accumulates; no client-side smoothing invents certainty.
    spread = 1.96 * (len(current) ** 0.5)
    low_rate = max(0.01, (len(current) - spread) / window_minutes)
    high_rate = (len(current) + spread) / window_minutes
    low_minutes = max(1, round(remaining / high_rate))
    high_minutes = max(low_minutes, round(remaining / low_rate))
    return throughput, {
        "available": True,
        "label": _eta_label(low_minutes, high_minutes),
        "low_minutes": low_minutes,
        "high_minutes": high_minutes,
        "sample_documents": len(current),
        "method": "recent_completions_approximate_95_percent",
    }


# ── per-document outcome ─────────────────────────────────────────────────────

def classify_document(job: dict, *, now: _dt.datetime, review_pending: bool = False,
                      has_correction: bool = False, has_verified_fix: bool = False,
                      lease_grace_s: int = LEASE_GRACE_S) -> tuple[str, str]:
    """The one outcome this document has reached in this run, plus the reason code for it.

    Returns a member of DOCUMENT_OUTCOMES. Exhaustive and mutually exclusive BY CONSTRUCTION —
    every branch returns, and no document can satisfy two — which is what lets the caller assert
    the six counters sum to the scope rather than hope they do.

    An expired lease is `waiting`, not `processing` and not `failed`: the sweeper will hand the
    document to another worker, so the honest answer is that nobody is working on it right now.
    Whether the RUN is stalled is a separate question, answered once at run level.
    """
    status = (job or {}).get("status") or ""

    if status == "dead":
        return "failed", "attempts_exhausted"

    if status == "cancelled":
        # Cancelled after a claim: in scope, no eligible approved fix was applied. `skipped` is
        # the partition's slot for exactly that, and it keeps the sum intact.
        return "skipped", "cancelled"

    if status == "running":
        lease = _parse(job.get("lease_expires_at"))
        if lease is None:
            # Claimed before lease_expires_at existed, or a claim path that does not set it.
            # Fall back to the heartbeat the sweeper's second predicate uses.
            beat = _age_s(job.get("locked_at"), now)
            if beat is None or beat <= STALL_AFTER_S:
                return "processing", "attempt_active"
            return "waiting", "lease_unknown_and_heartbeat_stale"
        if (lease - now).total_seconds() + lease_grace_s > 0:
            return "processing", "attempt_active"
        return "waiting", "lease_expired"

    if status == "queued":
        run_after = _parse(job.get("run_after"))
        if run_after is not None and run_after > now:
            return "waiting", "retry_scheduled"
        return "waiting", "unclaimed"

    if status == "done":
        # Terminal for the worker. Which of the three terminal outcomes it is depends on what the
        # run has to show for it — a decision the queue cannot make and the browser must not.
        if review_pending:
            return "review", "human_decision_required"
        if has_correction or has_verified_fix:
            return "completed", "corrected_copy_recorded"
        return "skipped", "no_eligible_fix_applied"

    # An unrecognised status is non-terminal and unclaimed as far as this run can tell. It is
    # never counted as completed: guessing in the optimistic direction is what "Applying fixes"
    # over an idle queue already cost.
    return "waiting", "unknown_job_status"


# ── run state ────────────────────────────────────────────────────────────────

def _applicable_states(counters: dict, *, total: int, claimed_any: bool,
                       progress_age_s: float | None, retry_at, stall_after_s: int,
                       corrected_pending_delivery: int) -> dict[str, str]:
    """Which precedence states this run currently satisfies, mapped to their reason codes.

    Each predicate is an independently TRUE statement about the run, so precedence chooses
    between facts rather than between guesses. Where a precedence entry would otherwise assert
    something false — "delayed until a known retry time" while three documents are actively being
    fixed — the predicate is gated and the gate is named here.
    """
    completed = counters["completed"]
    processing = counters["processing"]
    waiting = counters["waiting"]
    review = counters["review"]
    failed = counters["failed"]
    skipped = counters["skipped"]
    non_terminal = processing + waiting
    exceptions = review + failed + skipped

    out: dict[str, str] = {}

    if total and non_terminal == 0 and completed == 0 and failed > 0:
        out["failed"] = "every_document_failed"

    # Stall is only claimable once SOMETHING was claimed. A queue nobody has picked up is
    # `waiting` — "no compatible processing slot is currently active" — and calling that stalled
    # would report a capacity fact as a fault.
    if non_terminal > 0 and claimed_any and progress_age_s is not None \
            and progress_age_s > stall_after_s:
        out["stalled"] = "no_progress_within_threshold"

    if review > 0:
        out["needs_attention"] = "human_decision_required"

    # Gated on there being nothing active: with an attempt running, the run is not "delayed
    # until a known retry time", whatever some other document's run_after says.
    if retry_at is not None and processing == 0 and waiting > 0:
        out["retry_scheduled"] = "retry_scheduled"

    if waiting > 0 and processing == 0:
        out["waiting"] = "no_active_attempt"

    # PRD §17.2. The ONLY predicate that can put the run in an applying state, so a queued run
    # with zero active attempts cannot display "Applying fixes" by any path.
    if processing > 0:
        out["running"] = "attempt_active"

    if total and non_terminal == 0 and corrected_pending_delivery > 0:
        out["completing"] = "delivery_reconciliation_outstanding"

    if total and non_terminal == 0 and exceptions > 0:
        out["completed_with_exceptions"] = "exceptions_remain"

    if total and non_terminal == 0 and exceptions == 0:
        out["completed"] = "all_documents_terminal"

    return out


def derive_run_state(counters: dict, *, total: int, claimed_any: bool = False,
                     progress_age_s: float | None = None, retry_at=None,
                     cancel_requested: bool = False, cancelled: bool = False,
                     corrected_pending_delivery: int = 0,
                     stall_after_s: int = STALL_AFTER_S) -> dict:
    """The run's single displayed state, its reason code, and the states it also satisfies.

    Cancellation overrides normal processing states (PRD §7); everything else resolves through
    STATE_PRECEDENCE. `also` is returned so the panel can say "Review required · 20 documents
    still processing" instead of hiding live progress behind the more severe headline — the
    precedence order decides the HEADLINE, not what the run is allowed to mention.
    """
    if cancelled:
        return {"state": "cancelled", "reason": "cancelled", "also": []}
    if cancel_requested:
        return {"state": "cancel_requested", "reason": "cancel_requested", "also": []}
    if not total:
        return {"state": "draft", "reason": "no_durable_run", "also": []}

    applicable = _applicable_states(
        counters, total=total, claimed_any=claimed_any, progress_age_s=progress_age_s,
        retry_at=retry_at, stall_after_s=stall_after_s,
        corrected_pending_delivery=corrected_pending_delivery)

    # Entry state: a durable run exists and nothing has ever been claimed. More precise than
    # `waiting`, which also covers a run whose workers went away mid-flight.
    if not claimed_any and counters["waiting"] == total:
        return {"state": "accepted", "reason": "no_attempt_claimed",
                "also": sorted(applicable)}

    for state in STATE_PRECEDENCE:
        if state in applicable:
            return {"state": state, "reason": applicable[state],
                    "also": sorted(s for s in applicable if s != state)}

    # Every predicate above is gated on `total`, and `total` is non-zero here, so this is
    # unreachable by construction. Returning `waiting` rather than raising keeps a snapshot
    # servable if a future outcome is added to the partition without a matching predicate.
    return {"state": "waiting", "reason": "no_predicate_matched", "also": sorted(applicable)}


# ── phases ───────────────────────────────────────────────────────────────────

def derive_phases(counters: dict, *, total: int, state: str, applied_fixes: int,
                  verified_fixes: int, corrected_stored: int,
                  corrected_pending_delivery: int) -> list[dict]:
    """The phase rail, derived from durable facts rather than optimistic client transitions.

    Every phase carries exactly one of: pending / active / completed / completed_with_exceptions
    / failed / skipped. Phases overlap on purpose — `applying` and `rechecking` are both active
    on a run that is fixing some documents while verifying others — because pretending the work
    is serial is what made one "current file" the whole story.
    """
    terminal = counters["completed"] + counters["review"] + counters["failed"] + counters["skipped"]
    non_terminal = counters["processing"] + counters["waiting"]
    started = terminal > 0 or counters["processing"] > 0

    def _phase(key: str, status: str, detail: str | None = None) -> dict:
        return {"key": key, "label": PHASE_LABELS[key], "status": status, "detail": detail}

    if state in ("draft",):
        return [_phase(k, "pending") for k in PHASES]

    rail: list[dict] = []
    rail.append(_phase("preparing", "completed" if started or state != "accepted" else "active",
                       f"{total} document{'' if total == 1 else 's'} in scope"))

    if counters["processing"] > 0:
        rail.append(_phase("applying", "active",
                           f"{counters['processing']} document"
                           f"{'' if counters['processing'] == 1 else 's'} in flight"))
    elif non_terminal > 0:
        rail.append(_phase("applying", "active" if state == "running" else "pending",
                           f"{counters['waiting']} waiting"))
    elif counters["failed"] and not counters["completed"]:
        rail.append(_phase("applying", "failed", f"{counters['failed']} failed"))
    else:
        rail.append(_phase("applying", "completed_with_exceptions" if counters["failed"]
                           else "completed", f"{applied_fixes} fix"
                           f"{'' if applied_fixes == 1 else 'es'} applied"))

    if applied_fixes == 0:
        rail.append(_phase("rechecking", "pending" if non_terminal else "skipped",
                           None if non_terminal else "No fixes to re-check"))
    elif verified_fixes < applied_fixes:
        rail.append(_phase("rechecking", "active",
                           f"{verified_fixes} of {applied_fixes} fixes verified"))
    else:
        rail.append(_phase("rechecking", "completed",
                           f"{verified_fixes} fix{'' if verified_fixes == 1 else 'es'} verified"))

    if corrected_stored == 0:
        rail.append(_phase("saving", "pending" if non_terminal or applied_fixes else "skipped",
                           None if non_terminal or applied_fixes else "No corrected copies to save"))
    elif corrected_pending_delivery > 0:
        rail.append(_phase("saving", "active",
                           f"{corrected_pending_delivery} corrected cop"
                           f"{'y' if corrected_pending_delivery == 1 else 'ies'} pending delivery"))
    else:
        rail.append(_phase("saving", "completed",
                           f"{corrected_stored} corrected cop"
                           f"{'y' if corrected_stored == 1 else 'ies'} delivered"))

    if state in ("completed", "completed_with_exceptions", "failed", "cancelled"):
        rail.append(_phase("finalizing", "completed_with_exceptions"
                           if state == "completed_with_exceptions" else
                           ("failed" if state == "failed" else "completed")))
    elif state == "completing":
        rail.append(_phase("finalizing", "active"))
    else:
        rail.append(_phase("finalizing", "pending"))

    return rail


# ── source identity ──────────────────────────────────────────────────────────

def source_identity(*, scan_id: str, provider: str | None, locations: list[dict] | None = None,
                    scan_snapshot_id: str | None = None) -> dict:
    """Where this run's documents came from, taken from the run's own scan record.

    NEVER INFERRED FROM THE SIGNED-IN ACCOUNT OR A DEFAULT CONNECTOR (PRD §6A), and never
    slash-joined with a second provider: a SharePoint run says SharePoint, and `PROVIDER_LABELS`
    has no entry that names two providers at once. An unrecognised provider is echoed back as
    itself rather than mapped to a plausible neighbour — an unknown source is a fact, a wrong one
    is the defect.
    """
    key = (provider or "").strip().lower()
    label = PROVIDER_LABELS.get(key) or (provider or None)
    rows = [r for r in (locations or []) if any(r.get(k) for k in ("site_name", "library_name"))]
    sites = sorted({r["site_name"] for r in rows if r.get("site_name")})
    libraries = sorted({r["library_name"] for r in rows if r.get("library_name")})
    parts = [label] if label else []
    parts += sites[:1] if len(sites) == 1 else ([f"{len(sites)} sites"] if sites else [])
    parts += libraries[:1] if len(libraries) == 1 else \
        ([f"{len(libraries)} libraries"] if libraries else [])
    return {
        "scan_id": scan_id,
        "provider": key or None,
        "provider_label": label,
        "sites": sites,
        "libraries": libraries,
        # The scan snapshot these documents were listed from. The panel's own identity check
        # (invariant 5) compares this to the run's scan_id — a mismatch is reported, not resolved.
        "scan_snapshot_id": scan_snapshot_id or scan_id,
        "breadcrumb": " · ".join(p for p in parts if p) or None,
    }


# ── invariants ───────────────────────────────────────────────────────────────

def check_invariants(snapshot: dict) -> list[dict]:
    """PRD §9's publish-time checks. Returns one entry per violation, empty when reconciled.

    A violation is REPORTED, never repaired by picking a subsystem's number and calling it the
    answer. `metric` names what the panel must stop asserting; the rest of the snapshot stays
    exactly as measured so the last confirmed values remain visible.
    """
    out: list[dict] = []
    counters = snapshot.get("documents") or {}
    total = int(snapshot.get("total_documents") or 0)
    partition = sum(int(counters.get(k) or 0) for k in DOCUMENT_OUTCOMES)
    if partition != total:
        out.append({"invariant": "document_partition", "metric": "documents",
                    "detail": f"outcome partition sums to {partition}, scope is {total}"})

    fixes = snapshot.get("fixes") or {}
    applied, verified = int(fixes.get("applied") or 0), int(fixes.get("verified") or 0)
    if verified > applied:
        out.append({"invariant": "verified_within_applied", "metric": "fixes",
                    "detail": f"{verified} verified fixes against {applied} applied"})

    delivery = snapshot.get("delivery") or {}
    delivered = int(delivery.get("delivered") or 0)
    eligible = int(delivery.get("eligible") or 0)
    if delivered > eligible:
        out.append({"invariant": "delivery_within_eligible", "metric": "delivery",
                    "detail": f"{delivered} delivered against {eligible} documents with a "
                              "recorded correction"})

    if snapshot.get("state") in TERMINAL_STATES and int(counters.get("processing") or 0) > 0:
        out.append({"invariant": "terminal_has_no_active_attempt", "metric": "documents",
                    "detail": f"state {snapshot.get('state')} with "
                              f"{counters.get('processing')} active attempt(s)"})

    source = snapshot.get("source") or {}
    if source.get("scan_snapshot_id") and source.get("scan_snapshot_id") != snapshot.get("scan_id"):
        out.append({"invariant": "source_matches_scan", "metric": "source",
                    "detail": "source identity references a different scan snapshot"})

    for attempt in snapshot.get("active_attempts") or []:
        if not attempt.get("lease_valid"):
            out.append({"invariant": "active_attempt_has_valid_lease", "metric": "documents",
                        "detail": f"attempt on {attempt.get('file') or 'a document'} has no "
                                  "valid lease"})
            break

    if snapshot.get("revision") is None or not snapshot.get("generated_at"):
        out.append({"invariant": "revisioned_snapshot", "metric": "freshness",
                    "detail": "snapshot has no revision or generation time"})
    return out


# ── the snapshot ─────────────────────────────────────────────────────────────

def _revision(facts: dict, now: _dt.datetime) -> int:
    """A monotonic revision for this run, in milliseconds since the epoch.

    There is no per-run sequence column to read (`scan_runs.revision` is bumped by remediation
    WRITES and not by a job moving queued→running, so it stands still through most of a run).
    The newest durable timestamp the run has produced is monotonic for the same reason a clock
    is, changes on every durable transition, and needs no schema change to obtain. A client
    compares revisions to detect a gap; it never does arithmetic on one.
    """
    stamps = [_parse(facts.get("latest_progress_at")), _parse(facts.get("latest_delivery_at")),
              _parse(facts.get("started_at"))]
    newest = max([s for s in stamps if s is not None], default=None)
    if newest is None:
        return 0
    return int(newest.timestamp() * 1000)


def build_snapshot(facts: dict, *, now: _dt.datetime | None = None,
                   stall_after_s: int = STALL_AFTER_S,
                   lease_grace_s: int = LEASE_GRACE_S) -> dict:
    """One consistent read of the run's rows → one revisioned snapshot.

    `facts` is store.remediation_run_facts's output; see it for the shape. Everything below is
    derived from ONE read, so every counter in the result shares one revision — PRD §9's last
    invariant, satisfied by construction rather than by a check that runs afterwards.
    """
    now = now or _dt.datetime.now(_dt.timezone.utc)
    jobs = facts.get("jobs") or []
    review_docs = set(facts.get("review_documents") or ())
    corrected = set(facts.get("corrected_documents") or ())
    verified_docs = set(facts.get("verified_documents") or ())

    counters = {k: 0 for k in DOCUMENT_OUTCOMES}
    reasons: dict[str, int] = {}
    active: list[dict] = []
    retry_candidates: list[_dt.datetime] = []
    completed_at: list = []
    claimed_any = False

    for job in jobs:
        file = job.get("file")
        outcome, reason = classify_document(
            job, now=now, review_pending=file in review_docs,
            has_correction=file in corrected, has_verified_fix=file in verified_docs,
            lease_grace_s=lease_grace_s)
        counters[outcome] += 1
        if outcome == "completed":
            completed_at.append(job.get("updated_at"))
        reasons[reason] = reasons.get(reason, 0) + 1
        if int(job.get("attempts") or 0) > 0 or job.get("locked_at"):
            claimed_any = True
        if outcome == "processing":
            lease = _parse(job.get("lease_expires_at"))
            active.append({
                "file": file,
                "phase": job.get("phase") or None,
                "attempt": int(job.get("attempts") or 0) or None,
                "started_at": job.get("locked_at") or None,
                "progress_at": job.get("updated_at") or None,
                "elapsed_s": _age_s(job.get("locked_at"), now),
                # `None` lease means the claim predates the column — treated as valid here for
                # the same reason classify_document does, and the invariant check below is what
                # would catch a genuinely leaseless active attempt.
                "lease_valid": lease is None or (lease - now).total_seconds() + lease_grace_s > 0,
                "lease_expires_at": job.get("lease_expires_at") or None,
            })
        if outcome == "waiting" and reason == "retry_scheduled":
            run_after = _parse(job.get("run_after"))
            if run_after is not None:
                retry_candidates.append(run_after)

    total = len(jobs)
    corrected_stored = int(facts.get("corrected_stored") or 0)
    delivered = int(facts.get("corrected_delivered") or 0)
    pending_delivery = max(0, corrected_stored - delivered)
    retry_at = min(retry_candidates) if retry_candidates else None
    progress_age = _age_s(facts.get("latest_progress_at"), now)

    resolved = derive_run_state(
        counters, total=total, claimed_any=claimed_any, progress_age_s=progress_age,
        retry_at=retry_at, cancel_requested=bool(facts.get("cancel_requested")),
        cancelled=bool(facts.get("cancelled")), corrected_pending_delivery=pending_delivery,
        stall_after_s=stall_after_s)
    state = resolved["state"]

    applied = int(facts.get("fixes_applied") or 0)
    verified = int(facts.get("fixes_verified") or 0)
    remaining = counters["processing"] + counters["waiting"]
    throughput, estimate = derive_throughput(completed_at, remaining=remaining, now=now)

    snapshot = {
        "run_id": facts.get("run_id"),
        "scan_id": facts.get("scan_id"),
        "batch_id": facts.get("batch_id"),
        "generated_at": now.isoformat(),
        "revision": _revision(facts, now),
        "state": state,
        "reason": resolved["reason"],
        "also": resolved["also"],
        "message": STATE_MESSAGES.get(state, state),
        "terminal": state in TERMINAL_STATES,
        "started_at": facts.get("started_at") or None,
        "assessed_at": facts.get("assessed_at") or None,
        "policy_version": facts.get("policy_version") or None,
        "execution_mode": facts.get("execution_mode") or None,
        "source": source_identity(
            scan_id=facts.get("scan_id"), provider=facts.get("source"),
            locations=facts.get("locations"), scan_snapshot_id=facts.get("scan_snapshot_id")),
        "total_documents": total,
        "total_findings": facts.get("total_findings"),
        "documents": counters,
        "outcome_reasons": reasons,
        # Units are in the KEY, always. "Verified" alone was ambiguous between documents and
        # fixes and was read as both on the same screen (PRD §6C).
        "fixes": {"applied": applied, "verified": verified,
                  "verification_failures": max(0, applied - verified),
                  "documents_verified": len(verified_docs)},
        "delivery": {"stored": corrected_stored, "delivered": delivered,
                     "pending": pending_delivery, "eligible": len(corrected),
                     "latest_at": facts.get("latest_delivery_at") or None},
        "review": {"documents": counters["review"],
                   "items": int(facts.get("review_items") or 0)},
        "throughput": throughput,
        "estimate": estimate,
        "phases": derive_phases(counters, total=total, state=state, applied_fixes=applied,
                                verified_fixes=verified, corrected_stored=corrected_stored,
                                corrected_pending_delivery=pending_delivery),
        "active_attempts": active,
        "retry_at": retry_at.isoformat() if retry_at else None,
        "latest_progress_at": facts.get("latest_progress_at") or None,
        # How old the newest durable progress event may get before the CLIENT calls the panel
        # delayed, and before this server calls the run stalled. Sent rather than hardcoded in
        # the browser so both ends move together.
        "thresholds": {"stall_after_s": stall_after_s, "heartbeat_s": 15, "delayed_after_s": 60},
        "links": facts.get("links") or {},
    }
    violations = check_invariants(snapshot)
    snapshot["integrity"] = {"ok": not violations, "violations": violations,
                             "affected": sorted({v["metric"] for v in violations})}
    return snapshot
