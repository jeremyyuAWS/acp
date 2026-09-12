"""GPU vision overload is bounded, observable, and degrades to human review."""
from __future__ import annotations

import threading
import time

import ai
import providers


class _BlockingProvider:
    # Name it Ollama so the gateway does not exercise the separate cloud-to-local fallback;
    # these tests isolate the admission layer around exactly one provider request.
    name = "ollama"
    zone = "cloud"
    model = "vision-test"
    base_url = "https://gpu.invalid"

    def __init__(self):
        self.entered = 0
        self.peak = 0
        self.lock = threading.Lock()
        self.release = threading.Event()

    def generate(self, prompt, image_bytes, **kwargs):
        with self.lock:
            self.entered += 1
            self.peak = max(self.peak, self.entered)
        self.release.wait(timeout=2)
        with self.lock:
            self.entered -= 1
        return {"ok": True, "text": "A useful image description", "model": self.model,
                "provider": self.name, "zone": self.zone, "reason": providers.REASON_OK}


def _runtime(monkeypatch, limit=2, wait=0.02):
    monkeypatch.setattr(ai, "VISION_MAX_CONCURRENCY", limit)
    monkeypatch.setattr(ai, "VISION_QUEUE_TIMEOUT", wait)
    monkeypatch.setattr(ai, "_VISION_GATE", threading.BoundedSemaphore(limit))
    monkeypatch.setattr(ai, "_VISION_RUNTIME", {
        "active": 0, "peak_active": 0, "admitted": 0, "backpressured": 0,
        "completed": 0, "failed": 0, "timeouts": 0, "circuit_skips": 0,
    })


def test_six_simultaneous_requests_run_only_two_provider_calls(monkeypatch):
    provider = _BlockingProvider()
    _runtime(monkeypatch)
    monkeypatch.setattr(providers, "active_vision_provider", lambda: provider)
    monkeypatch.setattr(ai, "_trace_ai", lambda *args, **kwargs: None)

    start = threading.Barrier(7)
    results = []

    def call():
        start.wait()
        results.append(ai._vision_generate("describe", b"image"))

    threads = [threading.Thread(target=call) for _ in range(6)]
    for thread in threads:
        thread.start()
    start.wait()
    deadline = time.monotonic() + 1
    while ai.vision_runtime_health()["backpressured"] < 4 and time.monotonic() < deadline:
        time.sleep(0.005)
    provider.release.set()
    for thread in threads:
        thread.join(timeout=1)

    health = ai.vision_runtime_health()
    assert provider.peak == 2
    assert health == {
        "max_concurrency": 2, "queue_timeout_seconds": 0.02,
        "active": 0, "peak_active": 2, "admitted": 2, "backpressured": 4,
        "completed": 2, "failed": 0, "timeouts": 0, "circuit_skips": 0,
    }
    assert sum(result is None for result in results) == 4
    assert sum(result == "A useful image description" for result in results) == 2


def test_capacity_recovers_when_an_inflight_call_finishes(monkeypatch):
    provider = _BlockingProvider()
    _runtime(monkeypatch, limit=1, wait=0.01)

    first = threading.Thread(target=lambda: ai._bounded_vision_generate(
        provider, "describe", b"image", timeout=1))
    first.start()
    while ai.vision_runtime_health()["active"] != 1:
        time.sleep(0.005)

    refused = ai._bounded_vision_generate(provider, "describe", b"image", timeout=1)
    assert refused["reason"] == "capacity_busy"
    provider.release.set()
    first.join(timeout=1)

    recovered = ai._bounded_vision_generate(provider, "describe", b"image", timeout=1)
    assert recovered["ok"] is True
    assert ai.vision_runtime_health()["active"] == 0


def test_timeout_has_a_distinct_observable_reason(monkeypatch):
    _runtime(monkeypatch, limit=1)

    class TimeoutProvider(_BlockingProvider):
        def generate(self, prompt, image_bytes, **kwargs):
            return {"ok": False, "reason": providers.REASON_TIMEOUT,
                    "provider": self.name, "zone": self.zone, "model": self.model}

    result = ai._bounded_vision_generate(TimeoutProvider(), "describe", b"image", timeout=1)
    assert result["reason"] == providers.REASON_TIMEOUT
    assert ai.vision_runtime_health()["timeouts"] == 1
    assert ai.vision_runtime_health()["failed"] == 1


