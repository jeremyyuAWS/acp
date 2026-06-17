"""Result classification + scoring for acp scans.

Turns the Track-A finding into a product rule: a file whose analysis was incomplete
is NEVER reported as a clean pass.
  - ERROR     : the file could not be opened/analysed at all -> unscored, not a pass.
  - UNCERTAIN : it analysed but >=1 rule threw and was skipped -> the score is an
                UPPER BOUND (a skipped rule may hide issues); cannot be certified.
  - ANALYSED  : full run, score is trustworthy; only this can be certified compliant.

This is the seed of the Phase-4 versioned rubric.
"""
from __future__ import annotations
from enum import Enum

SEVERITY_PENALTY = {"CRITICAL": 25, "SERIOUS": 15, "MODERATE": 8, "MINOR": 3}
DEFAULT_PENALTY = 5
COMPLIANT_THRESHOLD = 90


class Status(str, Enum):
    ANALYSED = "analysed"
    UNCERTAIN = "uncertain"
    ERROR = "error"


def classify(succeeded: bool, error_count: int) -> Status:
    if not succeeded:
        return Status.ERROR
    return Status.UNCERTAIN if error_count > 0 else Status.ANALYSED


def raw_score(issues) -> int:
    return max(0, 100 - sum(SEVERITY_PENALTY.get(i["severity"], DEFAULT_PENALTY) for i in issues))


def assess(succeeded: bool, issues: list, errors: list) -> dict:
    status = classify(succeeded, len(errors))
    score = None if status is Status.ERROR else raw_score(issues)
    return {
        "status": status.value,
        "score": score,
        "skipped_rules": len(errors),
        # only a fully-analysed file at/above threshold can be certified compliant
        "compliant": status is Status.ANALYSED and score is not None and score >= COMPLIANT_THRESHOLD,
        "score_is_upper_bound": status is Status.UNCERTAIN,
    }


def render_score(a: dict) -> str:
    if a["status"] == "error":
        return "n/a (could not analyse)"
    if a["status"] == "uncertain":
        return f"<={a['score']} (UNCERTAIN: {a['skipped_rules']} skipped)"
    return str(a["score"])
