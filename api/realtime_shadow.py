"""Default-off shadow publisher for the versioned realtime event contract.

This module observes the durable worker; it is not part of job correctness.  Calls enqueue
best-effort work and return immediately.  Redis I/O happens on a daemon thread with bounded
connect/read timeouts and a distinct ``realtime:v1`` key namespace.
"""
from __future__ import annotations

from collections import Counter, OrderedDict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
import os
import threading
import time

from realtime_events import KIND_SPECS, RealtimeEvent, coalescing_bucket, owner_scope, stream_key
from realtime_feature import publisher_enabled
from swallowed import swallowed

def enabled() -> bool:
    return publisher_enabled()


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

    def write(self, event: RealtimeEvent) -> str:
        return self.redis.xadd(
            stream_key(event.owner_scope),
            {"event": event.to_json(), "event_id": event.event_id},
            maxlen=self.retention,
            approximate=True,
        )

    def write_many(self, events: list[RealtimeEvent]) -> list:
        """Write one ordered batch with a single Redis network round trip."""
        if not hasattr(self.redis, "pipeline"):
            # Lightweight test/in-process transports need not implement redis-py's pipeline API.
            return [self.write(event) for event in events]
        pipe = self.redis.pipeline(transaction=False)
        for event in events:
            pipe.xadd(
                stream_key(event.owner_scope),
                {"event": event.to_json(), "event_id": event.event_id},
                maxlen=self.retention,
                approximate=True,
            )
        # Keep individual Redis command failures in the result so the publisher can report
        # exactly which events were dropped instead of turning a partial batch into all-or-none.
        return pipe.execute(raise_on_error=False)


@dataclass(frozen=True)
class Pending:
    event: RealtimeEvent
    bucket: tuple[str, str] | None


class ShadowPublisher:
    def __init__(self, transport, *, max_progress: int = 256, max_batch: int = 128,
                 start_worker: bool = True):
        self.transport = transport
        self.max_progress = max_progress
        self.max_batch = max(1, max_batch)
        self._lifecycle = deque()
        self._progress = OrderedDict()
        self._cv = threading.Condition()
        self._local_sequences = Counter()
        self._sequence_lock = threading.Lock()
        if start_worker:
            threading.Thread(target=self._run, daemon=True,
                             name="realtime-shadow-publisher").start()

    def submit(self, *, kind: str, owner: str, correlation_id: str,
               payload: dict, scan_id: str | None = None, job_id: str | None = None,
               worker_id: str | None = None, coalesce_key: str | None = None) -> bool:
        try:
            scope = owner_scope(owner)
            sequence_key = (scope, correlation_id)
            with self._sequence_lock:
                self._local_sequences[sequence_key] += 1
                source_seq = self._local_sequences[sequence_key]
            event = RealtimeEvent(
                kind=kind, owner_scope=scope, payload=dict(payload),
                occurred_at=datetime.now(timezone.utc),
                source_seq=source_seq, scan_id=scan_id,
                job_id=job_id, worker_id=worker_id, correlation_id=correlation_id,
                coalesce_key=coalesce_key,
            )
            bucket = coalescing_bucket(event)
            with self._cv:
                if bucket:
                    if bucket not in self._progress and len(self._progress) >= self.max_progress:
                        self._progress.popitem(last=False)
                        METRICS.record("drop")
                    self._progress[bucket] = Pending(event, bucket)
                else:
                    self._lifecycle.append(Pending(event, None))
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

    def _take_batch(self) -> list[Pending]:
        """Take a bounded snapshot, preserving lifecycle priority and progress order."""
        with self._cv:
            while not self._lifecycle and not self._progress:
                self._cv.wait()
            batch = []
            while self._lifecycle and len(batch) < self.max_batch:
                batch.append(self._lifecycle.popleft())
            while not self._lifecycle and self._progress and len(batch) < self.max_batch:
                _key, item = self._progress.popitem(last=False)
                batch.append(item)
            return batch

    def publish_one(self) -> None:
        item = self._take()
        started = time.monotonic()
        try:
            self.transport.write(item.event)
            METRICS.record("success", (time.monotonic() - started) * 1000.0)
        except Exception:
            METRICS.record("drop")
            swallowed("realtime_shadow.ShadowPublisher.publish_one: Redis publish failed")

    def publish_batch(self) -> None:
        items = self._take_batch()
        started = time.monotonic()
        try:
            events = [item.event for item in items]
            batch_writer = getattr(self.transport, "write_many", None)
            # The publisher contract predates Redis batching and intentionally supports small
            # observing/in-process transports. Keep that boundary compatible; Redis still takes
            # the one-round-trip write_many path while simple transports remain truthful.
            results = (batch_writer(events) if callable(batch_writer)
                       else [self.transport.write(event) for event in events])
        except Exception:
            for _item in items:
                METRICS.record("drop")
            swallowed("realtime_shadow.ShadowPublisher.publish_batch: Redis batch failed")
            return
        latency_ms = (time.monotonic() - started) * 1000.0
        for result in results:
            if isinstance(result, Exception):
                METRICS.record("drop")
                swallowed("realtime_shadow.ShadowPublisher.publish_batch: Redis publish failed")
            else:
                METRICS.record("success", latency_ms)

    def _run(self) -> None:
        while True:
            self.publish_batch()


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
        owner = str(payload.get("tenant_id") or payload.get("owner") or
                     payload.get("user") or "system")
        correlation = str(job.get("scan_id") or payload.get("scan_id") or job["id"])
        domain = _domain(str(job.get("type") or ""))
        payload_out = {"job_type": job.get("type"), "status": status,
                       "transition": transition, **(detail or {})}
        common = {"owner": owner, "correlation_id": correlation, "payload": payload_out,
                  "scan_id": job.get("scan_id") or payload.get("scan_id"),
                  "job_id": str(job["id"]), "worker_id": worker_id}
        transition_kind = {
            "started": f"{domain}.started", "complete": f"{domain}.completed",
            "cancelled": f"{domain}.cancelled", "failed": f"{domain}.failed",
            "fail": f"{domain}.failed", "dead": f"{domain}.failed",
            "retry": "queue.job_delayed", "deployment_requeue": "queue.job_delayed",
        }.get(transition)
        if transition_kind in KIND_SPECS:
            publisher.submit(kind=transition_kind, **common)
        if transition == "dead":
            publisher.submit(kind="queue.job_dead_lettered", **common)
    except Exception:
        METRICS.record("drop")
        swallowed("realtime_shadow.observe_job: shadow observer failed")


def metrics_snapshot() -> dict:
    return {"enabled": enabled(), **METRICS.snapshot()}
