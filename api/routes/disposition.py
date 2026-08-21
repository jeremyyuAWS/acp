"""Configurable file disposition (ADR 0003, Phase 3) -- policy CRUD, preview,
and the EXECUTE path (approved 2026-07-02).

Execution flow: /execute evaluates an ENABLED policy against the documents
table; matches either become pending_approval rows in the append-only
disposition_audit (requires_approval policies — the default) or are actioned
immediately. /approvals lists the pending queue; approve performs the action,
reject records the refusal. Every outcome lands in disposition_audit.

Safety posture: authoring routes (create / update / enable / preview a policy) are open to any
authenticated user under the open-access model (_require_admin, which every signed-in user now
passes) — a policy is created disabled and never moves a file on its own. The two routes that
actually AUTHORISE or PERFORM a move-or-trash — execute and approve — are OWNER-gated
(_require_owner), so no single non-owner can act on the estate. delete is always Drive trash
(never permanent — see disposition.execute_action), and
a doc/policy pair with a live outcome (pending or applied) is never re-queued.
"""
from __future__ import annotations
import json
import uuid

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

import core
import disposition
from .system import _require_admin, _require_owner

router = APIRouter()


def _drive_svc(request: Request):
    """Drive client from the caller's token header, or None (leave-only mode)."""
    token = request.headers.get("x-drive-token")
    if not token:
        return None
    import handlers
    return handlers._drive_client(token)


def _persist_tags(doc: dict, cfg: dict, policy_id: str) -> None:
    """Write a tag policy's tags to file_tags after execute_action applied them.

    The disposition governance layer (the documents table) has no scan grain, so
    system tags are keyed by the document's STABLE doc_id (as scan_id) and its path
    (as file) — unique per document and idempotent by the file_tags primary key, so
    a re-run adds nothing new. kind='system'; rule_id is the policy that applied it,
    matching store.add_file_tags' contract (PRD §4.2 Tag / §3 auto-tagging)."""
    tags = disposition.tag_list(cfg)
    if tags:
        core.store.add_file_tags(doc["doc_id"], doc.get("path") or doc["doc_id"],
                                 tags, kind="system", rule_id=policy_id)


def _trace_decision(doc_id: str, path: str | None, *, action: str, status: str,
                    policy_id: str | None, reason: str | None) -> None:
    """Best-effort Langfuse span for a disposition/approval decision (Langfuse audit N2).

    Disposition was the one decision surface with no trace — the approval queue (#360) records
    to disposition_audit but emitted nothing to Langfuse, unlike the HITL review decisions. This
    mirrors that coverage. PHI-safe by construction: the helper sends only counts, statuses and
    ids and reduces the free-text `reason` to a length (see api/lf.trace_disposition_decision and
    docs/audit-langfuse-phi.md). Never blocks the decision it observes."""
    try:
        import lf as _lf
        _lf.trace_disposition_decision(doc_id, path, action=action, status=status,
                                       policy_id=policy_id, reason=reason)
    except Exception:
        pass


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
        disposition.validate_action_config(body.action, body.action_config)
    except ValueError as e:
        raise HTTPException(422, str(e))
    policy_id = uuid.uuid4().hex[:12]
    core.store.create_disposition_policy(
        policy_id, name=body.name, match=json.dumps(body.match), action=body.action,
        action_config=json.dumps(body.action_config), requires_approval=body.requires_approval,
        enabled=body.enabled)
    core.store.log_decision("admin", "disposition.policy_created", detail=body.name)
    return core.store.get_disposition_policy(policy_id)


