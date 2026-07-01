"""Human-in-the-loop review queue endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import core

router = APIRouter()


class HitlUpdate(BaseModel):
    status: str                     # pending | approved | rejected | skipped
    reviewer_note: str | None = None


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


@router.get("/hitl/queue")
def hitl_list(status: str | None = None, scan_id: str | None = None):
    """List HITL review items. Filter by status (pending/approved/rejected/skipped) or scan_id."""
    return core.store.list_hitl_queue(status=status, scan_id=scan_id)


@router.put("/hitl/queue/{item_id}")
def hitl_update(item_id: str, body: HitlUpdate):
    """Update a HITL review item status (approve, reject, skip) with an optional reviewer note."""
    item = core.store.get_hitl_item(item_id)
    if item is None:
        raise HTTPException(404, "item not found")
    valid = {"pending", "approved", "rejected", "skipped"}
    if body.status not in valid:
        raise HTTPException(422, f"status must be one of {sorted(valid)}")
    updated = core.store.update_hitl_item(item_id, body.status, body.reviewer_note)
    # Immutable audit trail: who decided what, when, on which finding.
    core.store.log_decision(
        "reviewer", f"hitl.{body.status}",
        scan_id=item.get("scan_id"), file=item.get("file"), rule_id=item.get("rule_id"),
        detail=body.reviewer_note or None)
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
    return updated
