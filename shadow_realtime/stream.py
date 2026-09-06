"""Isolated Redis Streams transport for the version-one shadow experiment."""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Iterable, Protocol

from .contract import EventEnvelope


STREAM_NAMESPACE = "realtime:v1"


class RedisLike(Protocol):
    def xadd(self, name, fields, id="*", maxlen=None, approximate=True): ...
    def xrange(self, name, min="-", max="+", count=None): ...
    def set(self, name, value, nx=False, ex=None): ...
    def incr(self, name): ...


def enabled(environ: dict[str, str] | None = None) -> bool:
    env = os.environ if environ is None else environ
    return env.get("SHADOW_REALTIME_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}


def stream_key(tenant_id: str) -> str:
    safe = "".join(c for c in tenant_id if c.isalnum() or c in "-_")
    if not safe or safe != tenant_id:
        raise ValueError("tenant_id must contain only letters, numbers, '-' or '_'")
    return f"{STREAM_NAMESPACE}:tenant:{safe}:events"


@dataclass(frozen=True)
class PublishResult:
    stream_id: str | None
    coalesced: bool = False


class ShadowStream:
    """Publish/replay adapter; deliberately not wired into ACP's existing Redis client."""

    def __init__(self, redis: RedisLike, *, max_events: int = 50_000, coalesce_seconds: int = 2):
        if max_events < 1:
            raise ValueError("max_events must be positive")
        self.redis = redis
        self.max_events = max_events
        self.coalesce_seconds = coalesce_seconds

    def next_sequence(self, tenant_id: str) -> int:
        return int(self.redis.incr(f"{STREAM_NAMESPACE}:tenant:{tenant_id}:sequence"))

    def publish(self, event: EventEnvelope, *, coalesce_key: str | None = None) -> PublishResult:
        # Only low-priority progress may be coalesced. Lifecycle events are always appended.
        if event.priority == "low" and event.event_type.endswith(".progress") and coalesce_key:
            marker = f"{STREAM_NAMESPACE}:coalesce:{event.tenant_id}:{coalesce_key}"
            if not self.redis.set(marker, event.event_id, nx=True, ex=self.coalesce_seconds):
                return PublishResult(None, coalesced=True)
        sid = self.redis.xadd(
            stream_key(event.tenant_id),
            {"envelope": event.to_json()},
            maxlen=self.max_events,
            approximate=True,
        )
        if isinstance(sid, bytes):
            sid = sid.decode("ascii")
        return PublishResult(str(sid))

    def replay(self, tenant_id: str, last_event_id: str | None, *, limit: int = 10_000) -> list[tuple[str, EventEnvelope]]:
        """Return retained events after the SSE Last-Event-ID cursor, oldest first."""
        start = "-" if not last_event_id else f"({last_event_id}"
        rows = self.redis.xrange(stream_key(tenant_id), min=start, max="+", count=limit)
        out = []
        for sid, fields in rows:
            sid = sid.decode("ascii") if isinstance(sid, bytes) else str(sid)
            raw = fields.get(b"envelope") if b"envelope" in fields else fields["envelope"]
            out.append((sid, EventEnvelope.from_json(raw)))
        return out


def sse_frames(events: Iterable[tuple[str, EventEnvelope]]) -> Iterable[str]:
    """Project replay/live rows to SSE, including IDs understood by Last-Event-ID."""
    for stream_id, event in events:
        yield f"id: {stream_id}\nevent: {event.event_type}\ndata: {event.to_json()}\n\n"