def _readable(rows: list[dict]) -> list[dict]:
    """Join the human-readable facts onto audit rows: the document's source/path/department and
    the policy's NAME.

    A row as stored is (doc_id, policy_id, action, result) — four ids and an enum. Rendering that
    asks a reviewer to authorise "archive sp:1 under p2", which is not a decision anybody can
    make, and an auditor reading it back later has no way to tell what happened.

    `source` is what makes the rows SCOPEABLE. disposition_audit has no source column, so without
    this join a per-source panel would have to render the whole estate's history under a heading
    naming one source — the count-without-its-boundary error the rule match counts avoid.

    Shared by the approval queue and the audit trail deliberately: two endpoints enriching the
    same table differently is how one of them ends up missing a field nobody noticed.

    `document_exists` is false when the document has since been removed. Left visible, not
    filtered: for a pending row it is what a reviewer needs before deciding, and for a historical
    row it is part of what happened.
    """
    if not rows:
        return []
    docs = {d["doc_id"]: d for d in core.store.list_all_documents()}
    policies = {p["policy_id"]: p for p in core.store.list_disposition_policies()}
    out = []
    for r in rows:
        d = docs.get(r.get("doc_id")) or {}
        p = policies.get(r.get("policy_id")) or {}
        out.append({**r,
                    "source": d.get("source"), "path": d.get("path"),
                    "department": d.get("department"), "document_exists": bool(d),
                    # None, not the id, when the policy is gone: a deleted rule is a fact, and
                    # showing its id here would read as a name.
                    "policy_name": p.get("name")})
    return out


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


def _preview(match: list[dict], action: str, policy_id: str | None) -> dict:
    """The dry run itself, shared by the saved-policy preview and the draft preview.

    ONE evaluator, deliberately. The rule editor previews a draft as it is typed and the rule list
    previews the saved rule; were those two implementations, the count a person approved a rule on
    and the count that rule actually produces could differ — and the entire reason the preview
    exists is that somebody is deciding on the strength of that number.

    Read-only by construction: reads `documents`, runs `disposition.matches` in Python, writes
    nothing. No file is touched, no disposition_audit row appended, no policy row created.
    """
    docs = core.store.list_all_documents()
    selected = [d for d in docs if disposition.matches(d, match)]
    return {"policy_id": policy_id, "action": action,
            "would_match": len(selected), "documents": selected}


@router.post("/disposition/policies/{policy_id}/preview")
def preview_policy(policy_id: str):
    """Dry run: which documents would this policy select, right now? Never writes
    disposition_audit and never touches a file -- read-only by construction."""
    policy = core.store.get_disposition_policy(policy_id)
    if policy is None:
        raise HTTPException(404, "policy not found")
    return _preview(json.loads(policy["match"]), policy["action"], policy_id)


class PolicyDraft(BaseModel):
    """An UNSAVED rule — just enough of one to say what it would select."""
    match: list[dict]
    action: str
    action_config: dict = {}


@router.post("/disposition/preview")
def preview_draft(body: PolicyDraft, request: Request):
    """Dry run a rule that does NOT exist yet: how many documents would `{match, action}` select?

    The saved-policy preview above needs a policy_id, so the rule editor could only show a count
    AFTER creating the rule — which inverts the order the decision is actually made in. A person
    writing "everything under /Finance/2019 not modified in five years" needs to know it selects
    40 files and not 40,000 BEFORE committing to it; a preview that arrives once the row exists is
    a preview of a decision already taken.

    Read-only by construction, and more strictly so than the saved preview: it creates no policy
    row, so there is nothing to enable, nothing to execute and nothing left behind when the person
    closes the editor. It runs the SAME `disposition.matches` over the SAME documents table via
    `_preview`, so the count shown while typing is the count the saved rule will produce.

    Returns the saved preview's shape with `policy_id: null` — null because this rule has no id,
    not because one was lost. The key is present so a caller reads both responses one way.

    Admin-gated like the rest of this module, and NOT like `preview_policy`, which carries no gate.
    The predicate here is CALLER-SUPPLIED: the saved preview can only re-run a predicate an admin
    already authored and stored, while this route would otherwise let any allow-listed user run an
    arbitrary predicate over the whole documents table and read the matching rows back. Same
    refusal shape as its neighbours — 403 "admin access required".
    """
    _require_admin(request)
    if body.action not in disposition.ACTIONS:
        raise HTTPException(422, f"action must be one of {sorted(disposition.ACTIONS)}")
    try:
        disposition.validate_match(body.match)
        disposition.validate_action_config(body.action, body.action_config)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return _preview(body.match, body.action, None)


