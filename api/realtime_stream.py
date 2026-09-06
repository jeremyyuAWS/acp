"""Shared canonical SSE response used by the gateway and ACP's same-origin bridge."""
from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress

from fastapi import Request
from fastapi.responses import StreamingResponse

try:  # package import in the standalone gateway; top-level import in /app/api production
    from .realtime_events import MAX_REPLAY_EVENTS, parse_last_event_id
except ImportError:  # pragma: no cover - exercised by the production-style import smoke test
    from realtime_events import MAX_REPLAY_EVENTS, parse_last_event_id


SnapshotProvider = Callable[[str], Awaitable[Mapping]]


def _control(kind: str, payload: Mapping) -> bytes:
    return f"event: {kind}\ndata: {json.dumps(dict(payload), separators=(',', ':'))}\n\n".encode()


def event_stream_response(
    request: Request, *, scope: str, store, block_ms: int,
    last_event_id: str | None = None, snapshot_provider: SnapshotProvider | None = None,
    close_store: bool = False,
) -> StreamingResponse:
    """Serve one owner-scoped canonical stream behind any already-authenticated edge."""
    invalid_reason = None

    async def body():
        nonlocal invalid_reason
        cursor = last_event_id
        try:
            if cursor:
                try:
                    parse_last_event_id(cursor)
                    status = await store.cursor_status(scope, cursor)
                    if status != "valid":
                        invalid_reason = status
                except ValueError:
                    invalid_reason = "malformed"
            if not cursor or invalid_reason:
                if invalid_reason:
                    yield _control("reconciliation-required", {"reason": invalid_reason})
                if snapshot_provider is not None:
                    yield _control("snapshot", await snapshot_provider(scope))
                cursor = "$"
            else:
                rows = await store.replay(scope, cursor, limit=MAX_REPLAY_EVENTS)
                for row_id, event in rows:
                    cursor = row_id
                    yield event.to_sse().encode()
                if len(rows) == MAX_REPLAY_EVENTS:
                    yield _control("reconciliation-required", {"reason": "replay-limit"})
                    return
            listener = store.listen(scope, cursor, block_ms=block_ms)
            try:
                while not await request.is_disconnected():
                    try:
                        _row_id, event = await asyncio.wait_for(anext(listener), timeout=15)
                    except StopAsyncIteration:
                        return
                    except TimeoutError:
                        yield b": keepalive\n\n"
                        continue
                    yield event.to_sse().encode()
            finally:
                with suppress(Exception):
                    await listener.aclose()
        finally:
            if close_store:
                with suppress(Exception):
                    await store.close()

    return StreamingResponse(
        body(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
