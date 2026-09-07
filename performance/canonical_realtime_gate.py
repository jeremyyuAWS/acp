"""Bounded load/isolation gate for the default-off canonical realtime path."""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict, dataclass
import json
import os
import sys
import threading
import time
from uuid import uuid4

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = os.path.join(ROOT, "api")
if API not in sys.path:
    sys.path.insert(0, API)

import realtime_shadow
from realtime_event_store import RedisEventStore
from realtime_events import owner_scope, stream_key


THRESHOLDS = {
    "gateway_latency_p95_ms_max": 250.0,
    "submit_latency_p95_ms_max": 1.0,
    "coalesced_write_ratio_max": 0.10,
    "redis_bytes_per_event_max": 2048.0,
    "tenant_leakage_max": 0,
    "missing_retry_events_max": 0,
    "missing_dead_letter_events_max": 0,
    "missing_latest_progress_events_max": 0,
    "publisher_drops_max": 0,
}


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction))]


class MemoryRedis:
    """Thread-safe Redis Streams subset with optional write pressure."""

    def __init__(self, delay_ms: float = 0.5):
        self.delay_ms = delay_ms
        self.streams: dict[str, list[tuple[str, dict]]] = {}
        self._clock = 0
        self._lock = threading.Lock()

    def xadd(self, key, fields, maxlen=None, approximate=True):
        if self.delay_ms:
            time.sleep(self.delay_ms / 1000)
        with self._lock:
            self._clock += 1
            row_id = f"{self._clock}-0"
            rows = self.streams.setdefault(key, [])
            rows.append((row_id, dict(fields)))
            if maxlen and len(rows) > maxlen:
                del rows[:len(rows) - maxlen]
            return row_id

    def rows(self, key):
        with self._lock:
            return list(self.streams.get(key, ()))

    def memory_bytes(self, keys):
        with self._lock:
            return len(json.dumps({key: self.streams.get(key, []) for key in keys}))


class AsyncMemoryRedis:
    def __init__(self, redis: MemoryRedis):
        self.redis = redis

    async def xrange(self, key, min="-", max="+", count=None):
        rows = self.redis.rows(key)
        if str(min).startswith("("):
            cursor = tuple(map(int, str(min)[1:].split("-")))
            rows = [row for row in rows if tuple(map(int, row[0].split("-"))) > cursor]
        return rows[:count] if count else rows

    async def xrevrange(self, key, max="+", min="-", count=None):
        rows = list(reversed(self.redis.rows(key)))
        return rows[:count] if count else rows

    async def xread(self, streams, count, block):
        return []

    async def aclose(self):
        return None


class ObservedTransport:
    """Record each event's publish-to-observable latency at its own write boundary."""

    def __init__(self, transport):
        self.transport = transport
        self.redis = transport.redis
        self._latencies_ms: dict[str, float] = {}
        self._active_writes = 0
        self._lock = threading.Lock()

    def write(self, event):
        started_ns = time.perf_counter_ns()
        with self._lock:
            self._active_writes += 1
        try:
            row_id = self.transport.write(event)
            latency_ms = (time.perf_counter_ns() - started_ns) / 1_000_000
            with self._lock:
                self._latencies_ms[event.event_id] = latency_ms
            return row_id
        finally:
            with self._lock:
                self._active_writes -= 1

    def write_many(self, events):
        # The in-memory transport has no atomic pipeline, so preserve each write's own
        # observation boundary.  A real Redis pipeline makes the whole batch observable when
        # execute returns; every event in that batch therefore shares that measured duration.
        if not hasattr(self.redis, "pipeline"):
            return [self.write(event) for event in events]
        started_ns = time.perf_counter_ns()
        with self._lock:
            self._active_writes += 1
        try:
            results = self.transport.write_many(events)
            latency_ms = (time.perf_counter_ns() - started_ns) / 1_000_000
            with self._lock:
                self._latencies_ms.update({event.event_id: latency_ms for event in events})
            return results
        finally:
            with self._lock:
                self._active_writes -= 1

    def has_active_writes(self) -> bool:
        with self._lock:
            return self._active_writes > 0

    def latency_ms(self, event_id: str) -> float:
        with self._lock:
            return self._latencies_ms[event_id]