class PolicyUpdate(BaseModel):
    """An edit to a saved rule. Every field optional — an omitted field is left as it is.

    `enabled` is DELIBERATELY ABSENT. Arming a rule is its own decision, with its own route
    (PUT .../enabled) and its own audit line. Folding it into the edit payload would let a save
    somebody read as "rename this rule" also start it running.
    """
    name: str | None = None
    match: list[dict] | None = None
    action: str | None = None
    action_config: dict | None = None
    requires_approval: bool | None = None


def _policy_has_history(policy_id: str) -> bool:
    """Has this rule already produced a recorded outcome?

    disposition_audit is the complete record of what a rule has done. Every path that acts on a
    rule appends to it: the execute path writes a row per selected document, and the discovery
    lifecycle evaluator (handlers._evaluate_discover_lifecycle_rules) writes one beside every
    lifecycle_status it sets — so a rule cannot have flagged a file without an audit row naming
    it. Checking this one table is therefore checking every kind of history, not a convenient
    subset of it.

    ANY result counts, 'rejected' and 'failed' included. doc_has_disposition treats those as
    non-live so a re-run may propose the document again; that is a different question. The
    question here is whether a stored record NAMES this rule, and a rejected row names it just as
    loudly — an auditor reading "rejected: matched delete rule 'stale-finance'" is owed the rule
    that sentence was written about.
    """
    return bool(core.store.list_disposition_audit(policy_id=policy_id, limit=1))


@router.put("/disposition/policies/{policy_id}")
def update_policy(policy_id: str, body: PolicyUpdate, request: Request):
    """Edit a saved rule. Validated exactly like create, and structurally unable to arm one.

    ── WHAT AN EDIT MAY NOT DO: CHANGE WHAT ALREADY HAPPENED ────────────────────────────────
    A rule that has run has produced records that name it — disposition_audit rows, and
    scan_inventory rows whose `lifecycle_rule_id` points at it with a `lifecycle_reason` quoting
    it by name. Those records carry the rule's ID and nothing else: no column anywhere records
    WHICH DEFINITION of the rule produced them.

    So editing a definition in place silently rewrites the past. A file flagged "Archive Candidate
    — matched archive rule 'stale finance'" under a rule that said "not modified in five years"
    would, after an edit, be read by every future reader as having matched "not modified in 90
    days". Nothing errors. The tag does not move. The reason string does not change. Only its
    meaning does — retroactively, for evidence a compliance reviewer is expected to rely on.

    THE RULE THIS ROUTE ENFORCES: edits apply going forward, and existing records keep the
    definition that produced them.

    Implemented as: a rule that has produced ANY recorded outcome may no longer have its
    DEFINITION changed (`match`, `action`, `action_config`) — refused with 409. Its `name` and
    `requires_approval` stay editable, because neither alters which files the rule selected or
    what it recommended for them. To change what a rule that has run selects, create a new rule
    and disable the old one: the old rule and its history stay intact and keep meaning what they
    meant.

    ── WHY NOT VERSIONING, WHICH WOULD BE MORE PERMISSIVE ───────────────────────────────────
    The alternative is to version the policy and stamp that version onto every record it produces,
    so an edit makes v2 while existing tags keep pointing at v1. That is the better long-term
    answer and it is deliberately NOT implemented here, because doing it honestly means adding a
    version to `disposition_policy` AND `disposition_audit` AND `scan_inventory` — the three
    places a rule reference is stored — plus a backfill decision for every row already written
    without one. Versioning only the policy table would be WORSE than not versioning at all: audit
    rows would still carry a bare ID, so history would still read against whatever version is
    current, while the schema now claims the problem is solved.

    A rule that has produced nothing has exactly one definition, so the guarantee holds trivially
    for it — and that is the case the rule editor is in almost every time, since rules are created
    disabled and are edited before they are ever armed.
    """
    _require_admin(request)
    policy = core.store.get_disposition_policy(policy_id)
    if policy is None:
        raise HTTPException(404, "policy not found")

    # Resolve the RESULTING definition (current value wherever the caller omitted a field), then
    # validate THAT rather than the patch. A patch moving `action` from 'archive' to 'tag' without
    # supplying action_config has to be judged as the tag policy it produces — which is how "tag
    # with no tags" is caught here instead of failing silently at execute time.
    current_match = json.loads(policy.get("match") or "[]")
    current_cfg = json.loads(policy.get("action_config") or "{}")
    new_match = current_match if body.match is None else body.match
    new_action = policy["action"] if body.action is None else body.action
    new_cfg = current_cfg if body.action_config is None else body.action_config

    if new_action not in disposition.ACTIONS:
        raise HTTPException(422, f"action must be one of {sorted(disposition.ACTIONS)}")
    try:
        disposition.validate_match(new_match)
        disposition.validate_action_config(new_action, new_cfg)
    except ValueError as e:
        raise HTTPException(422, str(e))

    changed = [field for field, before, after in
               (("match", current_match, new_match),
                ("action", policy["action"], new_action),
                ("action_config", current_cfg, new_cfg))
               if before != after]
    if changed and _policy_has_history(policy_id):
        raise HTTPException(409,
            f"this rule has already run — its {', '.join(changed)} can no longer be changed. "
            "Files it flagged carry its decision, and no record says which version of the rule "
            "made that decision, so editing the rule here would change what those records mean. "
            "Create a new rule with the definition you want and disable this one; its history "
            "stays intact. (Its name and approval requirement are still editable.)")

    new_name = policy.get("name") if body.name is None else body.name
    new_req = (bool(policy.get("requires_approval")) if body.requires_approval is None
               else body.requires_approval)
    core.store.update_disposition_policy(
        policy_id, name=new_name, match=json.dumps(new_match), action=new_action,
        action_config=json.dumps(new_cfg), requires_approval=new_req)
    core.store.log_decision("admin", "disposition.policy_updated",
                            detail=f"{new_name}: {', '.join(changed) or 'name/approval only'}")
    return core.store.get_disposition_policy(policy_id)


