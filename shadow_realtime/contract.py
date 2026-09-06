"""Version-one event envelope shared by the shadow collector and load harness."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from typing import Any, Mapping
from uuid import uuid4


PRIORITIES = frozenset({"low", "normal", "high", "critical"})


@dataclass(frozen=True)
class EventEnvelope:
    event_id: str
    event_version: int
    event_type: str
    occurred_at: str
    tenant_id: str
    correlation_id: str
    source: str
    priority: str
    sequence: int
    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.event_version != 1:
            raise ValueError("shadow realtime only supports event_version=1")
        if not self.event_type or not self.tenant_id or not self.source:
            raise ValueError("event_type, tenant_id, and source are required")
        if self.priority not in PRIORITIES:
            raise ValueError(f"unsupported priority: {self.priority}")
        if self.sequence < 0:
            raise ValueError("sequence must not be negative")

    @classmethod
    def new(
        cls,
        *,
        event_type: str,
        tenant_id: str,
        correlation_id: str,
        source: str,
        priority: str,
        sequence: int,
        payload: Mapping[str, Any],
        event_id: str | None = None,
        occurred_at: str | None = None,
    ) -> "EventEnvelope":
        return cls(
            event_id=event_id or str(uuid4()),
            event_version=1,
            event_type=event_type,
            occurred_at=occurred_at or datetime.now(timezone.utc).isoformat(),
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            source=source,
            priority=priority,
            sequence=sequence,
            payload=dict(payload),
        )

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"), sort_keys=True)

    @classmethod
    def from_json(cls, value: str | bytes) -> "EventEnvelope":
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        return cls(**json.loads(value))
