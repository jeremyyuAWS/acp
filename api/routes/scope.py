"""Scope-rule CRUD (Discover/Assess Lifecycle PRD §4.4 / AC-09, Phase C4c).

A *scope rule* targets files by folder / owner / department / SharePoint Content Type and
assigns a WCAG code-set
(a subset of Core-17), so different parts of the estate can be assessed against different
criteria. The pure resolution logic lives in `api/scope_resolver.py` and persistence in
`api/store.py` (both merged in C4a); this module is the owner-gated control surface over
those, plus a tiny `/scope/selectors` helper the editor UI renders from.

Every mutating route validates the rule with `scope_resolver.validate_scope_rule` against
the Core-17 set BEFORE it touches the store, so a rule can never scope a file to a
criterion the product does not track. Reads are open; writes are owner-only (the same
`_require_admin` gate the platform-admin endpoints use in `routes/system.py`).
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

import core
import scope_resolver
import wcag_codeset
from .system import _require_admin

router = APIRouter()


def _allowed_codes() -> set[str]:
    """The Core-17 set every scope rule's codes must be a subset of."""
    return set(wcag_codeset.core17_codes())


class ScopeRuleIn(BaseModel):
    """The editable fields of a scope rule (the rule_id and created_by are server-set)."""
    name: str = ""
    selector: str
    value: str
    codes: list[str] = Field(default_factory=list)
    priority: int = 0
    is_override: bool = False
    enabled: bool = True


class EnabledIn(BaseModel):
    enabled: bool


def _serialize(rule: dict) -> dict:
    """The rule as the API returns it — codes already decoded to a list by the store, the
    override/enabled flags already bools. We pass the store row through unchanged so the
    ordering (priority desc, then name) the store applies is what the UI receives."""
    return {
        "rule_id": rule.get("rule_id"),
        "name": rule.get("name") or "",
        "selector": rule.get("selector"),
        "value": rule.get("value"),
        "codes": list(rule.get("codes") or []),
        "priority": int(rule.get("priority") or 0),
        "is_override": bool(rule.get("is_override")),
        "enabled": bool(rule.get("enabled")),
        "created_at": rule.get("created_at"),
        "created_by": rule.get("created_by"),
    }


@router.get("/scope/selectors")
def scope_selectors():
    """The building blocks the rule editor needs: the allowed selectors and the Core-17
    catalog (code + name + lane formats) to pick codes from. Read-only, no gate."""
    return {
        "selectors": list(scope_resolver.SELECTORS),
        "codes": wcag_codeset.core17_catalog(),
    }


@router.get("/scope/rules")
def list_scope_rules():
    """All scope rules, codes decoded, in the store's priority-desc / name order. Read-only."""
    return {"rules": [_serialize(r) for r in core.store.list_scope_rules()]}


@router.post("/scope/rules")
def create_scope_rule(body: ScopeRuleIn, request: Request):
    """Create a scope rule (owner-only). Validates the rule against the Core-17 set before
    persisting; a malformed rule is a 400 carrying the validator's own message. The
    rule_id is server-generated so two editors can never collide on one."""
    _require_admin(request)
    rule = {
        "selector": body.selector,
        "value": body.value,
        "codes": list(body.codes),
        "priority": body.priority,
        "is_override": body.is_override,
        "enabled": body.enabled,
    }
    try:
        scope_resolver.validate_scope_rule(rule, _allowed_codes())
    except ValueError as e:
        raise HTTPException(400, str(e))

    rule_id = uuid.uuid4().hex
    created_by = getattr(request.state, "user_email", None) or "demo"
    core.store.create_scope_rule(
        rule_id, name=body.name or "", selector=body.selector, value=body.value,
        codes=list(body.codes), priority=body.priority, is_override=body.is_override,
        enabled=body.enabled, created_by=created_by,
    )
    created = core.store.get_scope_rule(rule_id)
    return _serialize(created) if created else {"rule_id": rule_id}


@router.patch("/scope/rules/{rule_id}")
def set_scope_rule_enabled(rule_id: str, body: EnabledIn, request: Request):
    """Enable or disable one rule (owner-only). 404 if it does not exist."""
    _require_admin(request)
    if core.store.get_scope_rule(rule_id) is None:
        raise HTTPException(404, "scope rule not found")
    core.store.set_scope_rule_enabled(rule_id, body.enabled)
    return _serialize(core.store.get_scope_rule(rule_id))


@router.delete("/scope/rules/{rule_id}")
def delete_scope_rule(rule_id: str, request: Request):
    """Delete one rule (owner-only). 404 if it does not exist."""
    _require_admin(request)
    if core.store.get_scope_rule(rule_id) is None:
        raise HTTPException(404, "scope rule not found")
    core.store.delete_scope_rule(rule_id)
    return {"deleted": rule_id}