def test_only_one_request_probes_a_half_open_circuit(monkeypatch):
    provider = _BlockingProvider()
    _runtime(monkeypatch, limit=2, wait=0.02)
    monkeypatch.setattr(providers, "active_vision_provider", lambda: provider)
    monkeypatch.setattr(ai, "_trace_ai", lambda *args, **kwargs: None)
    monkeypatch.setattr(ai, "VISION_CIRCUIT_COOLDOWN", 1.0)
    key = (provider.name, provider.base_url, provider.model)
    monkeypatch.setattr(ai, "_VISION_CIRCUITS", {
        key: {"failures": 1, "opened_at": time.monotonic() - 2,
              "reason": providers.REASON_TIMEOUT, "reported": True},
    })

    results = []
    first = threading.Thread(target=lambda: results.append(
        ai._vision_generate("describe", b"image", scan_id="scan")))
    first.start()
    while provider.entered != 1:
        time.sleep(0.005)
    second = ai._vision_generate("describe", b"image", scan_id="scan")
    provider.release.set()
    first.join(timeout=1)

    assert second is None
    assert results == ["A useful image description"]
    assert ai.vision_runtime_health()["admitted"] == 1
    assert ai.vision_runtime_health()["circuit_skips"] == 1
    assert key not in ai._VISION_CIRCUITS


def test_local_fallback_does_not_hide_gpu_timeout_from_the_circuit(monkeypatch):
    _runtime(monkeypatch, limit=2)
    monkeypatch.setattr(ai, "_trace_ai", lambda *args, **kwargs: None)
    monkeypatch.setattr(ai, "VISION_CIRCUIT_FAILURES", 1)

    class TimedOutGpu:
        name = "runpod_serverless"
        zone = "cloud"
        model = "gpu-model"
        endpoint = "https://gpu.invalid"

        def generate(self, *args, **kwargs):
            return {"ok": False, "reason": providers.REASON_TIMEOUT,
                    "provider": self.name, "zone": self.zone, "model": self.model}

    class HealthyLocal:
        name = "ollama"
        zone = "local"
        model = "local-model"

        def generate(self, *args, **kwargs):
            return {"ok": True, "text": "A useful local description",
                    "reason": providers.REASON_OK, "provider": self.name,
                    "zone": self.zone, "model": self.model}

    gpu = TimedOutGpu()
    monkeypatch.setattr(providers, "active_vision_provider", lambda: gpu)
    monkeypatch.setattr(providers, "local_vision_provider", lambda: HealthyLocal())

    assert ai._vision_generate("describe", b"image", scan_id="scan") == \
        "A useful local description"
    circuit = ai._VISION_CIRCUITS[(gpu.name, gpu.endpoint, gpu.model)]
    assert circuit["reason"] == providers.REASON_TIMEOUT

    # The next file degrades directly instead of retrying the overloaded GPU.
    assert ai._vision_generate("describe", b"image", scan_id="scan") is None
    assert ai.vision_runtime_health()["circuit_skips"] == 1


def test_provider_timeout_classification_is_not_collapsed_into_transport_error():
    class ReadTimeout(Exception):
        pass

    reason, detail = providers._classify(ReadTimeout("GPU overloaded"))
    assert reason == providers.REASON_TIMEOUT
    assert "GPU overloaded" in detail


def test_enabled_cloud_escalation_is_not_blocked_by_local_gpu_load(monkeypatch):
    _runtime(monkeypatch, limit=1, wait=0.01)
    monkeypatch.setattr(ai, '_CLOUD_VISION_GATE', threading.BoundedSemaphore(1))
    class CloudProvider:
        name = 'anthropic'
        def generate(self, *args, **kwargs):
            return {'ok': True, 'text': 'A grounded cloud draft'}
    assert ai._VISION_GATE.acquire(blocking=False)
    try:
        assert ai._bounded_vision_generate(CloudProvider(), 'describe', b'image')['ok']
        assert ai.vision_runtime_health()['active'] == 0
    finally:
        ai._VISION_GATE.release()


def test_cloud_requests_still_have_bounded_admission(monkeypatch):
    _runtime(monkeypatch, limit=1, wait=0.01)
    monkeypatch.setattr(ai, '_CLOUD_VISION_GATE', threading.BoundedSemaphore(1))
    class CloudProvider:
        name = 'openai'
        def generate(self, *args, **kwargs):
            raise AssertionError('busy API slot must not dispatch')
    assert ai._CLOUD_VISION_GATE.acquire(blocking=False)
    try:
        assert ai._bounded_vision_generate(CloudProvider(), 'describe', b'image')['reason'] == 'capacity_busy'
    finally:
        ai._CLOUD_VISION_GATE.release()
