"""The canonical realtime gate, asserted on what CI can decide.

The gate reports two classes of check (performance/canonical_realtime_gate.py, TIMING_CHECKS).
Structural checks hold by construction — no cross-tenant row, no lost lifecycle event, every
job's final progress written and in order, a warm-path batch from the persistent client — and
are asserted here. Timing checks are wall-clock percentiles and a scheduler-dependent coalescing
ratio; they are asserted with fixed inputs through `evaluate`, and on real hardware by the
staging gate. They are NOT asserted on a run in this process: the same in-memory configuration
measured a tenfold spread in gateway p95 and 12–14 progress writes across fifteen identical local
runs, and a CI runner is a worse place to measure than a laptop. A green that depends on the
runner being quiet is not a green.
"""
from pathlib import Path
from types import SimpleNamespace

import pytest

import performance.canonical_realtime_gate as gate
from performance.canonical_realtime_gate import (
    THRESHOLDS, TIMING_CHECKS, GateConfig, ObservedTransport, evaluate,
    out_of_order_progress_jobs, public_config, run,
)


ROOT = Path(__file__).resolve().parents[2]


class FakeClock:
    """Nanoseconds that move only when a test says so."""

    def __init__(self):
        self.now_ns = 0

    def __call__(self) -> int:
        return self.now_ns

    def advance_ms(self, ms: float) -> None:
        self.now_ns += int(ms * 1_000_000)


# ── the in-memory run: structural facts only ──────────────────────────────────

def test_canonical_realtime_gate_is_isolated_and_lossless():
    config = GateConfig(tenants=3, jobs_per_tenant=4, progress_per_job=50,
                        redis_delay_ms=0.25, timeout_seconds=5)
    result = run(config)
    m = result["metrics"]

    assert result["structural_decision"] == "GO", result
    assert set(result["structural_checks"]) | set(result["timing_checks"]) == set(result["checks"])
    assert set(result["timing_checks"]) == TIMING_CHECKS
    assert m["tenant_leakage"] == 0
    assert m["missing_retry_events"] == 0
    assert m["missing_dead_letter_events"] == 0
    assert m["missing_latest_progress_events"] == 0
    assert m["missing_warm_soak_events"] == 0
    assert m["missing_failed_events"] == 0
    assert m["progress_out_of_order"] == 0
    assert m["publisher_drops"] == 0
    assert m["cold_first_batch_size"] >= 1
    assert m["warm_batch_count"] >= 1
    assert result["checks"]["persistent_client_warm_soak"] is True
    # Coalescing bounds, stated structurally: never more writes than submissions, never fewer
    # than one final progress per job. HOW MANY in between is the scheduler's, and is reported
    # as coalesced_write_ratio for the staging gate to judge.
    expected_progress = config.tenants * config.jobs_per_tenant
    assert m["progress_submitted"] == expected_progress * config.progress_per_job
    assert expected_progress <= m["progress_written"] <= m["progress_submitted"]
    # The timing metrics are MEASURED — present and sane — but not judged here.
    for name in TIMING_CHECKS:
        assert name in m and m[name] >= 0.0, name
    assert m["gateway_latency_p95_ms"] > 0.0 and m["submit_latency_p95_ms"] > 0.0
    assert result["config"]["redis_url"] is None


def _progress(job_id: str, *values: int):
    return [SimpleNamespace(kind="assess.progressed", job_id=job_id, payload={"progress": v})
            for v in values]


def test_out_of_order_progress_is_counted_per_job():
    """Dropped intermediates are fine (0, 7, 49); a repeat or a step back is not, and a job is
    counted once however many times it misbehaves. Lifecycle events are not progress."""
    lifecycle = [SimpleNamespace(kind="assess.completed", job_id="a", payload={})]
    assert out_of_order_progress_jobs(_progress("a", 0, 7, 49) + lifecycle) == 0
    assert out_of_order_progress_jobs(_progress("a", 0, 7, 7)) == 1
    assert out_of_order_progress_jobs(_progress("a", 5, 3, 9, 2) + _progress("b", 1, 2)) == 1
    assert out_of_order_progress_jobs(_progress("a", 2, 1) + _progress("b", 2, 1)) == 2
    assert out_of_order_progress_jobs([]) == 0


