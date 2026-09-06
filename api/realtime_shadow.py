"""Default-off shadow publisher for the versioned realtime event contract.

This module observes the durable worker; it is not part of job correctness.  Calls enqueue
best-effort work and return immediately.  Redis I/O happens on a daemon thread with bounded
connect/read timeouts and a distinct ``realtime:v1`` key namespace.
"""
from __future__ import annotations

from collections import Counter, OrderedDict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
import threading
import time
import uuid

from swallowed import swallowed

NAMESPACE = "realtime:v1"
EVENT_VERSION = 1
_TRUE = frozenset({"1", "true", "yes", "on"})


def enabled() -> bool:
    return (os.environ.get("ACP_REALTIME_SHADOW_ENABLED") or "").strip().lower() in _TRUE


def _integer(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        return default


class Metrics:
    """Tiny dependency-free metrics surface for health/telemetry integration."""

    def __init__(self):
        self._counts = Counter()
        self._latency_ms_total = 0.0
        self._lock = threading.Lock()

    def record(self, outcome: str, latency_ms: float = 0.0) -> None:
        with self._lock:
            self._counts[outcome] += 1
            if outcome == "success":
                self._latency_ms_total += latency_ms

    def snapshot(self) -> dict:
        with self._lock:
            successes = self._counts["success"]
            return {
                "publish_success_total": successes,
                "publish_drop_total": self._counts["drop"],
                "publish_latency_ms_total": self._latency_ms_total,
                "publish_latency_ms_average": (
                    self._latency_ms_total / successes if successes else 0.0
                ),
            }


METRICS = Metrics()


class RedisStreamTransport:
    def __init__(self, url: str, *, timeout_ms: int, retention: int):
        import redis
        timeout = timeout_ms / 1000.0
        self.redis = redis.Redis.from_url(
            url, decode_responses=True, socket_connect_timeout=timeout, socket_timeout=timeout
        )
        self.retention = retention

    @staticmethod
    def stream(tenant_id: str) -> str:
        return f"{NAMESPACE}:tenant:{tenant_id}:events"

    def next_sequence(self, tenant_id: str, correlation_id: str) -> int:
        return int(self.redis.incr(f"{NAMESPACE}:tenant:{tenant_id}:sequence:{correlation_id}"))

    def write(self, envelope: dict) -> str:
        return self.redis.xadd(
            self.stream(envelope["tenant_id"]),
            {"event": json.dumps(envelope, separators=(",", ":"), sort_keys=True)},
            maxlen=self.retention,
            approximate=True,
        )

    def replay(self, tenant_id: str, last_event_id: str, *, count: int = 100) -> list[dict]:
        """Return events strictly after a Redis/Last-Event-ID cursor."""
        rows = self.redis.xread({self.stream(tenant_id): last_event_id}, count=count, block=0)
        return [{**json.loads(fields["event"]), "stream_id": stream_id}
                for _stream, entries in rows for stream_id, fields in entries]


@dataclass(frozen=True)
class Pending:
    envelope: dict
    coalesce_key: str | None


class ShadowPublisher:
    def __init__(self, transport, *, max_progress: int = 256, start_worker: bool = True):
        self.transport = transport
        self.max_progress = max_progress
        self._lifecycle = deque()
        self._progress = OrderedDict()
        self._cv = threading.Condition()
        self._local_sequences = Counter()
        if start_worker:
            threading.Thread(target=self._run, daemon=True,
                             name="realtime-shadow-publisher").start()

    def _sequence(self, tenant_id: str, correlation_id: str) -> int:
        try:
            return self.transport.next_sequence(tenant_id, correlation_id)
        except Exception:
            key = (tenant_id, correlation_id)
            self._local_sequences[key] += 1
            return self._local_sequences[key]

    def submit(self, *, event_type: str, tenant_id: str, correlation_id: str,
               source: str, priority: str, payload: dict) -> bool:
        try:
            envelope = {
                "event_id": uuid.uuid4().hex,
                "event_version": EVENT_VERSION,
                "event_type": event_type,
                "occurred_at": datetime.now(timezone.utc).isoformat(),
                "tenant_id": tenant_id,
                "correlation_id": correlation_id,
                "source": source,
                "priority": priority,
                # Assigned by the publisher thread so even a slow/broken Redis sequence call
                # can never delay the authoritative worker path.
                "sequence": None,
                "payload": dict(payload),
            }
            # Only low-priority progress is replaceable. Lifecycle transitions retain order
            # and identity; they are never folded into one another.
            coalesce_key = (f"{tenant_id}:{correlation_id}:{event_type}"
                            if priority == "low" else None)
            with self._cv:
                if coalesce_key:
                    if coalesce_key not in self._progress and len(self._progress) >= self.max_progress:
                        self._progress.popitem(last=False)
                        METRICS.record("drop")
                    self._progress[coalesce_key] = Pending(envelope, coalesce_key)
                else:
                    self._lifecycle.append(Pending(envelope, None))
                self._cv.notify()
            return True
        except Exception:
            METRICS.record("drop")
            swallowed("realtime_shadow.ShadowPublisher.submit: shadow event was dropped")
            return False

    def _take(self) -> Pending:
        with self._cv:
            while not self._lifecycle and not self._progress:
                self._cv.wait()
            if self._lifecycle:
                return self._lifecycle.popleft()
            _key, item = self._progress.popitem(last=False)
            return item

    def publish_one(self) -> None:
        item = self._take()
        started = time.monotonic()
        try:
            item.envelope["sequence"] = self._sequence(
                item.envelope["tenant_id"], item.envelope["correlation_id"])
            self.transport.write(item.envelope)
            METRICS.record("success", (time.monotonic() - started) * 1000.0)
        except Exception:
            METRICS.record("drop")
            swallowed("realtime_shadow.ShadowPublisher.publish_one: Redis publish failed")

    def _run(self) -> None:
        while True:
            self.publish_one()


_publisher = None
_publisher_lock = threading.Lock()


def _configured_publisher():
    global _publisher
    if not enabled():
        return None
    if _publisher is None:
        with _publisher_lock:
            if _publisher is None:
                url = (os.environ.get("ACP_REALTIME_SHADOW_REDIS_URL") or "").strip()
                if not url:
                    return None
                _publisher = ShadowPublisher(RedisStreamTransport(
                    url,
                    timeout_ms=_integer("ACP_REALTIME_SHADOW_TIMEOUT_MS", 100),
                    retention=_integer("ACP_REALTIME_SHADOW_RETENTION", 10000),
                ))
    return _publisher


_DISCOVER = frozenset({"scan", "scan_folder", "scan_discover", "workspace_scan_discover"})
_ASSESS = frozenset({"scan_assess", "scan_batch", "scan_file", "workspace_scan_file",
                     "scan_finalize", "assess_trace", "rescore_file"})
_REMEDIATE = frozenset({"remediate_file", "apply_approved_values", "deliver_corrected_copy"})


def _domain(job_type: str) -> str:
    if job_type in _DISCOVER:
        return "discover"
    if job_type in _ASSESS:
        return "assess"
    if job_type in _REMEDIATE:
        return "remediate"
    return "worker"


def observe_job(job: dict, transition: str, *, worker_id: str, status: str | None = None,
                detail: dict | None = None) -> None:
    """Narrow worker adapter. Never raises and does nothing unless explicitly enabled."""
    publisher = _configured_publisher()
    if publisher is None:
        return
    try:
        payload = job.get("payload") or {}
        tenant = str(payload.get("tenant_id") or payload.get("owner") or
                     payload.get("user") or "system")
        correlation = str(job.get("scan_id") or payload.get("scan_id") or job["id"])
        domain = _domain(str(job.get("type") or ""))
        common = {
            "tenant_id": tenant, "correlation_id": correlation,
            "source": "acp.worker.shadow", "priority": "high",
            "payload": {"job_id": job["id"], "job_type": job.get("type"),
                        "worker_id": worker_id, "status": status, **(detail or {})},
        }
        # Separate facts let consumers follow the product lane, queue transition, or worker
        # execution without teaching worker.py about any downstream consumer.
        publisher.submit(event_type=f"{domain}.{transition}", **common)
        publisher.submit(event_type=f"queue.{transition}", **common)
        publisher.submit(event_type=f"worker.job.{transition}", **common)
    except Exception:
        METRICS.record("drop")
        swallowed("realtime_shadow.observe_job: shadow observer failed")


def metrics_snapshot() -> dict:
    return {"enabled": enabled(), **METRICS.snapshot()}
