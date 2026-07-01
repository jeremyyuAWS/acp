"""Disposition policy matching (ADR 0003, Phase 3): pure validation + evaluation
logic, no DB access (api/store.py owns persistence, matching this module's
seam with api/documents.py in Phase 1).

PREVIEW ONLY in this phase -- matches() only tells you which documents a
policy WOULD select. It never touches a file. The real move/rename/archive/
delete execution path is a separate, later decision (ADR 0003's own note:
"Disposition that deletes/moves customer files is irreversible — gate behind
requires_approval + the immutable disposition_audit, and never act without an
explicit policy the admin enabled").

Conditions are evaluated in Python over already-fetched document rows, not
interpolated into SQL — this sidesteps building (and having to audit) a
dynamic-SQL predicate compiler for something admin-authored and potentially
complex, at the cost of fetching the full documents table per preview. Fine
at today's scale; revisit if/when that table gets large enough to matter.
"""
from __future__ import annotations
from datetime import datetime, timezone

ACTIONS = {"leave", "archive", "rename", "move", "delete"}

FIELDS = {"department", "business_criticality", "regulatory_tags", "triage_score",
         "source", "owner", "age_days"}

_OPS = {
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
    "gt": lambda a, b: a is not None and b is not None and a > b,
    "gte": lambda a, b: a is not None and b is not None and a >= b,
    "lt": lambda a, b: a is not None and b is not None and a < b,
    "lte": lambda a, b: a is not None and b is not None and a <= b,
    "contains": lambda a, b: b is not None and str(b).lower() in str(a or "").lower(),
}


def validate_match(match: list[dict]) -> None:
    """Raise ValueError on a malformed or unsafe match predicate. Call before
    persisting a policy — matches() itself doesn't re-validate on every call."""
    if not isinstance(match, list):
        raise ValueError("match must be a list of conditions")
    for cond in match:
        if not isinstance(cond, dict) or "field" not in cond or "op" not in cond:
            raise ValueError(f"malformed condition: {cond!r}")
        if cond["field"] not in FIELDS:
            raise ValueError(f"unknown field: {cond['field']!r} (allowed: {sorted(FIELDS)})")
        if cond["op"] not in _OPS:
            raise ValueError(f"unknown op: {cond['op']!r} (allowed: {sorted(_OPS)})")


def _age_days(created_at: str | None) -> int | None:
    if not created_at:
        return None
    try:
        created = datetime.fromisoformat(created_at)
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - created).days
    except Exception:
        return None


def matches(doc: dict, match: list[dict]) -> bool:
    """True iff `doc` satisfies every condition (AND) in `match`. Assumes
    validate_match already passed — does not re-check field/op safety."""
    values = {**doc, "age_days": _age_days(doc.get("created_at"))}
    for cond in match:
        if not _OPS[cond["op"]](values.get(cond["field"]), cond.get("value")):
            return False
    return True
