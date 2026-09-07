"""Bounded load/isolation gate for the default-off canonical realtime path.

Two classes of check come out of one run (see TIMING_CHECKS and evaluate): structural checks,
which CI asserts on an in-memory run, and timing checks, which the report carries for the
staging gate to judge on real hardware. docs/runbooks/canonical-realtime-load-gate.md says why.
"""
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
    "warm_gateway_latency_p95_ms_max": 250.0,
    "submit_latency_p95_ms_max": 1.0,
    "coalesced_write_ratio_max": 0.10,
    "redis_bytes_per_event_max": 2048.0,
    "tenant_leakage_max": 0,
    "missing_retry_events_max": 0,
    "missing_dead_letter_events_max": 0,
    "missing_latest_progress_events_max": 0,
    "missing_warm_soak_events_max": 0,
    "progress_out_of_order_max": 0,
    "publisher_drops_max": 0,
}

# The checks whose outcome depends on the WALL CLOCK and the scheduler: a latency percentile,
# and the coalescing ratio, which is how many publisher drains happened to interleave with the
# submit loop (measured 12–14 progress writes for the same 600 submissions across 15 identical
# in-memory runs, and 13 and 15 on two CI runs of one commit that had bounded it at 12). Every
# other check is STRUCTURAL: it holds or fails by construction of the publisher and the store
# — no cross-tenant row, no lost lifecycle event, every job's final progress written, in order —
# whatever the machine is doing. The two classes decide differently: the staging gate's GO
# requires both (a slow gateway is a real NO-GO for enabling the feature), while the in-memory
# CI run asserts only the structural class and REPORTS the timing class, because a p95 measured
# on a shared CI runner is evidence about the runner, and a test that fails on it is a flake
# waiting to happen rather than a finding.
TIMING_CHECKS = frozenset({
    "gateway_latency_p95_ms", "warm_gateway_latency_p95_ms",
    "submit_latency_p95_ms", "coalesced_write_ratio",
})


def evaluate(metrics: dict) -> dict:
    """Decide from a metrics dict alone — no clock, no threads — so the verdict is unit-testable
    with fixed inputs. Returns the per-check booleans, the same booleans split by class, and two
    decisions: `decision` (GO only if every check holds; what the staging gate exits on) and
    `structural_decision` (GO if every non-timing check holds; what CI asserts)."""
    checks = {
        name.removesuffix("_max"): metrics[name.removesuffix("_max")] <= threshold
        for name, threshold in THRESHOLDS.items()
    }
    checks["missing_failed_events"] = metrics["missing_failed_events"] == 0
    checks["persistent_client_warm_soak"] = metrics["warm_batch_count"] >= 1
    timing = {name: ok for name, ok in checks.items() if name in TIMING_CHECKS}
    structural = {name: ok for name, ok in checks.items() if name not in TIMING_CHECKS}
    return {
        "checks": checks,
        "timing_checks": timing,
        "structural_checks": structural,
        "structural_decision": "GO" if all(structural.values()) else "NO-GO",
        "decision": "GO" if all(checks.values()) else "NO-GO",
    }


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction))]


