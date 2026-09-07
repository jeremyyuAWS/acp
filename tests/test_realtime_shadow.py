from __future__ import annotations

import sys
from pathlib import Path

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import realtime_shadow as shadow
import worker
from realtime_events import Priority, RealtimeEvent, owner_scope, stream_key
from realtime_gateway.store import _with_stream_id


class Transport:
    def __init__(self, fail=False):
        self.events = []
        self.sequences = {}
        self.fail = fail

    def write(self, event):
        if self.fail:
            raise TimeoutError("injected Redis timeout")
        self.events.append(event)
        return "1-0"


def test_default_off_is_a_noop(monkeypatch):
    monkeypatch.delenv("ACP_REALTIME_SHADOW_ENABLED", raising=False)
    monkeypatch.setattr(shadow, "_publisher", None)
    assert shadow._configured_publisher() is None


def test_versioned_contract_and_adapter_domain(monkeypatch):
    transport = Transport()
    publisher = shadow.ShadowPublisher(transport, start_worker=False)
    monkeypatch.setattr(shadow, "_configured_publisher", lambda: publisher)
    shadow.observe_job({"id": "j1", "type": "scan_discover", "scan_id": "s1",
                        "payload": {"tenant_id": "t1"}},
                       "started", worker_id="w1", status="running")
    publisher.publish_one()
    event = transport.events[0]
    assert isinstance(event, RealtimeEvent)
    assert event.kind == "discover.started"
    assert event.owner_scope == owner_scope("t1")
    assert event.correlation_id == "s1"
    assert event.source_seq == 1
    assert event.effective_priority == Priority.NORMAL
    assert event.payload["status"] == "running"


def test_submit_does_not_wait_for_transport_sequence():
    publisher = shadow.ShadowPublisher(Transport(), start_worker=False)
    assert publisher.submit(kind="assess.started", owner="t", correlation_id="c", payload={})


def test_lifecycle_is_lossless_while_low_priority_progress_coalesces():
    transport = Transport()
    publisher = shadow.ShadowPublisher(transport, max_progress=2, start_worker=False)
    base = dict(owner="t", correlation_id="c")
    publisher.submit(kind="assess.progressed", payload={"n": 1}, coalesce_key="scan-1", **base)
    publisher.submit(kind="assess.progressed", payload={"n": 2}, coalesce_key="scan-1", **base)
    publisher.submit(kind="assess.completed", payload={}, **base)
    publisher.submit(kind="remediate.started", payload={}, **base)
    assert len(publisher._progress) == 1
    assert len(publisher._lifecycle) == 2
    publisher.publish_one()
    publisher.publish_one()
    publisher.publish_one()
    assert [e.kind for e in transport.events] == [
        "assess.completed", "remediate.started", "assess.progressed"]
    assert transport.events[-1].payload == {"n": 2}


def test_publish_failure_is_swallowed_and_counted(monkeypatch):
    monkeypatch.setattr(shadow, "METRICS", shadow.Metrics())
    publisher = shadow.ShadowPublisher(Transport(fail=True), start_worker=False)
    assert publisher.submit(kind="worker.unhealthy", owner="t", correlation_id="c", payload={})
    publisher.publish_one()  # must not raise
    assert shadow.metrics_snapshot()["publish_drop_total"] == 1


def test_broken_observer_cannot_change_job_outcome(monkeypatch):
    class Store:
        job = {"id": "j1", "type": "shadow_failure_test", "payload": {}, "scan_id": "s1",
               "attempts": 1, "max_attempts": 2, "status": "running"}
        def claim_job(self, *_args, **_kwargs):
            job, self.job = self.job, None
            return job
        def is_job_cancelled(self, _job_id):
            return False
        def complete_job(self, _job_id, **_claim):
            self.completed = True
        def get_job(self, _job_id):
            return {"status": "done"}

    store = Store()
    monkeypatch.setitem(worker.HANDLERS, "shadow_failure_test", lambda _payload, _job: None)
    monkeypatch.setattr(shadow, "observe_job",
                        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("injected")))
    assert worker.JobWorker(store, worker_id="w1").run_once()
    assert store.completed is True


def test_redis_transport_uses_isolated_namespace_retention_and_last_event_id():
    class FakeRedis:
        def __init__(self):
            self.xadd_args = None
        def xadd(self, *args, **kwargs):
            self.xadd_args = (args, kwargs)
            return "2-0"

    transport = object.__new__(shadow.RedisStreamTransport)
    transport.redis = FakeRedis()
    transport.retention = 77
    publisher = shadow.ShadowPublisher(transport, start_worker=False)
    publisher.submit(kind="assess.started", owner="owner@example.com", correlation_id="scan-1",
                     payload={"status": "running"}, scan_id="scan-1", job_id="job-1")
    publisher.publish_one()
    args, kwargs = transport.redis.xadd_args
    assert args[0] == stream_key(owner_scope("owner@example.com"))
    assert kwargs == {"maxlen": 77, "approximate": True}
    fields = args[1]
    assert set(fields) == {"event", "event_id"}
    stream_id, restored = _with_stream_id("2-0", fields)
    assert stream_id == "2-0"
    assert restored.stream_id == "2-0"
    assert restored.kind == "assess.started"
    assert restored.event_id == fields["event_id"]
    assert restored.effective_priority == Priority.NORMAL


class FakePipeline:
    def __init__(self, results=None, failure=None):
        self.commands = []
        self.results = results
        self.failure = failure
        self.execute_calls = []

    def xadd(self, *args, **kwargs):
        self.commands.append((args, kwargs))
        return self

    def execute(self, **kwargs):
        self.execute_calls.append(kwargs)
        if self.failure:
            raise self.failure
        return self.results or [f"{n}-0" for n in range(1, len(self.commands) + 1)]