@router.post("/disposition/policies/{policy_id}/execute")
def execute_policy(policy_id: str, request: Request):
    """Run an ENABLED policy for real. requires_approval matches queue as
    pending_approval; the rest are actioned immediately. Idempotent per
    (doc, policy): a pending or applied outcome is never re-queued."""
    _require_owner(request)   # actually moves/trashes files — owner-only
    policy = core.store.get_disposition_policy(policy_id)
    if policy is None:
        raise HTTPException(404, "policy not found")
    if not policy.get("enabled"):
        raise HTTPException(409, "policy is disabled — enable it before executing")
    match = json.loads(policy["match"])
    cfg = json.loads(policy.get("action_config") or "{}")
    svc = _drive_svc(request)
    # 'leave' and 'tag' never touch Drive, so they can act immediately with no svc.
    if policy["action"] not in ("leave", "tag") and not policy.get("requires_approval") and svc is None:
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
            detail = f"queued by policy '{policy['name']}' — awaiting approval"
            core.store.create_disposition_audit(
                audit_id, doc_id=doc["doc_id"], policy_id=policy_id,
                action=policy["action"], result="pending_approval", detail=detail)
            summary["pending_approval"] += 1
            _trace_decision(doc["doc_id"], doc.get("path"), action=policy["action"],
                            status="pending_approval", policy_id=policy_id, reason=detail)
        else:
            result, detail = disposition.execute_action(doc, policy["action"], cfg, svc)
            if result == "applied" and policy["action"] == "tag":
                _persist_tags(doc, cfg, policy_id)
            core.store.create_disposition_audit(
                audit_id, doc_id=doc["doc_id"], policy_id=policy_id,
                action=policy["action"], result=result, detail=detail)
            summary[result] += 1
            _trace_decision(doc["doc_id"], doc.get("path"), action=policy["action"],
                            status=result, policy_id=policy_id, reason=detail)
    core.store.log_decision("admin", "disposition.policy_executed",
                            detail=f"{policy['name']}: {summary}")
    return {"policy_id": policy_id, **summary}


@router.get("/disposition/audit")
def disposition_audit(request: Request, limit: int = Query(200, ge=1, le=1000)):
    """Full disposition history, newest first — the visible face of the append-only
    audit table (pending, applied, rejected, failed alike)."""
    _require_admin(request)
    return _readable(core.store.list_disposition_audit(limit=limit))


