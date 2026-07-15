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
