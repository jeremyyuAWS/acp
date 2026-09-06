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


@dataclass(frozen=True)
class GateConfig:
    tenants: int = 4
    jobs_per_tenant: int = 8
    progress_per_job: int = 100
    redis_delay_ms: float = 0.5
    redis_url: str | None = None
    timeout_seconds: float = 15.0


async def _replay_all(store, scope):
    return await store.replay(scope, "0-0", limit=500)


def run(config: GateConfig) -> dict:
    if config.tenants < 2 or config.tenants * config.jobs_per_tenant * 4 > 500:
        raise ValueError("gate requires 2+ tenants and no more than 500 retained events")
    run_id = uuid4().hex
    owners = [f"realtime-gate+{run_id}-{n}@example.invalid" for n in range(config.tenants)]
    keys = [stream_key(owner_scope(owner)) for owner in owners]
    memory = None
    cleanup = None
    if config.redis_url:
        import redis
        sync_redis = redis.Redis.from_url(config.redis_url, decode_responses=True)
        transport = realtime_shadow.RedisStreamTransport(
            config.redis_url, timeout_ms=500, retention=10_000,
        )
        from redis import asyncio as async_redis
        reader = async_redis.Redis.from_url(config.redis_url, decode_responses=True)
        cleanup = lambda: sync_redis.delete(*keys)
    else:
        memory = MemoryRedis(config.redis_delay_ms)
        transport = realtime_shadow.RedisStreamTransport.__new__(realtime_shadow.RedisStreamTransport)
        transport.redis = memory
        transport.retention = 10_000
        reader = AsyncMemoryRedis(memory)

    publisher = realtime_shadow.ShadowPublisher(transport)
    drops_before = realtime_shadow.METRICS.snapshot()["publish_drop_total"]
    submit_latencies = []
    progress_submitted = config.tenants * config.jobs_per_tenant * config.progress_per_job
    expected_lossless = config.tenants * (config.jobs_per_tenant * 2 + 3)
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
            if pending == 0 and written >= expected_lossless:
                break
            time.sleep(0.01)
        else:
            raise TimeoutError("publisher did not drain within the gate timeout")

        store = RedisEventStore(reader)
        per_owner = {owner: asyncio.run(_replay_all(store, owner_scope(owner))) for owner in owners}
        all_events = [event for rows in per_owner.values() for _row_id, event in rows]
        observed_ns = time.perf_counter_ns()
        gateway_latencies = [
            (observed_ns - int(event.payload["emitted_ns"])) / 1_000_000 for event in all_events
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
                "config": asdict(config), "thresholds": THRESHOLDS, "metrics": metrics,
                "checks": checks, "decision": "GO" if all(checks.values()) else "NO-GO"}
    finally:
        realtime_shadow._publisher = previous
        if previous_enabled is None:
            os.environ.pop("ACP_REALTIME_SHADOW_ENABLED", None)
        else:
            os.environ["ACP_REALTIME_SHADOW_ENABLED"] = previous_enabled
        if cleanup:
            cleanup()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--redis-url", help="isolated staging Redis URL; generated streams are deleted")
    parser.add_argument("--output", default="-")
    args = parser.parse_args()
    result = run(GateConfig(redis_url=args.redis_url))
    rendered = json.dumps(result, indent=2, sort_keys=True)
    if args.output == "-":
        print(rendered)
    else:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(rendered + "\n")
    return 0 if result["decision"] == "GO" else 1


if __name__ == "__main__":
    raise SystemExit(main())
