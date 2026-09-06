"""Redis reader for the canonical owner-scoped realtime event stream."""
from __future__ import annotations

import json
from collections.abc import AsyncIterator

try:  # package import in the standalone gateway; top-level import in /app/api production
    from .realtime_events import MAX_REPLAY_EVENTS, RealtimeEvent, parse_last_event_id, stream_key
except ImportError:  # pragma: no cover - exercised by the production-style import smoke test
    from realtime_events import MAX_REPLAY_EVENTS, RealtimeEvent, parse_last_event_id, stream_key


def _with_stream_id(row_id: str | bytes, fields: dict) -> tuple[str, RealtimeEvent]:
    sid = row_id.decode("ascii") if isinstance(row_id, bytes) else str(row_id)
    raw = fields.get("event", fields.get(b"event"))
    if raw is None:
        raise ValueError("realtime stream row is missing the canonical event field")
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    body = json.loads(raw)
    body["stream_id"] = sid
    return sid, RealtimeEvent.from_dict(body)


class RedisEventStore:
    """Read canonical events without touching any legacy queue or SSE keys."""

    def __init__(self, redis):
        self.redis = redis

    async def bounds(self, scope: str) -> tuple[str | None, str | None]:
        key = stream_key(scope)
        first = await self.redis.xrange(key, min="-", max="+", count=1)
        last = await self.redis.xrevrange(key, max="+", min="-", count=1)
        normalize = lambda row: row[0].decode("ascii") if isinstance(row[0], bytes) else str(row[0])
        return normalize(first[0]) if first else None, normalize(last[0]) if last else None

    async def cursor_status(self, scope: str, cursor: str) -> str:
        requested = parse_last_event_id(cursor)
        first, last = await self.bounds(scope)
        if first and requested < parse_last_event_id(first):
            return "stale"
        if last and requested > parse_last_event_id(last):
            return "ahead"
        return "valid"

    async def replay(
        self, scope: str, cursor: str, *, limit: int = MAX_REPLAY_EVENTS,
    ) -> list[tuple[str, RealtimeEvent]]:
        if limit < 1 or limit > MAX_REPLAY_EVENTS:
            raise ValueError(f"replay limit must be from 1 through {MAX_REPLAY_EVENTS}")
        rows = await self.redis.xrange(stream_key(scope), min=f"({cursor}", max="+", count=limit)
        return [_with_stream_id(row_id, fields) for row_id, fields in rows]

    async def listen(
        self, scope: str, cursor: str, *, block_ms: int,
    ) -> AsyncIterator[tuple[str, RealtimeEvent]]:
        current = cursor
        while True:
            rows = await self.redis.xread(
                {stream_key(scope): current}, count=MAX_REPLAY_EVENTS, block=block_ms,
            )
            for _key, entries in rows:
                for row_id, fields in entries:
                    current, event = _with_stream_id(row_id, fields)
                    yield current, event

    async def close(self) -> None:
        await self.redis.aclose()