def test_the_run_reports_the_order_invariant_it_computed(monkeypatch):
    """The metric on a real run is the pure function's answer over the replayed events — not a
    constant that happens to be zero."""
    monkeypatch.setattr(gate, "out_of_order_progress_jobs", lambda events: 7)
    result = run(GateConfig(tenants=2, jobs_per_tenant=1, progress_per_job=5,
                            redis_delay_ms=0, timeout_seconds=5))
    assert result["metrics"]["progress_out_of_order"] == 7
    assert result["structural_checks"]["progress_out_of_order"] is False
    assert result["structural_decision"] == "NO-GO"


def test_explicit_second_wave_guarantees_persistent_client_warm_sample():
    result = run(GateConfig(tenants=2, jobs_per_tenant=1, progress_per_job=10,
                            redis_delay_ms=0, timeout_seconds=5))

    assert result["metrics"]["missing_warm_soak_events"] == 0
    assert result["metrics"]["warm_batch_count"] >= 1
    assert result["checks"]["persistent_client_warm_soak"] is True


# ── the verdict: decided from fixed metrics, no clock in the loop ─────────────

def _green_metrics() -> dict:
    """A metrics dict that passes every check — each threshold met with room to spare."""
    m = {name.removesuffix("_max"): 0 for name in THRESHOLDS}
    m.update(gateway_latency_p95_ms=12.0, warm_gateway_latency_p95_ms=9.0,
             submit_latency_p95_ms=0.05, coalesced_write_ratio=0.02,
             redis_bytes_per_event=640.0, missing_failed_events=0, warm_batch_count=3)
    return m


def test_evaluate_partitions_every_check_into_exactly_one_class():
    verdict = evaluate(_green_metrics())
    assert verdict["decision"] == "GO" and verdict["structural_decision"] == "GO"
    assert set(verdict["timing_checks"]) == TIMING_CHECKS
    assert not (set(verdict["structural_checks"]) & TIMING_CHECKS)
    assert set(verdict["structural_checks"]) | TIMING_CHECKS == set(verdict["checks"])
    assert all(verdict["checks"].values())


@pytest.mark.parametrize("name,value", [
    ("gateway_latency_p95_ms", THRESHOLDS["gateway_latency_p95_ms_max"] + 0.01),
    ("warm_gateway_latency_p95_ms", THRESHOLDS["warm_gateway_latency_p95_ms_max"] + 0.01),
    ("submit_latency_p95_ms", THRESHOLDS["submit_latency_p95_ms_max"] + 0.01),
    ("coalesced_write_ratio", THRESHOLDS["coalesced_write_ratio_max"] + 0.01),
])
def test_a_timing_breach_is_a_staging_no_go_but_not_a_structural_one(name, value):
    """The staging gate still refuses a slow gateway — that verdict is unchanged. What changed
    is that CI no longer pretends to have measured it."""
    verdict = evaluate({**_green_metrics(), name: value})
    assert verdict["decision"] == "NO-GO"
    assert verdict["timing_checks"][name] is False
    assert verdict["structural_decision"] == "GO"


@pytest.mark.parametrize("name,value", [
    ("tenant_leakage", 1),
    ("missing_retry_events", 1),
    ("missing_dead_letter_events", 1),
    ("missing_latest_progress_events", 1),
    ("missing_warm_soak_events", 1),
    ("missing_failed_events", 1),
    ("progress_out_of_order", 1),
    ("publisher_drops", 1),
    ("redis_bytes_per_event", THRESHOLDS["redis_bytes_per_event_max"] + 1),
])
def test_a_structural_breach_is_a_no_go_everywhere(name, value):
    verdict = evaluate({**_green_metrics(), name: value})
    assert verdict["structural_decision"] == "NO-GO"
    assert verdict["decision"] == "NO-GO"
    assert verdict["structural_checks"][name] is False


