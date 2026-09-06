"""Versioned wire contract for ACP realtime operational events.

This module is intentionally transport-only.  Publishers and SSE routes opt into it in later
changes; importing it has no side effects and it does not read Redis, Postgres, or Azure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import IntEnum
import hashlib
import json
import re
from types import MappingProxyType
from typing import Any, Mapping
from uuid import UUID, uuid4


SCHEMA_VERSION = "1.0"
MEDIA_TYPE = "application/vnd.acp.realtime-event+json;version=1.0"
SSE_EVENT_NAME = "acp-event"
STREAM_PREFIX = "acp:realtime:v1:owner"
RETENTION_SECONDS = 24 * 60 * 60
RETENTION_MIN_EVENTS = 10_000
MAX_REPLAY_EVENTS = 500

_KIND_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
_STREAM_ID_RE = re.compile(r"^(?:0|[1-9][0-9]*)-(?:0|[1-9][0-9]*)$")


class Priority(IntEnum):
    """Delivery priority; the numeric value is stable on the wire."""

    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3


@dataclass(frozen=True)
class KindSpec:
    priority: Priority
    terminal: bool = False
    coalesce_window_ms: int = 0


# A closed vocabulary makes typos fail before they become events no consumer can interpret.
KIND_SPECS: Mapping[str, KindSpec] = MappingProxyType({
    # Discover
    "discover.queued": KindSpec(Priority.NORMAL, coalesce_window_ms=2_000),
    "discover.started": KindSpec(Priority.NORMAL),
    "discover.progressed": KindSpec(Priority.LOW, coalesce_window_ms=10_000),
    "discover.completed": KindSpec(Priority.HIGH, terminal=True),
    "discover.cancelled": KindSpec(Priority.HIGH, terminal=True),
    "discover.failed": KindSpec(Priority.CRITICAL, terminal=True),
    # Assess
    "assess.queued": KindSpec(Priority.NORMAL, coalesce_window_ms=2_000),
    "assess.started": KindSpec(Priority.NORMAL),
    "assess.progressed": KindSpec(Priority.LOW, coalesce_window_ms=10_000),
    "assess.completed": KindSpec(Priority.HIGH, terminal=True),
    "assess.cancelled": KindSpec(Priority.HIGH, terminal=True),
    "assess.failed": KindSpec(Priority.CRITICAL, terminal=True),
    # Remediate
    "remediate.queued": KindSpec(Priority.NORMAL, coalesce_window_ms=2_000),
    "remediate.started": KindSpec(Priority.NORMAL),
    "remediate.progressed": KindSpec(Priority.LOW, coalesce_window_ms=10_000),
    "remediate.review_requested": KindSpec(Priority.HIGH),
    "remediate.completed": KindSpec(Priority.HIGH, terminal=True),
    "remediate.cancelled": KindSpec(Priority.HIGH, terminal=True),
    "remediate.failed": KindSpec(Priority.CRITICAL, terminal=True),
    # Queue and worker lifecycle
    "queue.depth_changed": KindSpec(Priority.LOW, coalesce_window_ms=10_000),
    "queue.job_delayed": KindSpec(Priority.HIGH, coalesce_window_ms=1_000),
    "queue.job_dead_lettered": KindSpec(Priority.CRITICAL),
    "worker.starting": KindSpec(Priority.NORMAL, coalesce_window_ms=2_000),
    "worker.ready": KindSpec(Priority.NORMAL, coalesce_window_ms=2_000),
    "worker.busy": KindSpec(Priority.LOW, coalesce_window_ms=10_000),
    "worker.draining": KindSpec(Priority.HIGH),
    "worker.unhealthy": KindSpec(Priority.CRITICAL),
    "worker.offline": KindSpec(Priority.CRITICAL, terminal=True),
    # Azure capacity and alerts
    "capacity.changed": KindSpec(Priority.NORMAL, coalesce_window_ms=2_000),
    "capacity.shortage_detected": KindSpec(Priority.CRITICAL),
    "capacity.recovered": KindSpec(Priority.HIGH),
    "alert.opened": KindSpec(Priority.CRITICAL),
    "alert.updated": KindSpec(Priority.HIGH, coalesce_window_ms=1_000),
    "alert.resolved": KindSpec(Priority.HIGH, terminal=True),
})


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def owner_scope(owner_email: str) -> str:
    """Return the non-reversible tenant token used in Redis keys, never the email itself."""

    normalized = owner_email.strip().casefold()
    if not normalized:
        raise ValueError("owner_email is required")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]


def stream_key(scope: str) -> str:
    if not re.fullmatch(r"[a-f0-9]{24}", scope):
        raise ValueError("owner scope must be a 24-character lowercase hex token")
    return f"{STREAM_PREFIX}:{scope}:events"


def parse_last_event_id(value: str | None) -> tuple[int, int] | None:
    """Validate the Redis Stream ID carried in ``Last-Event-ID``."""

    if value is None or value == "":
        return None
    if not _STREAM_ID_RE.fullmatch(value):
        raise ValueError("Last-Event-ID must be a Redis Stream ID (<ms>-<sequence>)")
    milliseconds, sequence = value.split("-", 1)
    return int(milliseconds), int(sequence)


def _instant(value: datetime, name: str) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _parse_instant(value: Any, name: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be an RFC 3339 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} must be an RFC 3339 string") from exc
    _instant(parsed, name)
    return parsed


@dataclass(frozen=True)
class RealtimeEvent:
    """One immutable v1 event envelope.

    ``stream_id`` is assigned by Redis XADD and is the ordering/replay cursor. ``event_id`` is
    generated once by the producer and remains stable across retries or durable-store replays.
    """

    kind: str
    owner_scope: str
    payload: Mapping[str, Any]
    occurred_at: datetime
    observed_at: datetime = field(default_factory=utc_now)
    event_id: str = field(default_factory=lambda: str(uuid4()))
    priority: Priority | None = None
    stream_id: str | None = None
    source_seq: int | None = None
    workflow_id: str | None = None
    scan_id: str | None = None
    job_id: str | None = None
    worker_id: str | None = None
    correlation_id: str | None = None
    coalesce_key: str | None = None
    stale_after_ms: int | None = None

    def __post_init__(self) -> None:
        if self.kind not in KIND_SPECS or not _KIND_RE.fullmatch(self.kind):
            raise ValueError(f"unknown realtime event kind: {self.kind!r}")
        if not re.fullmatch(r"[a-f0-9]{24}", self.owner_scope):
            raise ValueError("owner_scope must be a 24-character lowercase hex token")
        try:
            UUID(self.event_id)
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("event_id must be a UUID") from exc
        if self.stream_id is not None:
            parse_last_event_id(self.stream_id)
        if self.source_seq is not None and self.source_seq < 0:
            raise ValueError("source_seq cannot be negative")
        if self.stale_after_ms is not None and self.stale_after_ms <= 0:
            raise ValueError("stale_after_ms must be positive")
        if not isinstance(self.payload, Mapping):
            raise ValueError("payload must be an object")
        _instant(self.occurred_at, "occurred_at")
        _instant(self.observed_at, "observed_at")
        try:
            json.dumps(self.payload, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("payload must be finite JSON") from exc
        expected = KIND_SPECS[self.kind].priority
        if self.priority is not None and self.priority != expected:
            raise ValueError(f"priority for {self.kind} must be {expected.name}")

    @property
    def effective_priority(self) -> Priority:
        return self.priority if self.priority is not None else KIND_SPECS[self.kind].priority

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "event_id": self.event_id,
            "stream_id": self.stream_id,
            "kind": self.kind,
            "priority": int(self.effective_priority),
            "owner_scope": self.owner_scope,
            "occurred_at": _instant(self.occurred_at, "occurred_at"),
            "observed_at": _instant(self.observed_at, "observed_at"),
            "stale_after_ms": self.stale_after_ms,
            "source_seq": self.source_seq,
            "workflow_id": self.workflow_id,
            "scan_id": self.scan_id,
            "job_id": self.job_id,
            "worker_id": self.worker_id,
            "correlation_id": self.correlation_id,
            "coalesce_key": self.coalesce_key,
            "payload": dict(self.payload),
        }
        return {key: value for key, value in data.items() if value is not None}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"), sort_keys=True, allow_nan=False)

    def to_sse(self) -> str:
        if self.stream_id is None:
            raise ValueError("stream_id is required before SSE serialization")
        return f"id: {self.stream_id}\nevent: {SSE_EVENT_NAME}\ndata: {self.to_json()}\n\n"

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RealtimeEvent":
        """Validate and deserialize v1, ignoring additive fields from a later minor version."""

        version = value.get("schema_version")
        if not isinstance(version, str) or not re.fullmatch(r"1\.[0-9]+", version):
            raise ValueError(f"unsupported realtime event schema_version: {version!r}")
        required = ("event_id", "kind", "owner_scope", "occurred_at", "observed_at", "payload")
        missing = [name for name in required if name not in value]
        if missing:
            raise ValueError(f"missing realtime event fields: {', '.join(missing)}")
        try:
            if isinstance(value.get("priority"), bool):
                raise ValueError
            priority = Priority(value["priority"]) if "priority" in value else None
        except (TypeError, ValueError) as exc:
            raise ValueError("priority must be an integer from 0 through 3") from exc
        return cls(
            kind=value["kind"], owner_scope=value["owner_scope"], payload=value["payload"],
            occurred_at=_parse_instant(value["occurred_at"], "occurred_at"),
            observed_at=_parse_instant(value["observed_at"], "observed_at"),
            event_id=value["event_id"], priority=priority, stream_id=value.get("stream_id"),
            source_seq=value.get("source_seq"), workflow_id=value.get("workflow_id"),
            scan_id=value.get("scan_id"), job_id=value.get("job_id"),
            worker_id=value.get("worker_id"), correlation_id=value.get("correlation_id"),
            coalesce_key=value.get("coalesce_key"), stale_after_ms=value.get("stale_after_ms"),
        )


def coalescing_bucket(event: RealtimeEvent) -> tuple[str, str] | None:
    """Return the publisher-side latest-value bucket, or None when delivery is lossless."""

    spec = KIND_SPECS[event.kind]
    if spec.terminal or event.effective_priority == Priority.CRITICAL or not spec.coalesce_window_ms:
        return None
    if not event.coalesce_key:
        return None
    return event.kind, event.coalesce_key


def legacy_sse_data(payload: Mapping[str, Any]) -> str:
    """Serialize an existing snapshot frame unchanged during the additive v1 rollout."""

    return f"data: {json.dumps(dict(payload), separators=(',', ':'))}\n\n"
