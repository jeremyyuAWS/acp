from __future__ import annotations

import sys
from pathlib import Path

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import realtime_shadow as shadow
import worker


class Transport:
    def __init__(self, fail=False):
        self.events = []
        self.sequences = {}
        self.fail = fail

    def next_sequence(self, tenant, correlation):
        key = (tenant, correlation)
        self.sequences[key] = self.sequences.get(key, 0) + 1
        return self.sequences[key]

    def write(self, envelope):
        if self.fail:
            raise TimeoutError("injected Redis timeout")
        self.events.append(envelope)
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
    assert set(event) == {"event_id", "event_version", "event_type", "occurred_at",
                          "tenant_id", "correlation_id", "source", "priority", "sequence",
                          "payload"}
    assert event["event_version"] == 1
    assert event["event_type"] == "discover.started"
    assert event["correlation_id"] == "s1"
    assert event["sequence"] == 1
    publisher.publish_one()
    publisher.publish_one()
    assert [e["event_type"] for e in transport.events] == [
        "discover.started", "queue.started", "worker.job.started"]


def test_submit_does_not_wait_for_transport_sequence():
    class SequenceMustStayOffCaller(Transport):
        def next_sequence(self, tenant, correlation):
            raise AssertionError("sequence I/O ran during submit")

    publisher = shadow.ShadowPublisher(SequenceMustStayOffCaller(), start_worker=False)
    assert publisher.submit(event_type="assess.started", tenant_id="t", correlation_id="c",
                            source="test", priority="high", payload={})


def test_lifecycle_is_lossless_while_low_priority_progress_coalesces():
    transport = Transport()
    publisher = shadow.ShadowPublisher(transport, max_progress=2, start_worker=False)
    base = dict(tenant_id="t", correlation_id="c", source="test")
    publisher.submit(event_type="assess.progress", priority="low", payload={"n": 1}, **base)
    publisher.submit(event_type="assess.progress", priority="low", payload={"n": 2}, **base)
    publisher.submit(event_type="assess.completed", priority="high", payload={}, **base)
    publisher.submit(event_type="remediate.started", priority="high", payload={}, **base)
    assert len(publisher._progress) == 1
    assert len(publisher._lifecycle) == 2
    publisher.publish_one()
    publisher.publish_one()
    publisher.publish_one()
    assert [e["event_type"] for e in transport.events] == [
        "assess.completed", "remediate.started", "assess.progress"]
    assert transport.events[-1]["payload"] == {"n": 2}


def test_publish_failure_is_swallowed_and_counted(monkeypatch):
    monkeypatch.setattr(shadow, "METRICS", shadow.Metrics())
    publisher = shadow.ShadowPublisher(Transport(fail=True), start_worker=False)
    assert publisher.submit(event_type="worker.failed", tenant_id="t", correlation_id="c",
                            source="test", priority="high", payload={})
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
            self.xread_args = None
        def xadd(self, *args, **kwargs):
            self.xadd_args = (args, kwargs)
            return "2-0"
        def xread(self, streams, **kwargs):
            self.xread_args = (streams, kwargs)
            return [("stream", [("2-0", {"event": '{"event_id":"e2"}'})])]

    transport = object.__new__(shadow.RedisStreamTransport)
    transport.redis = FakeRedis()
    transport.retention = 77
    transport.write({"tenant_id": "tenant-a", "event_id": "e1"})
    args, kwargs = transport.redis.xadd_args
    assert args[0] == "realtime:v1:tenant:tenant-a:events"
    assert kwargs == {"maxlen": 77, "approximate": True}
    assert transport.replay("tenant-a", "1-0") == [{"event_id": "e2", "stream_id": "2-0"}]
    assert transport.redis.xread_args == (
        {"realtime:v1:tenant:tenant-a:events": "1-0"}, {"count": 100, "block": 0})
