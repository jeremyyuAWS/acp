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
    return updated
