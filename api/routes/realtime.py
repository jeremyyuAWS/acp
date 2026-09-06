"""Authenticated same-origin bridge to the default-off canonical realtime stream."""
from __future__ import annotations

import os

from fastapi import APIRouter, Header, HTTPException, Request

from realtime_events import owner_scope
from realtime_gateway.app import event_stream_response
from realtime_gateway.store import RedisEventStore
import core


router = APIRouter()


def _enabled() -> bool:
    return os.getenv("ACP_REALTIME_V1_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}


def _store() -> RedisEventStore:
    import redis.asyncio as redis
    url = (os.getenv("ACP_REALTIME_V1_REDIS_URL") or os.getenv("REDIS_URL") or "").strip()
    if not url:
        raise HTTPException(503, "realtime event store is not configured")
    return RedisEventStore(redis.from_url(url, decode_responses=True))


def _owner(request: Request) -> str:
    return getattr(request.state, "user_email", None) or "demo"


@router.get("/api/realtime/v1/status")
async def status(request: Request):
    """Small authoritative twin used when the replay cursor can no longer be honored."""
    if not _enabled():
        raise HTTPException(404, "realtime shadow is disabled")
    owner = _owner(request)
    active = core.store.active_scan(owner=owner) or {}
    return {
        "scan_id": active.get("id") or active.get("scan_id"),
        "scan_status": active.get("status"),
        "active_workflows": core.store.active_workflows(owner),
    }


@router.get("/api/realtime/v1/stream")
async def stream(
    request: Request,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
):
    """Translate the existing access-gate identity into its private owner stream.

    The browser sends its normal Google/Microsoft bearer to the outer ACP access gate. This route
    never forwards that credential and never accepts an owner supplied by the client.
    """
    if not _enabled():
        raise HTTPException(404, "realtime shadow is disabled")
    owner = _owner(request)
    return event_stream_response(
        request, scope=owner_scope(owner), store=_store(),
        block_ms=int(os.getenv("ACP_REALTIME_V1_BLOCK_MS", "1000")),
        last_event_id=last_event_id, close_store=True,
    )