@dataclass(frozen=True)
class GateConfig:
    tenants: int = 4
    jobs_per_tenant: int = 8
    progress_per_job: int = 100
    redis_delay_ms: float = 0.5
    redis_url: str | None = None
    timeout_seconds: float = 15.0


def public_config(config: GateConfig) -> dict:
    """Render configuration without copying credentials into reports or logs."""
    rendered = asdict(config)
    rendered["redis_url"] = "configured" if config.redis_url else None
    return rendered


async def _replay_all(reader, owners):
    store = RedisEventStore(reader)
    try:
        return {
            owner: await store.replay(owner_scope(owner), "0-0", limit=500)
            for owner in owners
        }
    finally:
        await store.close()


def run(config: GateConfig) -> dict:
    if config.tenants < 2 or config.tenants * config.jobs_per_tenant * 4 > 500:
        raise ValueError("gate requires 2+ tenants and no more than 500 retained events")
    run_id = uuid4().hex
    owners = [f"realtime-gate+{run_id}-{n}@example.invalid" for n in range(config.tenants)]
    keys = [stream_key(owner_scope(owner)) for owner in owners]
    memory = None
    reader = None
    sync_redis = None
    if config.redis_url:
        import redis
        sync_redis = redis.Redis.from_url(config.redis_url, decode_responses=True)
        transport = realtime_shadow.RedisStreamTransport(
            config.redis_url, timeout_ms=500, retention=10_000,
        )
        from redis import asyncio as async_redis
        reader = async_redis.Redis.from_url(config.redis_url, decode_responses=True)
    else:
        memory = MemoryRedis(config.redis_delay_ms)
        transport = realtime_shadow.RedisStreamTransport.__new__(realtime_shadow.RedisStreamTransport)
        transport.redis = memory
        transport.retention = 10_000
        reader = AsyncMemoryRedis(memory)

    observed_transport = ObservedTransport(transport)
    publisher = realtime_shadow.ShadowPublisher(observed_transport)
    drops_before = realtime_shadow.METRICS.snapshot()["publish_drop_total"]
    submit_latencies = []
    progress_submitted = config.tenants * config.jobs_per_tenant * config.progress_per_job
    expected_lossless = config.tenants * (config.jobs_per_tenant * 2 + 3)
    expected_progress = config.tenants * config.jobs_per_tenant
    previous = realtime_shadow._publisher
    previous_enabled = os.environ.get("ACP_REALTIME_SHADOW_ENABLED")
    try:
        realtime_shadow._publisher = publisher
        os.environ["ACP_REALTIME_SHADOW_ENABLED"] = "1"
        for owner in owners:
            for job_number in range(config.jobs_per_tenant):
                job_id = f"{owner}:{job_number}"
                scan_id = f"scan-{job_number}"
                common = dict(owner=owner, correlation_id=scan_id, scan_id=scan_id,
                              job_id=job_id, worker_id="load-gate")
                emitted = time.perf_counter_ns()
                publisher.submit(kind="assess.started", payload={"emitted_ns": emitted}, **common)
                for progress in range(config.progress_per_job):
                    started = time.perf_counter_ns()
                    publisher.submit(
                        kind="assess.progressed",
                        payload={"progress": progress, "emitted_ns": started},
                        coalesce_key=job_id, **common,
                    )
                    submit_latencies.append((time.perf_counter_ns() - started) / 1_000_000)
                emitted = time.perf_counter_ns()
                publisher.submit(kind="assess.completed", payload={"emitted_ns": emitted}, **common)
            special = {"id": f"retry-{owner}", "type": "scan_file", "scan_id": "retry-scan",
                       "payload": {"owner": owner}}
            now = time.perf_counter_ns()
            realtime_shadow.observe_job(special, "retry", worker_id="load-gate", status="pending",
                                        detail={"emitted_ns": now})
            now = time.perf_counter_ns()
            realtime_shadow.observe_job(special, "dead", worker_id="load-gate", status="failed",
                                        detail={"emitted_ns": now})

        deadline = time.monotonic() + config.timeout_seconds
        while time.monotonic() < deadline:
            written = sum(len(memory.rows(key)) for key in keys) if memory else sum(
                int(transport.redis.xlen(key)) for key in keys)
            with publisher._cv:
                pending = len(publisher._lifecycle) + len(publisher._progress)
            if (pending == 0 and not observed_transport.has_active_writes()
                    and written >= expected_lossless + expected_progress):
                break
            time.sleep(0.01)
        else:
            raise TimeoutError("publisher did not drain within the gate timeout")

        reader_for_replay, reader = reader, None
        per_owner = asyncio.run(_replay_all(reader_for_replay, owners))
        all_events = [event for rows in per_owner.values() for _row_id, event in rows]
        gateway_latencies = [
            observed_transport.latency_ms(event.event_id) for event in all_events
        ]
        leakage = sum(
            event.owner_scope != owner_scope(owner)
            for owner, rows in per_owner.items() for _row_id, event in rows
        )
        retry_events = sum(event.kind == "queue.job_delayed" for event in all_events)
        dead_events = sum(event.kind == "queue.job_dead_lettered" for event in all_events)
        failed_events = sum(event.kind == "assess.failed" for event in all_events)
        retained = len(all_events)
        if memory:
            redis_bytes = memory.memory_bytes(keys)
        else:
            redis_bytes = sum(int(transport.redis.memory_usage(key) or 0) for key in keys)
        progress_written = sum(event.kind == "assess.progressed" for event in all_events)
        latest_progress_jobs = {
            event.job_id for event in all_events
            if event.kind == "assess.progressed"
            and event.payload.get("progress") == config.progress_per_job - 1
        }
        metrics = {
            "gateway_latency_p95_ms": percentile(gateway_latencies, .95),
            "submit_latency_p95_ms": percentile(submit_latencies, .95),
            "coalesced_write_ratio": progress_written / max(progress_submitted, 1),
            "progress_submitted": progress_submitted,
            "progress_written": progress_written,
            "retained_events": retained,
            "redis_bytes_per_event": redis_bytes / max(retained, 1),
            "tenant_leakage": leakage,
            "missing_retry_events": max(0, config.tenants - retry_events),
            "missing_dead_letter_events": max(0, config.tenants - dead_events),
            "missing_latest_progress_events": max(0, expected_progress - len(latest_progress_jobs)),
            "missing_failed_events": max(0, config.tenants - failed_events),
            "publisher_drops": (
                realtime_shadow.METRICS.snapshot()["publish_drop_total"] - drops_before
            ),
        }
        checks = {
            name.removesuffix("_max"): metrics[name.removesuffix("_max")] <= threshold
            for name, threshold in THRESHOLDS.items()
        }
        checks["missing_failed_events"] = metrics["missing_failed_events"] == 0
        return {"schema_version": 1, "mode": "redis" if config.redis_url else "in-memory-ci",
                "config": public_config(config), "thresholds": THRESHOLDS, "metrics": metrics,
                "checks": checks, "decision": "GO" if all(checks.values()) else "NO-GO"}
    finally:
        realtime_shadow._publisher = previous
        if previous_enabled is None:
            os.environ.pop("ACP_REALTIME_SHADOW_ENABLED", None)
        else:
            os.environ["ACP_REALTIME_SHADOW_ENABLED"] = previous_enabled
        if reader is not None:
            asyncio.run(reader.aclose())
        if sync_redis is not None:
            sync_redis.delete(*keys)
            sync_redis.close()
        if memory is None and hasattr(transport.redis, "close"):
            transport.redis.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--redis-env", default="ACP_REALTIME_GATE_REDIS_URL",
                        help="name of the environment variable holding the isolated Redis URL")
    parser.add_argument("--output", default="-")
    args = parser.parse_args()
    result = run(GateConfig(redis_url=os.environ.get(args.redis_env)))
    rendered = json.dumps(result, indent=2, sort_keys=True)
    if args.output == "-":
        print(rendered)
    else:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(rendered + "\n")
    return 0 if result["decision"] == "GO" else 1


if __name__ == "__main__":
    raise SystemExit(main())
