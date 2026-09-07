from performance.canonical_realtime_gate import GateConfig, run


def test_canonical_realtime_gate_is_bounded_isolated_and_green():
    result = run(GateConfig(tenants=3, jobs_per_tenant=4, progress_per_job=50,
                            redis_delay_ms=0.25, timeout_seconds=5))
    assert result["decision"] == "GO", result
    assert result["metrics"]["tenant_leakage"] == 0
    assert result["metrics"]["missing_retry_events"] == 0
    assert result["metrics"]["missing_dead_letter_events"] == 0
    assert result["metrics"]["missing_failed_events"] == 0
    assert result["metrics"]["progress_written"] <= 12
