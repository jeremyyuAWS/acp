"""Configurable file disposition (ADR 0003, Phase 3) -- policy CRUD + preview.

PREVIEW ONLY: /disposition/policies/{id}/preview reports which documents a
policy would select. No route here moves, renames, archives, or deletes a
file -- that execution path is a deliberately separate, later decision (see
api/disposition.py's module docstring).

Same access posture as the existing /admin/reset endpoint (system.py): gated
by the app's perimeter auth only, not a per-route admin-role check -- there's
no server-side admin role today. Worth closing before an execute path ships.
"""
from __future__ import annotations
import json
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import core
import disposition

router = APIRouter()


class PolicyCreate(BaseModel):
    name: str
    match: list[dict]
    action: str
    action_config: dict = {}
    requires_approval: bool = True
    enabled: bool = False        # created disabled by default -- an explicit opt-in to enable


@router.post("/disposition/policies")
def create_policy(body: PolicyCreate):
    if body.action not in disposition.ACTIONS:
        raise HTTPException(422, f"action must be one of {sorted(disposition.ACTIONS)}")
    try:
        disposition.validate_match(body.match)
    except ValueError as e:
        raise HTTPException(422, str(e))
    policy_id = uuid.uuid4().hex[:12]
    core.store.create_disposition_policy(
        policy_id, name=body.name, match=json.dumps(body.match), action=body.action,
        action_config=json.dumps(body.action_config), requires_approval=body.requires_approval,
        enabled=body.enabled)
    core.store.log_decision("admin", "disposition.policy_created", detail=body.name)
    return core.store.get_disposition_policy(policy_id)


@router.get("/disposition/policies")
def list_policies():
    return core.store.list_disposition_policies()


@router.put("/disposition/policies/{policy_id}/enabled")
def set_policy_enabled(policy_id: str, enabled: bool):
    if core.store.get_disposition_policy(policy_id) is None:
        raise HTTPException(404, "policy not found")
    core.store.set_disposition_policy_enabled(policy_id, enabled)
    core.store.log_decision("admin", f"disposition.policy_{'enabled' if enabled else 'disabled'}",
                            detail=policy_id)
    return core.store.get_disposition_policy(policy_id)


@router.post("/disposition/policies/{policy_id}/preview")
def preview_policy(policy_id: str):
    """Dry run: which documents would this policy select, right now? Never writes
    disposition_audit and never touches a file -- read-only by construction."""
    policy = core.store.get_disposition_policy(policy_id)
    if policy is None:
        raise HTTPException(404, "policy not found")
    match = json.loads(policy["match"])
    docs = core.store.list_all_documents()
    selected = [d for d in docs if disposition.matches(d, match)]
    return {"policy_id": policy_id, "action": policy["action"],
           "would_match": len(selected), "documents": selected}
