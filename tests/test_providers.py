"""Vision provider adapter seam (ADR 0019 Phase 1, §1).

Slice 1 must be a pure seam: the Ollama adapter does exactly what the old inline call did
(same URL, same payload shape, base64 image), returns a normalized result, and NEVER raises —
a transport error degrades to ok=False so the gateway can fall back. The selector defaults to
Ollama and reads its endpoint from ai's live globals (so a runtime endpoint switch is honoured).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import providers  # noqa: E402


def test_zone_local_vs_cloud():
    assert providers.zone_for_url("http://localhost:11434") == "local"
    assert providers.zone_for_url("http://10.0.0.5:11434") == "local"
    assert providers.zone_for_url("https://api.openai.com") == "cloud"
    assert providers.zone_for_url("https://acp-ollama.eastus2.azurecontainerapps.io") == "cloud"


def test_ollama_adapter_posts_images_and_normalizes(monkeypatch):
    seen = {}

    class _R:
        def raise_for_status(self): pass
        def json(self): return {"response": "  A bar chart of Q4 revenue  "}

    def fake_post(url, json=None, timeout=None):
        seen["url"] = url; seen["json"] = json; seen["timeout"] = timeout
        return _R()

    import httpx
    monkeypatch.setattr(httpx, "post", fake_post)
    p = providers.OllamaVisionProvider("http://localhost:11434/", "llava:13b")
    res = p.generate("describe", b"IMGBYTES", timeout=42.0)
    assert seen["url"] == "http://localhost:11434/api/generate"
    assert seen["json"]["model"] == "llava:13b"
    assert seen["json"]["images"] and isinstance(seen["json"]["images"][0], str)   # base64
    assert seen["timeout"] == 42.0
    assert res["text"] == "A bar chart of Q4 revenue"      # stripped, raw (ai.py owns cleaning)
    assert res["ok"] is True and res["provider"] == "ollama"
    assert res["zone"] == "local" and res["cost_usd"] == 0.0
    assert isinstance(res["latency_ms"], int)


def test_ollama_adapter_model_override(monkeypatch):
    captured = {}

    class _R:
        def raise_for_status(self): pass
        def json(self): return {"response": "x y z"}

    import httpx
    monkeypatch.setattr(httpx, "post", lambda url, json=None, timeout=None: captured.update(json=json) or _R())
    p = providers.OllamaVisionProvider("http://localhost:11434", "moondream")
    p.generate("d", b"B", model="llava:13b")
    assert captured["json"]["model"] == "llava:13b"        # per-call override wins


def test_ollama_adapter_never_raises_on_transport_error(monkeypatch):
    import httpx
    def boom(*a, **k): raise RuntimeError("connection refused")
    monkeypatch.setattr(httpx, "post", boom)
    res = providers.OllamaVisionProvider("http://localhost:11434", "m").generate("d", b"B")
    assert res["ok"] is False and res["text"] is None      # degraded, not raised
    assert res["provider"] == "ollama"


def test_selector_defaults_to_ollama_from_ai_globals(monkeypatch):
    import ai
    monkeypatch.setattr(ai, "OLLAMA_BASE_URL", "http://localhost:11434")
    monkeypatch.setattr(ai, "OLLAMA_VISION_MODEL", "moondream")
    monkeypatch.setattr(ai, "_maybe_refresh_endpoint", lambda: None)
    p = providers.active_vision_provider()
    assert isinstance(p, providers.OllamaVisionProvider)
    assert p.base_url == "http://localhost:11434" and p.model == "moondream"


def test_selector_unknown_provider_falls_back_to_ollama(monkeypatch):
    import ai
    import core
    monkeypatch.setattr(ai, "_maybe_refresh_endpoint", lambda: None)
    monkeypatch.setattr(ai, "OLLAMA_BASE_URL", "http://localhost:11434")
    monkeypatch.setattr(ai, "OLLAMA_VISION_MODEL", "moondream")
    import types
    monkeypatch.setattr(core, "store",
                        types.SimpleNamespace(get_setting=lambda k: "azure_openai" if k == "ai_vision_provider" else None))
    p = providers.active_vision_provider()
    assert isinstance(p, providers.OllamaVisionProvider)   # un-provisioned cloud never breaks local


def test_conforms_to_protocol():
    p = providers.OllamaVisionProvider("http://localhost:11434", "m")
    assert isinstance(p, providers.VisionProvider)
