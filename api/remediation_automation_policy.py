"""Authoritative contract for the remediation automation-policy preview.

The UI may explain this result, but it must never re-classify a finding.  In particular,
``primary_reason`` is a single value (or ``None`` when the evidence is insufficient); consumers
must not turn an unknown into a more reassuring reason.
"""
from __future__ import annotations

from collections import defaultdict
from enum import Enum
from typing import Any, Iterable


class RoutingReason(str, Enum):
    CONFIDENCE_BELOW_THRESHOLD = "confidence_below_threshold"
    SUBJECTIVE_DECISION = "subjective_decision"
    MISSING_EVIDENCE = "missing_evidence"
    UNSUPPORTED_REMEDIATION = "unsupported_remediation"
    SAFETY_RULE = "safety_rule"
    FAILED_VERIFICATION = "failed_verification"


REASON_ORDER = tuple(reason.value for reason in RoutingReason)
LANES = frozenset({"automatic", "review", "protected"})


def _text(value: Any) -> str | None:
    value = str(value or "").strip()
    return value or None


def _criterion(row: dict) -> str | None:
    value = _text(row.get("criterion") or row.get("rule_id") or row.get("ruleId"))
    if not value:
        return None
    return value.removeprefix("WCAG_").removeprefix("SC_").replace("_", ".")


def _format(row: dict) -> str | None:
    explicit = _text(row.get("format"))
    if explicit:
        return explicit.lower()
    filename = _text(row.get("file"))
    if not filename or "." not in filename:
        return None
    return filename.rsplit(".", 1)[1].lower()


def primary_reason(row: dict) -> str | None:
    """Return exactly one recorded/derivable reason, never a guessed fallback.

    An explicit backend reason wins.  Legacy evidence is evaluated in safety precedence: a failed
    verification and a hard safety rule are stronger explanations than proposal characteristics.
    """
    explicit = _text(row.get("primary_reason") or row.get("primaryReason"))
    if explicit in REASON_ORDER:
        return explicit
    if row.get("verification_failed") is True or row.get("verificationFailed") is True:
        return RoutingReason.FAILED_VERIFICATION.value
    if row.get("safety_rule") is True or row.get("safetyRule") is True or row.get("rejectedFix") is True:
        return RoutingReason.SAFETY_RULE.value
    supported = row.get("remediation_supported", row.get("remediationSupported"))
    if supported is False or row.get("hasProposal") is False:
        return RoutingReason.UNSUPPORTED_REMEDIATION.value
    evidence = row.get("evidence_complete", row.get("evidenceComplete"))
    if evidence is False:
        return RoutingReason.MISSING_EVIDENCE.value
    if row.get("subjective") is True or row.get("subjective_decision") is True:
        return RoutingReason.SUBJECTIVE_DECISION.value
    confidence = row.get("confidence")
    threshold = row.get("confidence_threshold", row.get("confidenceThreshold"))
    if isinstance(confidence, (int, float)) and isinstance(threshold, (int, float)) and confidence < threshold:
        return RoutingReason.CONFIDENCE_BELOW_THRESHOLD.value
    return None


def _lane(row: dict, reason: str | None) -> str:
    # The evaluator's lane is an independent policy outcome; the reason explains why that lane
    # was chosen.  Do not silently move a recorded review item into protected (or vice versa).
    lane = _text(row.get("lane"))
    if lane in LANES:
        return lane
    if reason in {RoutingReason.SAFETY_RULE.value, RoutingReason.FAILED_VERIFICATION.value}:
        return "protected"
    if reason is not None:
        return "review"
    # Unknown is conservatively open/protected, but remains unknown in the reason contract.
    return "protected"


def _count(rows: Iterable[dict]) -> dict[str, int]:
    rows = list(rows)
    return {"findings": len(rows), "files": len({_text(r.get("file")) for r in rows if _text(r.get("file"))})}


def build_policy_preview(findings: Iterable[dict] | None, *, level: int | None = None) -> dict:
    """Build the versioned, internally checkable policy-preview response."""
    rows = [dict(row) for row in (findings or []) if isinstance(row, dict)]
    routed: list[dict] = []
    by_lane: dict[str, list[dict]] = defaultdict(list)
    by_reason: dict[str, list[dict]] = defaultdict(list)
    unknown: list[dict] = []
    for row in rows:
        reason = primary_reason(row)
        lane = _lane(row, reason)
        normalized = {**row, "primary_reason": reason, "lane": lane,
                      "criterion": _criterion(row), "format": _format(row)}
        routed.append(normalized)
        by_lane[lane].append(normalized)
        if reason is None:
            if lane != "automatic":
                unknown.append(normalized)
        else:
            by_reason[reason].append(normalized)

    reasons = []
    for reason in REASON_ORDER:
        bucket = by_reason[reason]
        if not bucket:
            continue
        criteria: dict[str, list[dict]] = defaultdict(list)
        formats: dict[str, list[dict]] = defaultdict(list)
        for row in bucket:
            criteria[row["criterion"] or "Unknown"].append(row)
            formats[row["format"] or "unknown"].append(row)
        reasons.append({
            "reason": reason, **_count(bucket),
            "criteria": [{"criterion": key, **_count(value)} for key, value in sorted(criteria.items())],
            "formats": [{"format": key, **_count(value)} for key, value in sorted(formats.items())],
        })

    lanes = {lane: _count(by_lane[lane]) for lane in ("automatic", "review", "protected")}
    opened = _count(routed)
    lane_sum = sum(lanes[lane]["findings"] for lane in lanes)
    return {
        "contract_version": "remediation-automation-policy-preview.v1",
        "level": level,
        "open": opened,
        "lanes": lanes,
        "reasons": reasons,
        "findings": routed,
        "integrity": {
            "open_equals_lane_sum": opened["findings"] == lane_sum,
            "reason_is_mutually_exclusive": True,
            "unknown_primary_reason": _count(unknown),
            "complete": opened["findings"] == lane_sum and not unknown,
        },
    }
