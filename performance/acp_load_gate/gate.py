"""A dependency-free, deterministic queue/load model for ACP release gating.

The model is intentionally isolated from ACP runtime code and cloud resources.  It gives the
team a repeatable workload/chaos contract before a staging run: multi-tenant submissions,
mixed Office/PDF documents, fair claims, transient Redis/Postgres faults, retry/dead-letter
behaviour, and worker interruption during a simulated deployment.
"""

from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import math
import random
import statistics
import sys
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "1.0"


@dataclass
class Job:
    id: str
    tenant: str
    scan: str
    document: str
    file_type: str
    stage: str
    created_at: float
    duration: float
    max_attempts: int
    attempts: int = 0
    eligible_at: float = 0.0
    first_started_at: float | None = None
    completed_at: float | None = None
    interrupted: bool = False
    queue_wait: float = 0.0
    execution_time: float = 0.0


@dataclass(order=True)
class Event:
    at: float
    sequence: int
    kind: str = field(compare=False)
    payload: Any = field(compare=False, default=None)


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = (len(ordered) - 1) * percentile
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


def _distribution(values: list[float]) -> dict[str, float]:
    return {
        "p50": round(_percentile(values, 0.50), 3),
        "p95": round(_percentile(values, 0.95), 3),
        "p99": round(_percentile(values, 0.99), 3),
        "max": round(max(values, default=0.0), 3),
    }


def _jain(values: list[int]) -> float:
    if not values or not sum(values):
        return 1.0
    return (sum(values) ** 2) / (len(values) * sum(v * v for v in values))


def _stable_id(*parts: str) -> str:
    return hashlib.sha256("\x00".join(parts).encode()).hexdigest()[:16]


def _validate(config: dict[str, Any]) -> None:
    required = ("name", "seed", "workload", "workers", "faults", "thresholds")
    missing = [key for key in required if key not in config]
    if missing:
        raise ValueError(f"scenario missing required fields: {', '.join(missing)}")
    workload = config["workload"]
    if not workload.get("tenants") or not workload.get("file_mix"):
        raise ValueError("workload.tenants and workload.file_mix must not be empty")
    mix_total = sum(float(item["weight"]) for item in workload["file_mix"])
    if not math.isclose(mix_total, 1.0, abs_tol=1e-6):
        raise ValueError(f"file_mix weights must sum to 1.0 (got {mix_total})")
    for name in ("redis_error_rate", "database_error_rate", "terminal_error_rate"):
        rate = float(config["faults"].get(name, 0))
        if not 0 <= rate <= 1:
            raise ValueError(f"faults.{name} must be between 0 and 1")


def _choose_mix(rng: random.Random, mix: list[dict[str, Any]]) -> dict[str, Any]:
    point = rng.random()
    cumulative = 0.0
    for item in mix:
        cumulative += float(item["weight"])
        if point <= cumulative:
            return item
    return mix[-1]


def _build_jobs(config: dict[str, Any], rng: random.Random) -> tuple[list[Job], int]:
    workload = config["workload"]
    jobs: list[Job] = []
    documents = 0
    for tenant_index, tenant_config in enumerate(workload["tenants"]):
        tenant = tenant_config["name"]
        scans = int(tenant_config.get("scans", workload["scans_per_tenant"]))
        docs = int(tenant_config.get("documents_per_scan", workload["documents_per_scan"]))
        submit_base = tenant_index * float(workload.get("tenant_submit_stagger_seconds", 0))
        for scan_index in range(scans):
            scan = f"{tenant}-scan-{scan_index + 1}"
            submitted = submit_base + scan_index * float(workload.get("scan_submit_stagger_seconds", 0))
            for document_index in range(docs):
                documents += 1
                mix = _choose_mix(rng, workload["file_mix"])
                file_type = mix["extension"].lower()
                document = f"{scan}-document-{document_index + 1}{file_type}"
                jitter = rng.uniform(1 - float(mix.get("duration_jitter", 0)),
                                     1 + float(mix.get("duration_jitter", 0)))
                assess_duration = float(mix["assess_seconds"]) * jitter
                jobs.append(Job(
                    id=_stable_id(scan, document, "assess"), tenant=tenant, scan=scan,
                    document=document, file_type=file_type, stage="assess",
                    created_at=submitted, eligible_at=submitted, duration=assess_duration,
                    max_attempts=int(config["faults"]["max_attempts"]),
                ))
    return jobs, documents


