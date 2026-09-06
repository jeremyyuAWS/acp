import json

import pytest

from shadow_realtime.collector import CollectorConfig, OperationsCollector
from shadow_realtime.contract import EventEnvelope
from shadow_realtime.harness import HarnessConfig, MemoryRedis, run
from shadow_realtime.stream import ShadowStream, enabled, sse_frames, stream_key


def event(stream, *, event_type="job.completed", priority="high", sequence=1):
    return EventEnvelope.new(event_type=event_type, tenant_id="tenant-1", correlation_id="corr", source="test", priority=priority, sequence=sequence, payload={"ok": True})


def test_feature_is_default_off_and_never_uses_production_redis_name():
    assert enabled({}) is False
    assert stream_key("tenant-1") == "realtime:v1:tenant:tenant-1:events"
    with pytest.raises(RuntimeError, match="disabled"):
        CollectorConfig.from_env({"REDIS_URL": "redis://production"})


def test_contract_and_sse_id_round_trip():
    original = event(ShadowStream(MemoryRedis()))
    decoded = EventEnvelope.from_json(original.to_json())
    assert decoded == original
    frame = next(iter(sse_frames([("12-0", original)])))
    assert frame.startswith("id: 12-0\nevent: job.completed\ndata: ")


def test_replay_is_strictly_after_last_event_id_and_retention_is_bounded():
    backend = MemoryRedis()
    stream = ShadowStream(backend, max_events=3)
    ids = [stream.publish(event(stream, sequence=i)).stream_id for i in range(5)]
    assert [sid for sid, _ in stream.replay("tenant-1", None)] == ids[-3:]
    assert [sid for sid, _ in stream.replay("tenant-1", ids[-3])] == ids[-2:]


def test_only_low_priority_progress_is_coalesced():
    backend = MemoryRedis()
    stream = ShadowStream(backend)
    first = stream.publish(event(stream, event_type="job.progress", priority="low"), coalesce_key="job")
    second = stream.publish(event(stream, event_type="job.progress", priority="low", sequence=2), coalesce_key="job")
    lifecycle = stream.publish(event(stream, sequence=3), coalesce_key="job")
    assert first.stream_id and second.coalesced
    assert lifecycle.stream_id and not lifecycle.coalesced


def test_collector_normalizes_samples_without_real_credentials():
    config = CollectorConfig("redis://unused", "sub", "tenant-1", ("/resource/one",), interval_seconds=60)
    stream = ShadowStream(MemoryRedis())
    collector = OperationsCollector(config, stream, lambda resource, names: {"CpuUsage": {"average": 3}})
    ids = collector.collect_once()
    assert len(ids) == 1
    _, sample = stream.replay("tenant-1", None)[0]
    assert sample.event_type == "infrastructure.sample"
    assert sample.payload["resource_id"] == "/resource/one"


def test_harness_produces_machine_readable_go_no_go_result():
    result = run(HarnessConfig(events=300, retention=250, disconnect_after=100, lifecycle_every=50))
    json.dumps(result)
    assert result["schema_version"] == 1
    assert result["metrics"]["reconnect_replay_percent"] == 100.0
    assert result["metrics"]["lifecycle_event_loss"] == 0
    assert set(result["checks"]) == {"latency_p95", "latency_p99", "throughput", "reconnect_replay", "lifecycle_loss", "redis_memory", "retention", "slow_client", "cpu", "restart_recovery"}