@router.get("/disposition/approvals")
def list_approvals(request: Request):
    """The pending-approval queue — every doc a requires_approval policy selected
    that no admin has decided on yet.

    ENRICHED FROM `documents`, for two reasons. An audit row carries only `doc_id`, which is
    not something a reviewer can act on — approving "drive:1a2b3c" asks somebody to authorise a
    string. And without `source` the queue cannot be split by connector, so a per-source panel
    would have to render the whole estate's approvals under a heading naming one source: the
    same count-without-its-boundary defect the rule match counts avoid.

    `source`/`path` are None when the document has since disappeared. That is left visible
    rather than filtered out — a queued action against a document that no longer exists is
    exactly what a reviewer should see before deciding, and approve() already fails it with 410.
    """
    _require_admin(request)
    return _readable(core.store.list_disposition_audit(result="pending_approval"))


@router.post("/disposition/approvals/{audit_id}/approve")
def approve_disposition(audit_id: str, request: Request,
                        execute: bool = Query(True)):
    """Approve the queued action. `execute` decides whether the file is TOUCHED.

    execute=true (default, unchanged): perform the action now — the audit row moves to applied
    or failed. This is what the route has always done, and callers that relied on it still get it.

    execute=false: RECORD THE DECISION ONLY. The row moves to 'approved' and no Drive call is
    made. Two reasons this is a distinct outcome rather than a client-side nicety:

      • `disposition.execute_action` supports Drive-backed documents ONLY (it returns
        "unsupported source" for anything else), so an approval on a SharePoint/OneDrive
        document cannot execute today whatever the caller asks for. Recording the decision is
        the honest half of the operation, and it is the half a compliance reviewer needs.
      • ACP holds READ-ONLY scopes (sharepointScopes.CAN_WRITE_BACK is false). A UI whose
        Approve button claimed to move a file would be describing a capability the deployment
        does not have.

    'approved' counts as a LIVE outcome in doc_has_disposition, so an approved-but-unexecuted
    decision is not re-proposed on the next execute run — asking a reviewer the same question
    twice is how an approval queue stops being trusted.
    """
    _require_owner(request)   # authorises a move/trash of the file — owner-only
    row = core.store.get_disposition_audit(audit_id)
    if row is None or row["result"] != "pending_approval":
        raise HTTPException(404, "no pending approval with that id")
    if not execute:
        detail = "approved by admin — decision recorded, file not touched"
        core.store.set_disposition_audit_result(audit_id, "approved", detail)
        core.store.log_decision("admin", "disposition.approved",
                                detail=f"{row['action']} {row['doc_id']}: recorded, not executed")
        _trace_decision(row["doc_id"], (core.store.get_document(row["doc_id"]) or {}).get("path"),
                        action=row["action"], status="approved", policy_id=row["policy_id"],
                        reason=detail)
        return core.store.get_disposition_audit(audit_id)
    policy = core.store.get_disposition_policy(row["policy_id"]) or {}
    cfg = json.loads(policy.get("action_config") or "{}")
    docs = {d["doc_id"]: d for d in core.store.list_all_documents()}
    doc = docs.get(row["doc_id"])
    if doc is None:
        core.store.set_disposition_audit_result(audit_id, "failed", "document no longer exists")
        _trace_decision(row["doc_id"], None, action=row["action"], status="failed",
                        policy_id=row["policy_id"], reason="document no longer exists")
        raise HTTPException(410, "document no longer exists")
    result, detail = disposition.execute_action(doc, row["action"], cfg, _drive_svc(request))
    if result == "applied" and row["action"] == "tag":
        _persist_tags(doc, cfg, row["policy_id"])
    core.store.set_disposition_audit_result(audit_id, result, detail)
    core.store.log_decision("admin", f"disposition.{result}",
                            detail=f"{row['action']} {row['doc_id']}: {detail}"[:200])
    _trace_decision(row["doc_id"], doc.get("path"), action=row["action"], status=result,
                    policy_id=row["policy_id"], reason=detail)
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
    _trace_decision(row["doc_id"], (core.store.get_document(row["doc_id"]) or {}).get("path"),
                    action=row["action"], status="rejected", policy_id=row["policy_id"],
                    reason="declined by admin")
    return core.store.get_disposition_audit(audit_id)
