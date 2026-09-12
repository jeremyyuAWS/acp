import threading
import time

import lf
import pytest


@pytest.fixture(autouse=True)
def isolated_ingestion_health(monkeypatch):
    # Queue-flush doubles model their own failures and never make HTTP ingestion requests.
    # Reset only their independent process-local ingestion health, not production gating.
    for name in ("_ingestion_failures", "_ingestion_successes", "_ingestion_consecutive_failures",
                 "_ingestion_skipped"):
        monkeypatch.setattr(lf, name, 0)
    monkeypatch.setattr(lf, "_ingestion_retry_mono", 0.0)
    monkeypatch.setattr(lf, "_ingestion_last_error", None)
    monkeypatch.setattr(lf, "_ingestion_last_error_at", None)


def _wait_until(predicate, *, timeout=1):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    assert predicate()


def _reset_exporter(monkeypatch, client):
    """Give each test a fresh process-local exporter without reaching into the SDK."""
    monkeypatch.setattr(lf, "_ENABLED", True)
    monkeypatch.setattr(lf, "_client", client)
    monkeypatch.setattr(lf, "_flush_requested", False)
    monkeypatch.setattr(lf, "_flush_thread", None)
    monkeypatch.setattr(lf, "_flush_started_mono", None)
    monkeypatch.setattr(lf, "_flush_attempts", 0)
    monkeypatch.setattr(lf, "_flush_successes", 0)
    monkeypatch.setattr(lf, "_flush_failures", 0)
    monkeypatch.setattr(lf, "_flush_consecutive_failures", 0)
    monkeypatch.setattr(lf, "_flush_last_attempt_at", None)
    monkeypatch.setattr(lf, "_flush_last_success_at", None)
    monkeypatch.setattr(lf, "_flush_last_error_at", None)
    monkeypatch.setattr(lf, "_flush_last_duration_s", None)
    monkeypatch.setattr(lf, "_flush_retry_mono", 0.0)
    monkeypatch.setattr(lf, "_flush_next_retry_at", None)


def test_langfuse_outage_cannot_hold_a_worker_and_flushes_are_coalesced(monkeypatch):
    entered = threading.Event()
    release = threading.Event()

    class StalledLangfuse:
        calls = 0

        def flush(self):
            self.calls += 1
            entered.set()
            release.wait(timeout=2)

    client = StalledLangfuse()
    _reset_exporter(monkeypatch, client)

    started = time.monotonic()
    lf.flush()
    assert time.monotonic() - started < 0.1
    assert entered.wait(timeout=1)

    # Repeated job completions during the outage neither block nor create more exporter threads.
    first_thread = lf._flush_thread
    for _ in range(20):
        lf.flush()
    assert lf._flush_thread is first_thread
    assert client.calls == 1

    release.set()
    first_thread.join(timeout=1)
    assert not first_thread.is_alive()
    assert client.calls == 2  # one coalesced follow-up exports events added during the first pass


def test_exporter_recovers_after_an_exception_and_clears_degraded_health(monkeypatch):
    attempted = threading.Event()

    class FailOnceLangfuse:
        calls = 0

        def flush(self):
            self.calls += 1
            if self.calls == 1:
                attempted.set()
                raise RuntimeError("ingestion returned 500")

    client = FailOnceLangfuse()
    _reset_exporter(monkeypatch, client)
    monkeypatch.setenv("ACP_LANGFUSE_RETRY_BASE_SECONDS", "0.01")
    monkeypatch.setenv("ACP_LANGFUSE_RETRY_MAX_SECONDS", "0.01")

    lf.flush()
    assert attempted.wait(timeout=1)
    _wait_until(lambda: lf.exporter_health()["state"] == "degraded")

    failed = lf.exporter_health()
    assert failed["configured"] is True
    assert failed["exporting"] is False
    assert failed["pending"] is True
    assert failed["attempts"] == 1
    assert failed["successes"] == 0
    assert failed["failures"] == 1
    assert failed["consecutive_failures"] == 1
    assert failed["last_attempt_at"] is not None
    assert failed["last_success_at"] is None
    assert failed["last_error_at"] is not None
    assert failed["last_duration_s"] >= 0
    assert failed["next_retry_at"] is not None

    # Requests made while the breaker is open remain pending without hitting Langfuse.
    for _ in range(20):
        lf.flush()
    assert client.calls == 1

    time.sleep(0.03)
    lf.flush()
    _wait_until(lambda: lf.exporter_health()["state"] == "idle")

    recovered = lf.exporter_health()
    assert client.calls == 2
    assert recovered["pending"] is False
    assert recovered["attempts"] == 2
    assert recovered["successes"] == 1
    assert recovered["failures"] == 1
    assert recovered["consecutive_failures"] == 0
    assert recovered["last_success_at"] is not None
    assert recovered["next_retry_at"] is None


def test_health_reports_one_bounded_export_and_one_coalesced_follow_up(monkeypatch):
    entered = threading.Event()
    release = threading.Event()

    class BlockingLangfuse:
        calls = 0

        def flush(self):
            self.calls += 1
            if self.calls == 1:
                entered.set()
                assert release.wait(timeout=1)

    client = BlockingLangfuse()
    _reset_exporter(monkeypatch, client)

    lf.flush()
    assert entered.wait(timeout=1)
    exporter = lf._flush_thread

    active = lf.exporter_health()
    assert active["state"] == "exporting"
    assert active["exporting"] is True
    assert active["pending"] is False
    assert active["attempts"] == 1

    for _ in range(100):
        lf.flush()

    queued = lf.exporter_health()
    assert lf._flush_thread is exporter
    assert queued["state"] == "exporting"
    assert queued["exporting"] is True
    assert queued["pending"] is True
    assert client.calls == 1

    release.set()
    exporter.join(timeout=1)
    assert not exporter.is_alive()
    assert client.calls == 2

    idle = lf.exporter_health()
    assert idle["state"] == "idle"
    assert idle["exporting"] is False
    assert idle["pending"] is False
    assert idle["attempts"] == 2
    assert idle["successes"] == 2
    assert idle["failures"] == 0


def test_exporter_health_is_disabled_when_langfuse_is_not_configured(monkeypatch):
    monkeypatch.setattr(lf, "_ENABLED", False)
    # A stale request can survive a runtime disable or a previous concurrent test. It cannot be
    # serviced while disabled and must not make the public health payload contradict itself.
    monkeypatch.setattr(lf, "_flush_requested", True)

    health = lf.exporter_health()

    assert health["configured"] is False
    assert health["state"] == "disabled"
    assert health["exporting"] is False
    assert health["pending"] is False
