"""Document-centric layer (ADR 0003, Phase 1): stable document identity across
scans + a server-side, white-box triage score.

`file_records` is a per-scan snapshot; `documents` (api/store.py) is the
long-lived governed object a snapshot upserts into. This module holds the two
pieces of logic that belong to neither the scanner nor the store: how a
document's identity is resolved, and how urgent it is.
"""
from __future__ import annotations
import hashlib


def resolve_doc_id(source: str, drive_file_id: str | None, path: str, content_hash: str | None) -> str:
    """Stable identity for a document, independent of scan_id.

    Prefers the source's own stable id (survives rename/move — a Drive file_id
    doesn't change when the file is renamed). Falls back to source+content_hash
    for sources with no stable id (or local corpus files); this changes if the
    bytes change, which is the correct behavior for a fallback with no better
    signal — a renamed-but-unchanged local file is indistinguishable from a new
    one without a stable id from the source.
    """
    if drive_file_id:
        return f"{source}:{drive_file_id}"
    basis = content_hash or path
    return f"{source}:{hashlib.sha256(basis.encode()).hexdigest()[:24]}"


# Weights for the parts of triage we can actually compute server-side today
# (age/department/regulatory_tags/business_criticality need connector work the
# real Drive/SharePoint scan doesn't do yet — ADR 0003's own "Costs/risks").
# Each weight is out of 100; the rationale string cites which fired.
_PII_SEVERITY_WEIGHT = {"critical": 35, "moderate": 20, "low": 8}


def compute_triage_score(*, compliance_score: int | None, pii_severity: str | None,
                         pii_total: int, age_days: int | None, skipped_rules: int = 0) -> tuple[int, str]:
    """A 0-100 urgency score + a plain-language reason it's white-box (ADR 0003
    Ideal 9 — every rank must be explainable, never a client-side guess)."""
    score = 0
    reasons: list[str] = []

    if compliance_score is not None:
        gap = max(0, 100 - compliance_score)
        score += round(gap * 0.45)
        if gap > 0:
            reasons.append(f"compliance score {compliance_score}/100")

    if pii_total:
        w = _PII_SEVERITY_WEIGHT.get((pii_severity or "").lower(), 8)
        score += w
        reasons.append(f"{pii_total} sensitive-data finding{'s' if pii_total != 1 else ''} ({pii_severity or 'low'})")

    if age_days is not None and age_days > 180:
        bump = min(15, (age_days - 180) // 60 * 5)
        if bump:
            score += bump
            reasons.append(f"first seen {age_days} days ago")

    if skipped_rules:
        score += min(10, skipped_rules * 2)
        reasons.append(f"{skipped_rules} rule{'s' if skipped_rules != 1 else ''} skipped (uncertain score)")

    score = min(100, score)
    rationale = (f"{score}/100 — " + ", ".join(reasons)) if reasons else f"{score}/100 — no risk signals found"
    return score, rationale