def out_of_order_progress_jobs(events) -> int:
    """How many jobs have a written progress value that does not exceed the one before it, in
    stream order. Coalescing may DROP intermediate progress; it must never reorder it. Pure, so
    the invariant is testable on a handful of events rather than inferred from a live run."""
    progress_by_job: dict[str, list[int]] = {}
    for event in events:
        if event.kind == "assess.progressed":
            progress_by_job.setdefault(event.job_id, []).append(
                int(event.payload.get("progress", -1)))
    return sum(
        any(later <= earlier for earlier, later in zip(values, values[1:]))
        for values in progress_by_job.values()
    )


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

    def ping(self):
        if self.delay_ms:
            time.sleep(self.delay_ms / 1000)
        return True

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
    """Record each event's publish-to-observable latency at its own write boundary.

    `clock` returns nanoseconds and defaults to the real monotonic counter. A test hands in a
    fake so the per-boundary accounting below can be asserted exactly, rather than against a
    sleep whose real duration is whatever the runner allowed."""

    def __init__(self, transport, *, clock=time.perf_counter_ns):
        self.transport = transport
        self.redis = transport.redis
        self._clock = clock
        self._latencies_ms: dict[str, float] = {}
        self._batches: list[dict] = []
        self._warmup_latency_ms: float | None = None
        self._active_writes = 0
        self._lock = threading.Lock()

    def warmup(self):
        started_ns = self._clock()
        try:
            return self.transport.warmup()
        finally:
            with self._lock:
                self._warmup_latency_ms = (self._clock() - started_ns) / 1_000_000

    def write(self, event):
        started_ns = self._clock()
        with self._lock:
            self._active_writes += 1
        try:
            row_id = self.transport.write(event)
            latency_ms = (self._clock() - started_ns) / 1_000_000
            with self._lock:
                self._latencies_ms[event.event_id] = latency_ms
                self._batches.append({"latency_ms": latency_ms, "size": 1,
                                      "event_ids": [event.event_id]})
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
        started_ns = self._clock()
        with self._lock:
            self._active_writes += 1
        try:
            results = self.transport.write_many(events)
            latency_ms = (self._clock() - started_ns) / 1_000_000
            with self._lock:
                self._latencies_ms.update({event.event_id: latency_ms for event in events})
                self._batches.append({"latency_ms": latency_ms, "size": len(events),
                                      "event_ids": [event.event_id for event in events]})
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

    def batch_observations(self) -> list[dict]:
        with self._lock:
            return [dict(batch) for batch in self._batches]

    def warmup_latency_ms(self) -> float:
        with self._lock:
            return self._warmup_latency_ms or 0.0


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

        def wait_for_drain(minimum_written: int) -> int:
            deadline = time.monotonic() + config.timeout_seconds
            while time.monotonic() < deadline:
                written = sum(len(memory.rows(key)) for key in keys) if memory else sum(
                    int(transport.redis.xlen(key)) for key in keys)
                with publisher._cv:
                    pending = len(publisher._lifecycle) + len(publisher._progress)
                if (pending == 0 and not observed_transport.has_active_writes()
                        and written >= minimum_written):
                    return written
                time.sleep(0.01)
            raise TimeoutError("publisher did not drain within the gate timeout")

        first_wave_written = wait_for_drain(expected_lossless + expected_progress)

        # A legal burst can fit entirely in the publisher's first batch.  Send a distinct second
        # wave only after that batch drains so the same persistent client always supplies a real
        # warm-path sample; do not change production batching or coalescing to manufacture one.
        for owner in owners:
            publisher.submit(
                kind="assess.started", owner=owner, correlation_id=f"warm-soak-{run_id}",
                scan_id=f"warm-soak-{run_id}", job_id=f"warm-soak-{owner}",
                worker_id="load-gate", payload={"warm_soak": True},
            )
        wait_for_drain(first_wave_written + config.tenants)

        reader_for_replay, reader = reader, None
        per_owner = asyncio.run(_replay_all(reader_for_replay, owners))
        all_events = [event for rows in per_owner.values() for _row_id, event in rows]
        gateway_latencies = [
            observed_transport.latency_ms(event.event_id) for event in all_events
        ]
        batches = observed_transport.batch_observations()
        cold_batch = batches[:1]
        warm_batches = batches[1:]
        warm_gateway_latencies = [
            batch["latency_ms"]
            for batch in warm_batches
            for _event_id in batch["event_ids"]
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
        warm_soak_events = sum(event.payload.get("warm_soak") is True for event in all_events)
        # Structural — the submit loop is one thread and the publisher drains each bucket in
        # order — so it holds regardless of how many drains the scheduler interleaved.
        # `all_events` is in replay (stream) order per owner, which is what the invariant is on.
        progress_out_of_order = out_of_order_progress_jobs(all_events)
        metrics = {
            "gateway_latency_p95_ms": percentile(gateway_latencies, .95),
            "connection_warmup_latency_ms": observed_transport.warmup_latency_ms(),
            "cold_first_batch_latency_ms": cold_batch[0]["latency_ms"] if cold_batch else 0.0,
            "cold_first_batch_size": cold_batch[0]["size"] if cold_batch else 0,
            "warm_gateway_latency_p95_ms": percentile(warm_gateway_latencies, .95),
            "warm_batch_count": len(warm_batches),
            "warm_batch_size_p95": percentile(
                [float(batch["size"]) for batch in warm_batches], .95
            ),
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
            "missing_warm_soak_events": max(0, config.tenants - warm_soak_events),
            "missing_failed_events": max(0, config.tenants - failed_events),
            "progress_out_of_order": progress_out_of_order,
            "publisher_drops": (
                realtime_shadow.METRICS.snapshot()["publish_drop_total"] - drops_before
            ),
        }
        return {"schema_version": 1, "mode": "redis" if config.redis_url else "in-memory-ci",
                "config": public_config(config), "thresholds": THRESHOLDS, "metrics": metrics,
                **evaluate(metrics)}
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
