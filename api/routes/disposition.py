"""Configurable file disposition (ADR 0003, Phase 3) -- policy CRUD, preview,
and the EXECUTE path (approved 2026-07-02).

Execution flow: /execute evaluates an ENABLED policy against the documents
table; matches either become pending_approval rows in the append-only
disposition_audit (requires_approval policies — the default) or are actioned
immediately. /approvals lists the pending queue; approve performs the action,
reject records the refusal. Every outcome lands in disposition_audit.

Safety posture: all mutating routes are owner-gated via _require_admin (the
per-route admin check this module's preview-era docstring asked for), delete
is always Drive trash (never permanent — see disposition.execute_action), and
a doc/policy pair with a live outcome (pending or applied) is never re-queued.
"""
from __future__ import annotations
import json
import uuid

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

import core
import disposition
from .system import _require_admin

router = APIRouter()


def _drive_svc(request: Request):
    """Drive client from the caller's token header, or None (leave-only mode)."""
    token = request.headers.get("x-drive-token")
    if not token:
        return None
    import handlers
    return handlers._drive_client(token)


class PolicyCreate(BaseModel):
    name: str
    match: list[dict]
    action: str
    action_config: dict = {}
    requires_approval: bool = True
    enabled: bool = False        # created disabled by default -- an explicit opt-in to enable


@router.post("/disposition/policies")
def create_policy(body: PolicyCreate, request: Request):
    _require_admin(request)
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
def set_policy_enabled(policy_id: str, enabled: bool, request: Request):
    _require_admin(request)
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


@router.post("/disposition/policies/{policy_id}/execute")
def execute_policy(policy_id: str, request: Request):
    """Run an ENABLED policy for real. requires_approval matches queue as
    pending_approval; the rest are actioned immediately. Idempotent per
    (doc, policy): a pending or applied outcome is never re-queued."""
    _require_admin(request)
    policy = core.store.get_disposition_policy(policy_id)
    if policy is None:
        raise HTTPException(404, "policy not found")
    if not policy.get("enabled"):
        raise HTTPException(409, "policy is disabled — enable it before executing")
    match = json.loads(policy["match"])
    cfg = json.loads(policy.get("action_config") or "{}")
    svc = _drive_svc(request)
    if policy["action"] != "leave" and not policy.get("requires_approval") and svc is None:
        raise HTTPException(400, "this policy acts on Drive files immediately — "
                                 "connect Google Drive first")
    summary = {"matched": 0, "pending_approval": 0, "applied": 0, "failed": 0, "skipped": 0}
    for doc in core.store.list_all_documents():
        if not disposition.matches(doc, match):
            continue
        summary["matched"] += 1
        if core.store.doc_has_disposition(doc["doc_id"], policy_id):
            summary["skipped"] += 1
            continue
        audit_id = uuid.uuid4().hex[:12]
        if policy.get("requires_approval"):
            core.store.create_disposition_audit(
                audit_id, doc_id=doc["doc_id"], policy_id=policy_id,
                action=policy["action"], result="pending_approval",
                detail=f"queued by policy '{policy['name']}' — awaiting approval")
            summary["pending_approval"] += 1
        else:
            result, detail = disposition.execute_action(doc, policy["action"], cfg, svc)
            core.store.create_disposition_audit(
                audit_id, doc_id=doc["doc_id"], policy_id=policy_id,
                action=policy["action"], result=result, detail=detail)
            summary[result] += 1
    core.store.log_decision("admin", "disposition.policy_executed",
                            detail=f"{policy['name']}: {summary}")
    return {"policy_id": policy_id, **summary}


@router.get("/disposition/audit")
def disposition_audit(request: Request, limit: int = Query(200, ge=1, le=1000)):
    """Full disposition history, newest first — the visible face of the append-only
    audit table (pending, applied, rejected, failed alike)."""
    _require_admin(request)
    return core.store.list_disposition_audit(limit=limit)


@router.get("/disposition/approvals")
def list_approvals(request: Request):
    """The pending-approval queue — every doc a requires_approval policy selected
    that no admin has decided on yet."""
    _require_admin(request)
    return core.store.list_disposition_audit(result="pending_approval")


@router.post("/disposition/approvals/{audit_id}/approve")
def approve_disposition(audit_id: str, request: Request):
    """Perform the queued action. The audit row moves to applied or failed."""
    _require_admin(request)
    row = core.store.get_disposition_audit(audit_id)
    if row is None or row["result"] != "pending_approval":
        raise HTTPException(404, "no pending approval with that id")
    policy = core.store.get_disposition_policy(row["policy_id"]) or {}
    cfg = json.loads(policy.get("action_config") or "{}")
    docs = {d["doc_id"]: d for d in core.store.list_all_documents()}
    doc = docs.get(row["doc_id"])
    if doc is None:
        core.store.set_disposition_audit_result(audit_id, "failed", "document no longer exists")
        raise HTTPException(410, "document no longer exists")
    result, detail = disposition.execute_action(doc, row["action"], cfg, _drive_svc(request))
    core.store.set_disposition_audit_result(audit_id, result, detail)
    core.store.log_decision("admin", f"disposition.{result}",
                            detail=f"{row['action']} {row['doc_id']}: {detail}"[:200])
    return core.store.get_disposition_audit(audit_id)


@router.post("/disposition/approvals/{audit_id}/reject")
def reject_disposition(audit_id: str, request: Request):
    """Decline the queued action. Recorded (result=rejected), never re-queued
    automatically — a later execute run may propose it again only if the doc
    still matches, since rejected rows don't block re-evaluation."""
    _require_admin(request)
    row = core.store.get_disposition_audit(audit_id)
    if row is None or row["result"] != "pending_approval":
        raise HTTPException(404, "no pending approval with that id")
    core.store.set_disposition_audit_result(audit_id, "rejected", "declined by admin")
    core.store.log_decision("admin", "disposition.rejected",
                            detail=f"{row['action']} {row['doc_id']}")
    return core.store.get_disposition_audit(audit_id)
