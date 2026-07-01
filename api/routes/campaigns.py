"""Phased remediation campaigns (ADR 0003, Phase 4) -- persisted "Remediation
Programs": create/list/pause/resume a campaign, with batch membership computed
once at creation time and durable across reloads.

Same access posture as /disposition/* and the existing /admin/reset: gated by
the app's perimeter auth only, no server-side per-route role check yet.
"""
from __future__ import annotations
import json
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import core
import campaigns as _campaigns

router = APIRouter()


class CampaignCreate(BaseModel):
    scan_id: str
    name: str
    deadline: str | None = None


def _batch_done_counts(scan_id: str) -> dict[str, int]:
    """Files with a persisted 'accepted'/'override' action decision, PER FILE --
    NOTE: Discover.jsx's decide()/confirmClass() are currently client-state only
    (never POSTed to scan_decisions), so this is honest-but-empty until that's
    wired up -- a separate, pre-existing gap, not something this endpoint papers
    over with fake counts."""
    decisions = core.store.get_decisions(scan_id)
    done: set[str] = set()
    for file, kinds in decisions.items():
        raw = kinds.get("action")
        if not raw:
            continue
        try:
            state = json.loads(raw).get("state")
        except Exception:
            continue
        if state in ("accepted", "override"):
            done.add(file)
    return done


def _serialize_batches(campaign_id: str, scan_id: str) -> list[dict]:
    done = _batch_done_counts(scan_id)
    out = []
    for b in core.store.list_campaign_batches(campaign_id):
        files = json.loads(b["filter"] or "{}").get("files", [])
        out.append({**b, "count": len(files), "done": sum(1 for f in files if f in done)})
    return out


@router.post("/campaigns")
def create_campaign(body: CampaignCreate):
    scan = core.store.get_scan(body.scan_id)
    if scan is None:
        raise HTTPException(404, "scan not found")
    severities: dict[str, set[str]] = {}
    for row in core.store.list_scan_severities(body.scan_id):
        severities.setdefault(row["file"], set()).add(row["severity"])
    buckets = _campaigns.compute_batches(scan["files"], severities)

    campaign_id = uuid.uuid4().hex[:12]
    core.store.create_campaign(campaign_id, name=body.name, status="active",
                               scope=json.dumps({"scan_id": body.scan_id}))
    for seq, b in enumerate(buckets):
        core.store.create_campaign_batch(
            uuid.uuid4().hex[:12], campaign_id=campaign_id, seq=seq, status="pending",
            filter=json.dumps({"bucket": b["bucket"], "label": b["label"], "files": b["files"]}),
            deadline=body.deadline)
    core.store.log_decision("system", "campaign.created", scan_id=body.scan_id, detail=body.name)
    return get_campaign(campaign_id)


@router.get("/campaigns")
def list_campaigns(scan_id: str | None = None):
    return core.store.list_campaigns(scan_id=scan_id)


@router.get("/campaigns/{campaign_id}")
def get_campaign(campaign_id: str):
    c = core.store.get_campaign(campaign_id)
    if c is None:
        raise HTTPException(404, "campaign not found")
    scan_id = json.loads(c["scope"] or "{}").get("scan_id")
    return {**c, "batches": _serialize_batches(campaign_id, scan_id) if scan_id else []}


class StatusUpdate(BaseModel):
    status: str


_CAMPAIGN_STATUSES = {"draft", "active", "paused", "complete"}
_BATCH_STATUSES = {"pending", "active", "paused", "complete"}


@router.put("/campaigns/{campaign_id}/status")
def set_campaign_status(campaign_id: str, body: StatusUpdate):
    if core.store.get_campaign(campaign_id) is None:
        raise HTTPException(404, "campaign not found")
    if body.status not in _CAMPAIGN_STATUSES:
        raise HTTPException(422, f"status must be one of {sorted(_CAMPAIGN_STATUSES)}")
    core.store.update_campaign_status(campaign_id, body.status)
    core.store.log_decision("admin", f"campaign.{body.status}", detail=campaign_id)
    return get_campaign(campaign_id)


@router.put("/campaigns/{campaign_id}/batches/{batch_id}/status")
def set_batch_status(campaign_id: str, batch_id: str, body: StatusUpdate):
    if body.status not in _BATCH_STATUSES:
        raise HTTPException(422, f"status must be one of {sorted(_BATCH_STATUSES)}")
    core.store.update_campaign_batch_status(batch_id, body.status)
    core.store.log_decision("admin", f"campaign.batch_{body.status}", detail=batch_id)
    return get_campaign(campaign_id)