def test_no_warm_batch_is_a_structural_no_go():
    verdict = evaluate({**_green_metrics(), "warm_batch_count": 0})
    assert verdict["structural_checks"]["persistent_client_warm_soak"] is False
    assert verdict["structural_decision"] == "NO-GO"


def test_threshold_boundaries_are_inclusive():
    at_limit = {**_green_metrics(), **{
        name.removesuffix("_max"): threshold for name, threshold in THRESHOLDS.items()}}
    assert evaluate(at_limit)["decision"] == "GO"


# ── the observer: per-boundary latency, on a clock the test controls ──────────

def test_gateway_latency_uses_each_publish_boundary_not_final_batch_age():
    """Three sequential writes of 20 ms each. Observed per boundary, every event's latency is
    20 ms; observed as batch age, they would read 20, 40, 60. Asserted exactly, on a fake clock
    — the old version of this test slept for real and compared against the 250 ms SLO, which
    passes or fails on what the runner was doing at the time."""
    clock = FakeClock()

    class SequentialTransport:
        redis = SimpleNamespace()               # no `pipeline`: each write is its own boundary

        def write(self, _event):
            clock.advance_ms(20)
            return "1-0"

    observed = ObservedTransport(SequentialTransport(), clock=clock)
    events = [SimpleNamespace(event_id=f"event-{index}") for index in range(3)]
    observed.write_many(events)

    assert [observed.latency_ms(event.event_id) for event in events] == [20.0, 20.0, 20.0]
    assert [batch["size"] for batch in observed.batch_observations()] == [1, 1, 1]


def test_gateway_latency_observer_supports_batched_redis_writes():
    clock = FakeClock()

    class BatchTransport:
        redis = SimpleNamespace(pipeline=lambda: None)

        def write(self, _event):
            raise AssertionError("publisher should retain the batched path")

        def write_many(self, events):
            clock.advance_ms(5)
            return [f"{index}-0" for index, _event in enumerate(events, 1)]

    events = [SimpleNamespace(event_id=f"event-{index}") for index in range(3)]
    observed = ObservedTransport(BatchTransport(), clock=clock)

    assert observed.write_many(events) == ["1-0", "2-0", "3-0"]
    # A real pipeline makes the whole batch observable when execute returns, so every event in
    # it shares one measured duration — exactly 5 ms here, not "at least 5 and within a µs".
    assert [observed.latency_ms(event.event_id) for event in events] == [5.0, 5.0, 5.0]
    assert observed.batch_observations() == [{
        "latency_ms": 5.0,
        "size": 3,
        "event_ids": ["event-0", "event-1", "event-2"],
    }]


def test_observer_measures_the_warmup_on_the_same_clock():
    clock = FakeClock()

    class WarmTransport:
        redis = SimpleNamespace()

        def warmup(self):
            clock.advance_ms(7.5)

    observed = ObservedTransport(WarmTransport(), clock=clock)
    observed.warmup()
    assert observed.warmup_latency_ms() == 7.5


# ── shipping and redaction, unchanged ─────────────────────────────────────────

def test_staging_gate_is_shipped_and_uses_environment_secret():
    dockerfile = (ROOT / "deploy/public/Dockerfile").read_text()
    workflow = (ROOT / ".github/workflows/validate-staging-realtime.yml").read_text()
    assert "COPY performance/ /app/performance/" in dockerfile
    assert "python /app/scripts/staging_realtime_gate.py" in workflow
    assert "--redis-url" not in workflow
    assert "workflow_run:" in workflow and "deploy-staging" in workflow
    assert "acp-assess-staging" in workflow


def test_redis_url_is_redacted_from_reports():
    secret = "redis://user:do-not-print@example.invalid:6379/0"
    rendered = public_config(GateConfig(redis_url=secret))
    assert rendered["redis_url"] == "configured"
    assert secret not in str(rendered)