def run_scenario(config: dict[str, Any]) -> dict[str, Any]:
    """Run one scenario and return a stable, machine-readable gate result."""
    _validate(config)
    rng = random.Random(int(config["seed"]))
    initial_jobs, document_count = _build_jobs(config, rng)
    waiting: dict[str, deque[Job]] = defaultdict(deque)
    known_tenants = [item["name"] for item in config["workload"]["tenants"]]
    last_served = {tenant: -1.0 for tenant in known_tenants}
    events: list[Event] = []
    sequence = 0

    def schedule(at: float, kind: str, payload: Any = None) -> None:
        nonlocal sequence
        sequence += 1
        heapq.heappush(events, Event(at, sequence, kind, payload))

    for job in initial_jobs:
        schedule(job.created_at, "enqueue", job)
    deploy = config["faults"].get("deploy")
    if deploy:
        schedule(float(deploy["at_seconds"]), "deploy_start")
        schedule(float(deploy["at_seconds"]) + float(deploy["downtime_seconds"]), "deploy_end")

    worker_count = int(config["workers"])
    idle_workers = set(range(worker_count))
    active: dict[int, tuple[Job, int, float]] = {}
    generation = Counter()
    completed: list[Job] = []
    dead: list[Job] = []
    retries = 0
    errors = Counter()
    interruptions = 0
    recovered_interruptions = 0
    deploy_active = False
    now = 0.0

    def enqueue(job: Job) -> None:
        waiting[job.tenant].append(job)

    def claim() -> Job | None:
        eligible = [tenant for tenant, queue in waiting.items()
                    if queue and queue[0].eligible_at <= now]
        if not eligible:
            return None
        tenant = min(eligible, key=lambda item: (last_served[item], waiting[item][0].created_at, item))
        last_served[tenant] = now
        return waiting[tenant].popleft()

    def dispatch() -> None:
        if deploy_active:
            return
        while idle_workers:
            job = claim()
            if job is None:
                future = [queue[0].eligible_at for queue in waiting.values() if queue]
                if future:
                    schedule(min(future), "wake")
                return
            worker = min(idle_workers)
            idle_workers.remove(worker)
            job.attempts += 1
            job.queue_wait += max(0.0, now - max(job.created_at, job.eligible_at))
            if job.first_started_at is None:
                job.first_started_at = now
            generation[job.id] += 1
            token = generation[job.id]
            finish = now + job.duration
            active[worker] = (job, token, now)
            schedule(finish, "finish", (worker, job, token))

    while events or active or any(waiting.values()):
        if not events:
            raise RuntimeError("simulation stalled with unfinished jobs")
        event = heapq.heappop(events)
        now = event.at
        if event.kind == "enqueue":
            enqueue(event.payload)
        elif event.kind == "deploy_start":
            deploy_active = True
            interrupted_jobs = list(active.items())
            active.clear()
            for worker, (job, _token, _started) in interrupted_jobs:
                idle_workers.add(worker)
                generation[job.id] += 1
                interruptions += 1
                job.interrupted = True
                job.execution_time += max(0.0, now - _started)
                job.eligible_at = now + float(deploy.get("retry_delay_seconds", 0))
                enqueue(job)
        elif event.kind == "deploy_end":
            deploy_active = False
        elif event.kind == "finish":
            worker, job, token = event.payload
            current = active.get(worker)
            if current is None or current[0].id != job.id or token != generation[job.id]:
                continue
            del active[worker]
            idle_workers.add(worker)
            job.execution_time += job.duration
            roll = rng.random()
            redis = float(config["faults"].get("redis_error_rate", 0))
            database = float(config["faults"].get("database_error_rate", 0))
            terminal = float(config["faults"].get("terminal_error_rate", 0))
            failure = None
            if roll < redis:
                failure = "redis"
            elif roll < redis + database:
                failure = "database"
            elif roll < redis + database + terminal:
                failure = "terminal"
            if failure:
                errors[failure] += 1
                if failure == "terminal" or job.attempts >= job.max_attempts:
                    job.completed_at = now
                    dead.append(job)
                else:
                    retries += 1
                    backoff = float(config["faults"].get("retry_backoff_seconds", 0)) * job.attempts
                    job.eligible_at = now + backoff
                    enqueue(job)
            else:
                job.completed_at = now
                completed.append(job)
                if job.interrupted:
                    recovered_interruptions += 1
                if (job.stage == "assess" and
                        rng.random() < float(config["workload"].get("remediation_rate", 0))):
                    ratio = float(config["workload"].get("remediation_duration_ratio", 0.65))
                    remediation = Job(
                        id=_stable_id(job.scan, job.document, "remediate"), tenant=job.tenant,
                        scan=job.scan, document=job.document, file_type=job.file_type,
                        stage="remediate", created_at=now, eligible_at=now,
                        duration=job.duration * ratio, max_attempts=job.max_attempts,
                    )
                    enqueue(remediation)
        dispatch()

    all_terminal = completed + dead
    elapsed = max((job.completed_at or 0 for job in all_terminal), default=0.0)
    execution = [job.execution_time for job in all_terminal]
    waits = [job.queue_wait for job in all_terminal]
    end_to_end = [(job.completed_at or 0) - job.created_at for job in all_terminal]
    completed_by_tenant = Counter(job.tenant for job in completed)
    tenant_counts = [completed_by_tenant[tenant] for tenant in known_tenants]
    nonzero = [value for value in tenant_counts if value]
    fairness = {
        "jain_index": round(_jain(tenant_counts), 6),
        "max_min_completed_ratio": round(max(nonzero) / min(nonzero), 6) if nonzero else 1.0,
        "completed_jobs": {tenant: completed_by_tenant[tenant] for tenant in known_tenants},
    }
    metrics: dict[str, Any] = {
        "documents_submitted": document_count,
        "jobs_created": len(all_terminal),
        "jobs_completed": len(completed),
        "jobs_dead_lettered": len(dead),
        "retries": retries,
        "redis_errors": errors["redis"],
        "database_errors": errors["database"],
        "terminal_errors": errors["terminal"],
        "deploy_interruptions": interruptions,
        "deploy_interruptions_recovered": recovered_interruptions,
        "deploy_interruption_recovery_rate": (
            round(recovered_interruptions / interruptions, 6) if interruptions else 1.0
        ),
        "elapsed_seconds": round(elapsed, 3),
        "throughput_jobs_per_second": round(len(completed) / elapsed, 6) if elapsed else 0.0,
        "queue_wait_seconds": _distribution(waits),
        "execution_seconds": _distribution(execution),
        "end_to_end_seconds": _distribution(end_to_end),
        "fairness": fairness,
    }
    failures = _evaluate(metrics, config["thresholds"])
    return {
        "schema_version": SCHEMA_VERSION,
        "scenario": config["name"],
        "seed": int(config["seed"]),
        "mode": "isolated_simulation",
        "result": "GO" if not failures else "NO_GO",
        "failures": failures,
        "metrics": metrics,
        "thresholds": config["thresholds"],
    }


