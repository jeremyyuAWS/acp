from pathlib import Path
import time

from performance.canonical_realtime_gate import THRESHOLDS, GateConfig, public_config, run


ROOT = Path(__file__).resolve().parents[2]


def test_canonical_realtime_gate_is_bounded_isolated_and_green():
    result = run(GateConfig(tenants=3, jobs_per_tenant=4, progress_per_job=50,
                            redis_delay_ms=0.25, timeout_seconds=5))
    assert result["decision"] == "GO", result
    assert result["metrics"]["tenant_leakage"] == 0
    assert result["metrics"]["missing_retry_events"] == 0
    assert result["metrics"]["missing_dead_letter_events"] == 0
    assert result["metrics"]["missing_latest_progress_events"] == 0
    assert result["metrics"]["missing_failed_events"] == 0
    assert (result["metrics"]["coalesced_write_ratio"]
            <= THRESHOLDS["coalesced_write_ratio_max"])
    assert result["config"]["redis_url"] is None


def test_gateway_latency_uses_each_publish_boundary_not_final_batch_age():
    # A deliberately slow batch takes longer than the latency SLO end to end.  The old
    # calculation observed every row only after that whole batch drained, making even the
    # first completed write look late.  Each individual write remains promptly observable.
    started = time.perf_counter()
    result = run(GateConfig(tenants=2, jobs_per_tenant=4, progress_per_job=20,
                            redis_delay_ms=20, timeout_seconds=5))
    batch_elapsed_ms = (time.perf_counter() - started) * 1000

    assert batch_elapsed_ms > THRESHOLDS["gateway_latency_p95_ms_max"]
    assert (result["metrics"]["gateway_latency_p95_ms"]
            < THRESHOLDS["gateway_latency_p95_ms_max"])
    assert result["decision"] == "GO", result


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
