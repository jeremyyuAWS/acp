"""Evidence freshness (PRD §12).

Evidence goes stale. A keyboard test run against build 4821 says nothing about build 4990, and a
"Supports" claim resting on it is exactly the kind of unsupported claim the PRD opens by naming.
PRD §12 lists five triggers; this module computes all five.

STALENESS IS DERIVED, NEVER STORED AS THE SOURCE OF TRUTH
----------------------------------------------------------
A stored `is_stale` boolean is wrong the instant anything it depends on moves — and every one of
its dependencies moves routinely. Edit the report's product version and every evidence row's
staleness changes, with no write to any evidence row to trigger a recompute. Reopen a finding and
the same thing happens from the other direction.

So `evaluate()` takes the report and the evidence and returns the stale set. `acr_model.Evidence.
stale_reason` exists only as a cache for display and audit; it is never consulted to decide whether
a report may publish. acr_rules takes `stale_ids` as a parameter for this reason — the decision
path is handed a freshly computed set, not a column it trusts.

WHAT STALE DOES AND DOES NOT DO
--------------------------------
PRD §12, last line: a stale record "remains visible for audit history but cannot independently
support publication". Both halves matter. Stale evidence is never hidden and never deleted — it is
excluded from the inputs to a conformance decision, and shown, marked, everywhere else.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

# Default validity window (PRD §12: "Its configured validity period expired"). 180 days is a
# starting policy, not a standard — it is per-report configurable via
# acr_report.evidence_validity_days, and this is only the fallback when a report sets none.
DEFAULT_VALIDITY_DAYS = 180

# The five PRD §12 triggers, as stable tokens. Stored on the row and rendered verbatim, so a
# reviewer reading a stale badge learns WHICH rule fired rather than just that one did.
STALE_VERSION = "different_product_version"
STALE_COMPONENT_CHANGED = "component_changed_after_test"
STALE_EXPIRED = "validity_period_expired"
STALE_CONTRADICTED = "contradicted_by_regression"
STALE_REOPENED = "resolved_finding_reopened"


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def evaluate(report: dict, evidence, *, now: datetime | None = None,
             changed_workflows: set[str] | None = None,
             reopened_criteria: set[str] | None = None) -> dict[str, str]:
    """Which evidence rows are stale, and why. Returns {evidence_id: reason}.

    `changed_workflows` and `reopened_criteria` are injected rather than queried so this stays a
    pure function — the caller (acr_validation, the routes layer) owns the lookups, and the rules
    stay testable against constructed records with no database.
    """
    now = now or datetime.now(timezone.utc)
    changed = changed_workflows or set()
    reopened = reopened_criteria or set()
    window = timedelta(days=int(report.get("evidence_validity_days") or DEFAULT_VALIDITY_DAYS))
    report_version = (report.get("product_version") or "").strip()
    report_build = (report.get("build_id") or "").strip()

    stale: dict[str, str] = {}
    # Newest non-stale FAILING row per criterion — used for the "contradicted by a regression scan"
    # trigger below. Computed once rather than per-row.
    newest_fail: dict[str, str] = {}
    for e in evidence:
        if e.result == "fail":
            prev = newest_fail.get(e.criterion_num)
            if prev is None or e.tested_at > prev:
                newest_fail[e.criterion_num] = e.tested_at

    for e in evidence:
        ev_version = (getattr(e, "product_version", None) or "").strip()
        ev_build = (getattr(e, "build_id", None) or "").strip()

        # 1. A different product version. Only decidable when BOTH sides name one — evidence with
        #    no recorded version is not silently trusted, but it is not called stale either; that
        #    is a metadata GAP, and acr_validation reports it as one. Two different words for two
        #    different problems.
        if report_version and ev_version and ev_version != report_version:
            stale[e.id] = STALE_VERSION
            continue

        # 2. The associated screen or component changed after testing. Same-version builds still
        #    move; a build identifier mismatch, or an explicitly-changed workflow, is that.
        if report_build and ev_build and ev_build != report_build:
            stale[e.id] = STALE_COMPONENT_CHANGED
            continue
        if getattr(e, "workflow", None) and e.workflow in changed:
            stale[e.id] = STALE_COMPONENT_CHANGED
            continue

        # 3. Validity window elapsed.
        tested = _parse(getattr(e, "tested_at", None))
        if tested is not None and (now - tested) > window:
            stale[e.id] = STALE_EXPIRED
            continue

        # 4. A regression scan contradicts it: a PASSING row older than the newest FAILING row for
        #    the same criterion is no longer load-bearing. Note the asymmetry — a failure is not
        #    made stale by a later pass. That case is "resolved", and acr_rules.open_failures
        #    handles it, because a resolution needs to be visible as a resolution rather than
        #    quietly vanishing from the evidence list.
        if e.result == "pass":
            nf = newest_fail.get(e.criterion_num)
            if nf and nf > e.tested_at:
                stale[e.id] = STALE_CONTRADICTED
                continue

        # 5. A previously resolved finding reopened.
        if e.criterion_num in reopened and e.result == "pass":
            stale[e.id] = STALE_REOPENED
            continue

    return stale


def annotate(report: dict, evidence, **kw) -> list:
    """`evidence` with `stale_reason` filled in for display. Returns the same objects, mutated.

    For rendering and audit only. Never call this and then read `stale_reason` to make a decision —
    pass `evaluate()`'s result into acr_rules as `stale_ids` instead. See the module docstring.
    """
    stale = evaluate(report, evidence, **kw)
    for e in evidence:
        e.stale_reason = stale.get(e.id)
    return evidence