def _lookup(metrics: dict[str, Any], path: str) -> float:
    value: Any = metrics
    for part in path.split("."):
        value = value[part]
    if not isinstance(value, (int, float)):
        raise ValueError(f"threshold metric is not numeric: {path}")
    return float(value)


def _evaluate(metrics: dict[str, Any], thresholds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failures = []
    operators = {
        "max": lambda actual, expected: actual <= expected,
        "min": lambda actual, expected: actual >= expected,
        "eq": lambda actual, expected: actual == expected,
    }
    for threshold in thresholds:
        metric = threshold["metric"]
        operator = threshold["operator"]
        expected = float(threshold["value"])
        if operator not in operators:
            raise ValueError(f"unknown threshold operator: {operator}")
        actual = _lookup(metrics, metric)
        if not operators[operator](actual, expected):
            failures.append({
                "metric": metric, "operator": operator, "threshold": expected,
                "actual": actual, "reason": threshold.get("reason", "threshold breached"),
            })
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the isolated ACP load and chaos gate")
    parser.add_argument("--scenario", required=True, type=Path)
    parser.add_argument("--output", type=Path, help="write the JSON result to this path")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)
    try:
        config = json.loads(args.scenario.read_text(encoding="utf-8"))
        result = run_scenario(config)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"load gate configuration error: {exc}", file=sys.stderr)
        return 2
    rendered = json.dumps(result, indent=2 if args.pretty else None, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["result"] == "GO" else 1
