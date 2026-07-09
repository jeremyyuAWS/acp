"""Human-in-the-loop review queue endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

import core

router = APIRouter()


class HitlUpdate(BaseModel):
    status: str                     # pending | approved | rejected | skipped
    reviewer_note: str | None = None
    approved_value: str | None = None   # AI-drafted or hand-edited final text (alt/link text)
    edited: bool = False                # reviewer changed the AI draft before approving (calibration signal)
    review_ms: int | None = None        # client-measured time from card-open to decision (reviewer-time metric)
    ai_value: str | None = None         # the AI-proposed value shown, so we store proposed-vs-final


@router.post("/hitl/queue/{scan_id}/auto")
def hitl_auto_queue(scan_id: str):
    """Auto-populate the HITL review queue from ai-assisted FAILs in an existing scan.

    Idempotent — safe to call multiple times. Returns the newly created items.
    Fires a webhook (HITL_WEBHOOK_URL) if configured.
    """
    if core.store.get_scan(scan_id) is None:
        raise HTTPException(404, "scan not found")
    created = core.store.queue_hitl_items(scan_id)
    core.fire_webhook(created)
    return {"queued": len(created), "items": created}


@router.post("/hitl/queue/{scan_id}/verify")
def hitl_verify_queue(scan_id: str, file: str = Query(...)):
    """Queue a post-fix VERIFICATION item for one fully-automatic remediation
    (user decision 2026-07-02: automatic fixes also get human review). The
    ai-assisted pull above never sees auto-mode rules, so this is the only
    path that puts a fully-automatic fix in front of a person. Idempotent per
    (scan, file) — repeat clicks of remediate-now never duplicate the item."""
    if core.store.get_scan(scan_id) is None:
        raise HTTPException(404, "scan not found")
    item_id = core.store.queue_hitl_deferral(
        scan_id, file, "Automatic fix applied — verify the result", 1, rule_id="auto/verify")
    if item_id:
        core.fire_webhook([{"id": item_id, "scan_id": scan_id, "file": file,
                            "rule_id": "auto/verify", "status": "pending"}])
    return {"queued": 0 if item_id is None else 1, "id": item_id}


@router.get("/hitl/queue")
def hitl_list(request: Request, status: str | None = None, scan_id: str | None = None):
    """List HITL review items, scoped to the signed-in user's own documents. Filter by
    status (pending/approved/rejected/skipped) or scan_id."""
    owner = getattr(request.state, "user_email", None)
    return core.store.list_hitl_queue(status=status, scan_id=scan_id, owner=owner)


@router.get("/hitl/analytics")
def hitl_metrics(request: Request, scan_id: str | None = None):
    """Human-review telemetry for the Intelligent Review Workspace dashboard — decisions by
    action, approval rate, edit rate (confidence-calibration signal), and average review time
    (the headline metric: reviewer time eliminated). Scoped to one scan when scan_id is given."""
    if scan_id is not None and core.store.get_scan(
            scan_id, owner=getattr(request.state, "user_email", None)) is None:
        raise HTTPException(404, "scan not found")
    return core.store.hitl_analytics(scan_id)


@router.put("/hitl/queue/{item_id}")
def hitl_update(item_id: str, body: HitlUpdate, request: Request = None):
    """Update a HITL review item status (approve, reject, skip) with an optional reviewer note."""
    item = core.store.get_hitl_item(item_id)
    if item is None:
        raise HTTPException(404, "item not found")
    valid = {"pending", "approved", "rejected", "skipped"}
    if body.status not in valid:
        raise HTTPException(422, f"status must be one of {sorted(valid)}")
    updated = core.store.update_hitl_item(item_id, body.status, body.reviewer_note, body.approved_value)
    # Immutable audit trail: who decided what, when, on which finding — include the
    # approved value itself so the log is self-sufficient compliance evidence.
    _detail = body.reviewer_note or None
    if body.approved_value:
        _detail = f"{_detail + ' | ' if _detail else ''}approved: {body.approved_value[:160]}"
    core.store.log_decision(
        "reviewer", f"hitl.{body.status}",
        scan_id=item.get("scan_id"), file=item.get("file"), rule_id=item.get("rule_id"),
        detail=_detail)
    # Review telemetry (Intelligent Review Workspace): one event per decision so we can
    # report reviewer time saved + calibrate confidence from the edit/reject signal.
    # Best-effort — never blocks the review.
    try:
        _action = ("edit" if (body.status == "approved" and body.edited)
                   else {"approved": "approve", "rejected": "reject", "skipped": "skip"}.get(body.status, body.status))
        core.store.record_hitl_event(
            item.get("scan_id"), item.get("file"), item.get("rule_id"), item_id, _action,
            edited=body.edited, review_ms=body.review_ms, ai_value=body.ai_value,
            final_value=body.approved_value,
            reviewer=(getattr(request.state, "user_email", None) if request is not None else None))
    except Exception:
        pass
    # Observability: the human decision joins the file's Langfuse trace (audit P1 — HITL
    # decisions were previously untraced). Best-effort; never blocks the review.
    try:
        import lf as _lf
        _lf.trace_hitl_decision(item.get("scan_id"), item.get("file"), item.get("rule_id"),
                                body.status, note=body.reviewer_note,
                                approved_value=body.approved_value)
    except Exception:
        pass
    # ADR 0003 Phase 2: HITL resolution is an explicit remediation_state transition.
    # approved (AI draft accepted) -> complete; rejected (a human said it's wrong, still
    # needs work) -> in_progress; skipped (deferred, still needs attention) -> unchanged
    # (stays awaiting_review) -- pending doesn't transition anything.
    _STATE_FOR = {"approved": "complete", "rejected": "in_progress", "skipped": "awaiting_review"}
    if body.status in _STATE_FOR and item.get("scan_id") and item.get("file") and item.get("rule_id"):
        try:
            from documents import resolve_doc_id
            scan_id, file = item["scan_id"], item["file"]
            source = (core.store.get_scan(scan_id) or {}).get("run", {}).get("source")
            ident = next((i for i in core.store.list_file_identities(scan_id) if i["file"] == file), {})
            doc_id = resolve_doc_id(source, ident.get("drive_file_id"), file, ident.get("checksum"))
            core.store.upsert_remediation_state(doc_id, item["rule_id"], _STATE_FOR[body.status], scan_id)
        except Exception:
            pass
    # Re-validate → certify: once a remediated file's every review item is approved, it is
    # fully conformant (auto fixes verified + human findings signed off) and advances to
    # Publish. This is the seam that closes the remediate → review → publish loop — without
    # it an approved file stays compliant=0 forever and never reaches the publish queue.
    if body.status == "approved" and item.get("scan_id") and item.get("file"):
        try:
            if core.store.mark_file_compliant_if_reviewed(item["scan_id"], item["file"]):
                core.store.log_decision(
                    "system", "revalidate.certified", scan_id=item["scan_id"], file=item["file"],
                    detail="all findings resolved (auto-fixed + human-approved) — certified & advanced to Publish")
        except Exception:
            pass
    return updated
