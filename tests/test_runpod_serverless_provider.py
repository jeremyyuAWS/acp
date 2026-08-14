"""RunPod Serverless GPU vision provider + selection + CPU fallback (ADR 0022)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
import providers  # noqa: E402


class _Resp:
    def __init__(self, data):
        self._d = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._d


def test_generate_ok_sends_openai_body_and_measures_cost(monkeypatch):
    seen = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        seen["url"] = url
        seen["auth"] = headers["Authorization"]
        seen["has_image"] = any(c.get("type") == "image_url" for c in json["messages"][0]["content"])
        return _Resp({"choices": [{"message": {"content": "A bar chart of revenue by region."}}],
                      "executionTime": 2000})

    import httpx
    monkeypatch.setattr(httpx, "post", fake_post)
    p = providers.RunPodServerlessVisionProvider("EP123", "KEY", model="qwen2.5-vl", cost_per_sec=0.0004)
    r = p.generate("describe this", b"\x89PNGfake", timeout=30)
    assert "/v2/EP123/openai/v1/chat/completions" in seen["url"]
    assert seen["auth"] == "Bearer KEY" and seen["has_image"]
    assert r["ok"] and r["text"] == "A bar chart of revenue by region."
    assert r["provider"] == "runpod_serverless" and r["zone"] == "cloud"
    assert r["cost_usd"] == round(2.0 * 0.0004, 6)          # 2 GPU-seconds × rate, measured


def test_generate_never_raises(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("endpoint down")
    import httpx
    monkeypatch.setattr(httpx, "post", boom)
    r = providers.RunPodServerlessVisionProvider("EP", "K").generate("x", b"y")
    assert r["ok"] is False and r["text"] is None and r["zone"] == "cloud"


def test_serverless_provider_needs_both_endpoint_and_key(monkeypatch):
    monkeypatch.delenv("RUNPOD_ENDPOINT_ID", raising=False)
    monkeypatch.delenv("RUNPOD_API_KEY", raising=False)
    assert providers.serverless_vision_provider() is None
    monkeypatch.setenv("RUNPOD_ENDPOINT_ID", "EP")
    assert providers.serverless_vision_provider() is None    # key still missing
    monkeypatch.setenv("RUNPOD_API_KEY", "K")
    p = providers.serverless_vision_provider()
    assert p is not None and p.name == "runpod_serverless"


def test_active_selects_serverless_when_configured_else_local(monkeypatch):
    monkeypatch.setenv("ACP_VISION_PROVIDER", "runpod_serverless")
    monkeypatch.setenv("RUNPOD_ENDPOINT_ID", "EP")
    monkeypatch.setenv("RUNPOD_API_KEY", "K")
    assert providers.active_vision_provider().name == "runpod_serverless"
    # a stale serverless SELECTION with no endpoint configured must never break the local path
    monkeypatch.delenv("RUNPOD_ENDPOINT_ID", raising=False)
    assert providers.active_vision_provider().name == "ollama"


def test_vision_generate_falls_back_to_cpu_on_gpu_miss(monkeypatch):
    import ai

    class _Miss:
        name = "runpod_serverless"
        def generate(self, *a, **k):
            return {"ok": False, "text": None, "model": "qwen2.5-vl",
                    "provider": "runpod_serverless", "zone": "cloud", "latency_ms": 1, "cost_usd": 0.0}

    class _Floor:
        name = "ollama"
        def generate(self, *a, **k):
            return {"ok": True, "text": "A bar chart of revenue by region.", "model": "moondream",
                    "provider": "ollama", "zone": "local", "latency_ms": 1, "cost_usd": 0.0}

    monkeypatch.setattr(providers, "active_vision_provider", lambda: _Miss())
    monkeypatch.setattr(providers, "local_vision_provider", lambda: _Floor())
    out = ai._vision_generate("describe", b"imgbytes")
    assert out == "A bar chart of revenue by region."       # the CPU floor served it, not the GPU


def test_gpu_miss_is_recorded_not_silent(monkeypatch):
    """A RunPod miss must be VISIBLE — its own ai_calls row (zone=cloud, ok=False, with the reason) —
    not silently overwritten by the local fallback. Otherwise the GPU failure exists only in the
    worker stdout log, which is exactly why it was undiagnosable without az."""
    import ai
    calls = []
    monkeypatch.setattr(ai, "_trace_ai", lambda *a, **k: calls.append(k))

    class _Miss:
        name = "runpod_serverless"
        def generate(self, *a, **k):
            return {"ok": False, "text": None, "model": "qwen2.5-vl", "provider": "runpod_serverless",
                    "zone": "cloud", "latency_ms": 1, "cost_usd": 0.0, "reason": "transport_error"}

    class _Floor:
        name = "ollama"
        def generate(self, *a, **k):
            return {"ok": True, "text": "A bar chart of revenue by region.", "model": "moondream",
                    "provider": "ollama", "zone": "local", "latency_ms": 1, "cost_usd": 0.0}

    monkeypatch.setattr(providers, "active_vision_provider", lambda: _Miss())
    monkeypatch.setattr(providers, "local_vision_provider", lambda: _Floor())
    ai._vision_generate("describe", b"imgbytes")
    cloud = [k for k in calls if k.get("zone") == "cloud"]
    assert cloud, "the failed RunPod attempt was not recorded — the GPU miss is invisible"
    assert cloud[0]["ok"] is False and cloud[0]["provider"] == "runpod_serverless"
    assert cloud[0]["reason"] == "transport_error"


def test_runpod_gets_the_longer_cold_start_timeout(monkeypatch):
    """The serverless GPU call must use RUNPOD_VISION_TIMEOUT, not the shorter Ollama budget: a
    scale-to-zero VL-7B cold boot exceeds 120s and would otherwise time out into a silent fallback."""
    import ai
    seen = {}

    class _Cloud:
        name = "runpod_serverless"
        def generate(self, prompt, image_bytes, *, model=None, timeout=None):
            seen["timeout"] = timeout
            return {"ok": True, "text": "A bar chart of revenue by region.", "model": "qwen2.5-vl",
                    "provider": "runpod_serverless", "zone": "cloud", "latency_ms": 1, "cost_usd": 0.0}

    monkeypatch.setattr(providers, "active_vision_provider", lambda: _Cloud())
    monkeypatch.setattr(ai, "RUNPOD_VISION_TIMEOUT", 240.0)
    monkeypatch.setattr(ai, "OLLAMA_VISION_TIMEOUT", 120.0)
    ai._vision_generate("describe", b"imgbytes")
    assert seen["timeout"] == 240.0                          # GPU cold-start budget, not the CPU one