class FakeBatchRedis:
    def __init__(self, pipeline):
        self.created_with = []
        self._pipeline = pipeline

    def pipeline(self, **kwargs):
        self.created_with.append(kwargs)
        return self._pipeline


def test_batch_uses_one_nontransactional_round_trip_and_preserves_priority():
    pipe = FakePipeline()
    transport = object.__new__(shadow.RedisStreamTransport)
    transport.redis = FakeBatchRedis(pipe)
    transport.retention = 77
    publisher = shadow.ShadowPublisher(transport, start_worker=False)
    base = dict(owner="owner@example.com", correlation_id="scan-1")
    publisher.submit(kind="assess.progressed", payload={"n": 1},
                     coalesce_key="scan-1", **base)
    publisher.submit(kind="assess.progressed", payload={"n": 2},
                     coalesce_key="scan-1", **base)
    publisher.submit(kind="assess.completed", payload={}, **base)

    publisher.publish_batch()

    assert transport.redis.created_with == [{"transaction": False}]
    assert pipe.execute_calls == [{"raise_on_error": False}]
    restored = [_with_stream_id(f"{n}-0", args[1])[1]
                for n, (args, _kwargs) in enumerate(pipe.commands, 1)]
    assert [event.kind for event in restored] == ["assess.completed", "assess.progressed"]
    assert restored[-1].payload == {"n": 2}
    for args, kwargs in pipe.commands:
        assert args[0] == stream_key(owner_scope("owner@example.com"))
        assert kwargs == {"maxlen": 77, "approximate": True}
        assert set(args[1]) == {"event", "event_id"}


def test_batch_is_bounded_without_weakening_lifecycle_priority():
    pipe = FakePipeline()
    transport = object.__new__(shadow.RedisStreamTransport)
    transport.redis = FakeBatchRedis(pipe)
    transport.retention = 77
    publisher = shadow.ShadowPublisher(transport, max_batch=2, start_worker=False)
    base = dict(owner="t", correlation_id="c")
    publisher.submit(kind="assess.progressed", payload={"n": 1}, coalesce_key="job", **base)
    for n in range(3):
        publisher.submit(kind="assess.completed", payload={"n": n}, **base)

    publisher.publish_batch()

    restored = [_with_stream_id(f"{n}-0", args[1])[1]
                for n, (args, _kwargs) in enumerate(pipe.commands, 1)]
    assert [event.payload for event in restored] == [{"n": 0}, {"n": 1}]
    assert len(publisher._lifecycle) == 1
    assert len(publisher._progress) == 1


def test_partial_batch_failures_are_counted_per_event(monkeypatch):
    monkeypatch.setattr(shadow, "METRICS", shadow.Metrics())
    pipe = FakePipeline(results=["1-0", TimeoutError("one command failed"), "3-0"])
    transport = object.__new__(shadow.RedisStreamTransport)
    transport.redis = FakeBatchRedis(pipe)
    transport.retention = 77
    publisher = shadow.ShadowPublisher(transport, start_worker=False)
    for n in range(3):
        publisher.submit(kind="assess.completed", owner="t", correlation_id="c",
                         payload={"n": n})

    publisher.publish_batch()

    metrics = shadow.metrics_snapshot()
    assert metrics["publish_success_total"] == 2
    assert metrics["publish_drop_total"] == 1


def test_whole_batch_failure_is_swallowed_and_counts_every_drop(monkeypatch):
    monkeypatch.setattr(shadow, "METRICS", shadow.Metrics())
    pipe = FakePipeline(failure=TimeoutError("pipeline unavailable"))
    transport = object.__new__(shadow.RedisStreamTransport)
    transport.redis = FakeBatchRedis(pipe)
    transport.retention = 77
    publisher = shadow.ShadowPublisher(transport, start_worker=False)
    for n in range(3):
        publisher.submit(kind="assess.completed", owner="t", correlation_id="c",
                         payload={"n": n})

    publisher.publish_batch()

    metrics = shadow.metrics_snapshot()
    assert metrics["publish_success_total"] == 0
    assert metrics["publish_drop_total"] == 3


def test_batch_falls_back_for_legacy_single_write_transport(monkeypatch):
    monkeypatch.setattr(shadow, "METRICS", shadow.Metrics())
    transport = Transport()
    publisher = shadow.ShadowPublisher(transport, start_worker=False)
    for n in range(3):
        publisher.submit(kind="assess.completed", owner="t", correlation_id="c",
                         payload={"n": n})

    publisher.publish_batch()

    assert [event.payload for event in transport.events] == [{"n": 0}, {"n": 1}, {"n": 2}]
    assert shadow.metrics_snapshot()["publish_success_total"] == 3


def test_worker_outcomes_emit_only_truthful_registered_events(monkeypatch):
    transport = Transport()
    publisher = shadow.ShadowPublisher(transport, start_worker=False)
    monkeypatch.setattr(shadow, "_configured_publisher", lambda: publisher)
    job = {"id": "j1", "type": "scan_file", "scan_id": "s1",
           "payload": {"owner": "owner@example.com"}}
    shadow.observe_job(job, "retry", worker_id="w1", status="pending", detail={"attempt": 2})
    shadow.observe_job(job, "dead", worker_id="w1", status="failed")
    for _ in range(3):
        publisher.publish_one()
    assert [item.kind for item in transport.events] == [
        "queue.job_delayed", "assess.failed", "queue.job_dead_lettered"]
    assert all(item.kind in shadow.KIND_SPECS for item in transport.events)
