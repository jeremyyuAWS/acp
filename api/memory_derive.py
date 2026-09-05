"""ADR 0021 §D — nightly Review Memory derivation job.

Reads each org's HITL events from the last 30 days, groups by (rule_id, file_ext),
and proposes org_memory rows (status='proposed') for pairs that cross the maturity
thresholds. The job is idempotent: existing proposed or active rules for a
(rule_id, format) pair are skipped.

Proposed rows are inert until an admin accepts them via set_org_memory_status →
'active'. No memory rule ever becomes active without explicit approval; this job
only surfaces candidates.

Entry point: run_derivation(store) → dict with counts.
"""
from __future__ import annotations

import json
import statistics
from collections import defaultdict
from datetime import datetime, timezone, timedelta

_WINDOW_DAYS = 30
_MIN_APPROVALS = 10
_MAX_EDIT_RATE = 0.20
_MIN_APPROVAL_RATE = 0.90


def _file_ext(filename: str) -> str | None:
    """Return lowercase extension (no dot) or None if no dot in filename."""
    if not filename or "." not in filename:
        return None
    return filename.rsplit(".", 1)[-1].lower()


def _guidance(rule_id: str, fmt: str | None, evidence: dict) -> str:
    """Derive a human-readable prompt-fragment from reviewing behaviour signals.

    The fragment describes what reviewers actually accepted — no invented advice.
    It is short enough to embed in an AI proposer's system prompt without crowding
    the primary instruction.
    """
    appr = evidence.get("of", 0)
    edited = evidence.get("edited", 0)
    delta = evidence.get("median_delta_chars", 0)
    fmt_label = f"{fmt.upper()} " if fmt else ""

    if edited == 0:
        # Zero edits in N approvals — reviewers accepted AI output verbatim.
        return (
            f"For {fmt_label}{rule_id}: reviewers accepted AI-generated text without edits "
            f"across {appr} approvals — the current style matches reviewer expectations."
        )

    edit_pct = round(100 * edited / appr) if appr else 0
    if delta < -20:
        return (
            f"For {fmt_label}{rule_id}: when reviewers edited ({edit_pct}% of approvals) "
            f"they shortened the AI text by a median of {abs(delta)} characters — "
            f"prefer concise wording and avoid redundant preamble."
        )
    if delta > 20:
        return (
            f"For {fmt_label}{rule_id}: when reviewers edited ({edit_pct}% of approvals) "
            f"they added a median of {delta} characters — "
            f"include more descriptive detail in the proposed text."
        )
    return (
        f"For {fmt_label}{rule_id}: reviewers made minor edits in {edit_pct}% of approvals "
        f"(median change ±{abs(delta)} characters) — the AI output is close to target; "
        f"small phrasing adjustments may still be needed."
    )


def run_derivation(store) -> dict:
    """Iterate every org, find mature (rule_id, format) pairs, propose memory rows.

    Returns a summary dict:
      orgs_scanned   — number of orgs with at least one hitl event in the window
      pairs_proposed — new org_memory rows written (status='proposed')
      pairs_skipped  — pairs that passed maturity but already had a proposed/active rule
    """
    since_iso = (
        datetime.now(timezone.utc) - timedelta(days=_WINDOW_DAYS)
    ).isoformat()

    total_orgs = 0
    total_proposed = 0
    total_skipped = 0

    for org in store.list_org_owners():
        events = store.list_hitl_events_for_org(org, since_iso=since_iso)
        if not events:
            continue
        total_orgs += 1

        # Bucket events by (rule_id, file_ext)
        buckets: dict[tuple[str, str | None], dict] = defaultdict(
            lambda: {
                "approved": 0,
                "rejected": 0,
                "edited": 0,
                "delta_chars": [],
            }
        )
        for e in events:
            rule = (e.get("rule_id") or "").strip()
            ext = _file_ext(e.get("file") or "")
            if not rule:
                continue
            b = buckets[(rule, ext)]
            action = e.get("action") or ""
            if action in ("approve", "edit"):
                b["approved"] += 1
            elif action == "reject":
                b["rejected"] += 1
            if e.get("edited"):
                b["edited"] += 1
                ai_v = e.get("ai_value") or ""
                fin_v = e.get("final_value") or ""
                if ai_v and fin_v:
                    b["delta_chars"].append(len(fin_v) - len(ai_v))

        # Load existing proposed/active rules so we can skip duplicates.
        # Keyed as (rule_id, format) — None matches None.
        existing: set[tuple[str | None, str | None]] = {
            (r.get("rule_id"), r.get("format"))
            for r in store.list_org_memory(org)
            if r.get("status") in ("proposed", "active")
        }

        for (rule_id, ext), b in buckets.items():
            appr = b["approved"]
            edited = b["edited"]
            decided = appr + b["rejected"]
            if decided == 0:
                continue
            approval_rate = appr / decided
            edit_rate = edited / appr if appr > 0 else 1.0

            if (
                appr < _MIN_APPROVALS
                or edit_rate > _MAX_EDIT_RATE
                or approval_rate < _MIN_APPROVAL_RATE
            ):
                continue

            if (rule_id, ext) in existing:
                total_skipped += 1
                continue

            deltas = b["delta_chars"]
            median_delta = int(statistics.median(deltas)) if deltas else 0
            evidence = {
                "rule": rule_id,
                "format": ext,
                "edited": edited,
                "of": appr,
                "median_delta_chars": median_delta,
                "window_days": _WINDOW_DAYS,
            }
            guidance = _guidance(rule_id, ext, evidence)
            store.add_org_memory(
                org,
                "derived",
                guidance,
                rule_id=rule_id,
                format=ext,
                status="proposed",
                evidence=json.dumps(evidence),
                author="system:memory-derive",
            )
            total_proposed += 1

    result = {
        "orgs_scanned": total_orgs,
        "pairs_proposed": total_proposed,
        "pairs_skipped": total_skipped,
    }
    if total_proposed or total_skipped:
        print(
            f"[memory-derive] proposed={total_proposed} skipped={total_skipped} "
            f"orgs={total_orgs}",
            flush=True,
        )
    return result
