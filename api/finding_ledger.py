"""Stable identities and reconciliation rules for assessed accessibility findings."""
from __future__ import annotations

import hashlib
import json
import re


DISPOSITIONS = (
    "resolved_verified",
    "awaiting_review",
    "approved_pending_verification",
    "unchanged_no_fix",
    "remediation_failed",
    "excluded_by_policy",
    "superseded_by_reassessment",
)


def normalize_instance_key(value: object, *, ordinal: int) -> str:
    """Return a deterministic locator without preserving incidental whitespace."""
    text = re.sub(r"\s+", " ", str(value or "").strip()).casefold()
    return text or f"aggregate-instance:{ordinal}"


def stable_finding_id(document_id: str, rule_id: str, instance_key: str) -> str:
    encoded = json.dumps(
        ["finding-v1", document_id, rule_id, instance_key],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode()).hexdigest()


def reconcile(assessed: int, counts: dict[str, int], *, rows: int) -> dict:
    normalized = {key: int(counts.get(key) or 0) for key in DISPOSITIONS}
    accounted = sum(normalized.values())
    violations = []
    if rows != assessed:
        violations.append({"code": "ledger_cardinality", "assessed": assessed, "rows": rows})
    if accounted > assessed:
        violations.append({"code": "finding_overcount", "assessed": assessed,
                           "accounted": accounted})
    exact = not violations and rows == assessed and accounted == assessed
    return {
        "assessed": assessed,
        "resolved_verified": normalized["resolved_verified"],
        "awaiting_review": normalized["awaiting_review"],
        "approved_pending_verification": normalized["approved_pending_verification"],
        "unchanged_no_fix": normalized["unchanged_no_fix"],
        "failed": normalized["remediation_failed"],
        "excluded": normalized["excluded_by_policy"],
        "superseded": normalized["superseded_by_reassessment"],
        "accounted": accounted,
        "unaccounted": max(0, assessed - accounted),
        "exact": exact,
        "violations": violations,
    }
