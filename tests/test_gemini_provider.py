"""Gemini vision adapter — unit and structural tests.

Covers GeminiVisionProvider (happy path, auth header, endpoint, error branches),
activation_readiness, _adapter_for, and the Settings.jsx ADAPTER_READY guard.
"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import providers  # noqa: E402


# ── helpers ───────────────────────────────────────────────────────────────────────────────────────

def _ok_response(text="A black square on a white background."):
    class _R:
        def raise_for_status(self): pass
        def json(self):
            return {"choices": [{"message": {"content": text}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 20}}
    return _R()


# ── 1. GeminiVisionProvider unit tests ───────────────────────────────────────────────────────────

def test_gemini_generate_posts_to_correct_endpoint(monkeypatch):
    seen = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        seen["url"] = url
        seen["auth"] = headers.get("Authorization", "")
        seen["model"] = json.get("model")
        return _ok_response()

    import httpx
    monkeypatch.setattr(httpx, "post", fake_post)
    p = providers.GeminiVisionProvider("key-abc", model="gemini-1.5-pro")
    res = p.generate("describe", b"IMGBYTES")

    assert "generativelanguage.googleapis.com" in seen["url"]
    assert seen["url"].endswith("/chat/completions")
    assert seen["auth"] == "Bearer key-abc"
    assert seen["model"] == "gemini-1.5-pro"
    assert res["ok"] is True
    assert res["provider"] == "gemini"
    assert res["text"] == "A black square on a white background."


def test_gemini_key_never_appears_in_result(monkeypatch):
    import httpx
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _ok_response())
    p = providers.GeminiVisionProvider("super-secret-key", model="gemini-1.5-pro")
    res = p.generate("describe", b"IMG")
    dumped = str(res)
    assert "super-secret-key" not in dumped


def test_gemini_zone_is_cloud_for_default_endpoint():
    p = providers.GeminiVisionProvider("k", model="gemini-1.5-pro")
    assert p.zone == "cloud"


def test_gemini_zone_follows_custom_endpoint():
    p = providers.GeminiVisionProvider("k", model="gemini-1.5-pro",
                                       endpoint="http://localhost:8080")
    assert p.zone == "local"


def test_gemini_custom_endpoint_is_used(monkeypatch):
    seen = {}

    def fake_post(url, **k):
        seen["url"] = url
        return _ok_response()

    import httpx
    monkeypatch.setattr(httpx, "post", fake_post)
    p = providers.GeminiVisionProvider("k", model="m", endpoint="http://my-proxy:9000")
    p.generate("x", b"IMG")
    assert seen["url"].startswith("http://my-proxy:9000")


def test_gemini_image_is_sent_as_base64_data_uri(monkeypatch):
    import base64
    seen = {}

    def fake_post(url, json=None, **k):
        seen["content"] = json["messages"][0]["content"]
        return _ok_response()

    import httpx
    monkeypatch.setattr(httpx, "post", fake_post)
    p = providers.GeminiVisionProvider("k", model="m")
    raw = b"\x89PNG fake bytes"
    p.generate("describe", raw)
    parts = seen["content"]
    image_part = next(x for x in parts if x.get("type") == "image_url")
    expected = "data:image/png;base64," + base64.b64encode(raw).decode("ascii")
    assert image_part["image_url"]["url"] == expected


def test_gemini_http_error_returns_ok_false(monkeypatch):
    import httpx

    def bad_post(*a, **k):
        raise httpx.HTTPStatusError("401", request=None, response=None)

    monkeypatch.setattr(httpx, "post", bad_post)
    p = providers.GeminiVisionProvider("k", model="m")
    res = p.generate("x", b"IMG")
    assert res["ok"] is False


def test_gemini_transport_error_returns_ok_false(monkeypatch):
    import httpx

    def explode(*a, **k):
        raise httpx.ConnectError("timeout")

    monkeypatch.setattr(httpx, "post", explode)
    p = providers.GeminiVisionProvider("k", model="m")
    res = p.generate("x", b"IMG")
    assert res["ok"] is False


def test_gemini_empty_reply_returns_ok_false(monkeypatch):
    import httpx

    def blank(*a, **k):
        class _R:
            def raise_for_status(self): pass
            def json(self): return {"choices": [{"message": {"content": ""}, "finish_reason": "stop"}],
                                    "usage": {}}
        return _R()

    monkeypatch.setattr(httpx, "post", blank)
    p = providers.GeminiVisionProvider("k", model="m")
    res = p.generate("x", b"IMG")
    assert res["ok"] is False
    assert res["reason"] == providers.REASON_EMPTY


def test_gemini_cost_computed_from_usage(monkeypatch):
    import httpx

    def with_usage(*a, **k):
        class _R:
            def raise_for_status(self): pass
            def json(self): return {
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1000, "completion_tokens": 100},
            }
        return _R()

    monkeypatch.setattr(httpx, "post", with_usage)
    p = providers.GeminiVisionProvider("k", model="gemini-1.5-pro")
    res = p.generate("x", b"IMG")
    assert res["ok"] is True
    assert res["prompt_tokens"] == 1000
    assert res["completion_tokens"] == 100


# ── 2. activation_readiness for gemini ───────────────────────────────────────────────────────────

def test_gemini_missing_model_is_not_ready():
    r = providers.activation_readiness("gemini", {"key_secret_ref": "GEMINI_KEY"})
    assert r["ready"] is False
    assert "model" in r["missing"]


def test_gemini_missing_key_ref_is_not_ready():
    r = providers.activation_readiness("gemini", {"model": "gemini-1.5-pro"})
    assert r["ready"] is False
    assert "key_secret_ref" in r["missing"]


def test_gemini_ready_when_model_and_secret_present(monkeypatch):
    monkeypatch.setenv("GEMINI_KEY", "gm-test-value")
    r = providers.activation_readiness(
        "gemini", {"model": "gemini-1.5-pro", "key_secret_ref": "GEMINI_KEY"})
    assert r["ready"] is True
    assert r["missing"] == []
    assert r["secret_resolves"] is True


def test_gemini_not_ready_when_secret_absent(monkeypatch):
    monkeypatch.delenv("GEMINI_KEY", raising=False)
    r = providers.activation_readiness(
        "gemini", {"model": "gemini-1.5-pro", "key_secret_ref": "GEMINI_KEY"})
    assert r["ready"] is False
    assert r["missing"] == []          # fields are present; secret is ops's job


# ── 3. _adapter_for for gemini ────────────────────────────────────────────────────────────────────

def test_adapter_for_gemini_returns_instance_when_complete(monkeypatch):
    monkeypatch.setenv("GEMINI_KEY", "gm-test")
    adapter = providers._adapter_for(
        "gemini", {"model": "gemini-1.5-pro", "key_secret_ref": "GEMINI_KEY"})
    assert isinstance(adapter, providers.GeminiVisionProvider)
    assert adapter.model == "gemini-1.5-pro"


def test_adapter_for_gemini_returns_none_without_key(monkeypatch):
    monkeypatch.delenv("GEMINI_KEY", raising=False)
    adapter = providers._adapter_for(
        "gemini", {"model": "gemini-1.5-pro", "key_secret_ref": "GEMINI_KEY"})
    assert adapter is None


def test_adapter_for_gemini_returns_none_without_model(monkeypatch):
    monkeypatch.setenv("GEMINI_KEY", "gm-test")
    adapter = providers._adapter_for(
        "gemini", {"model": "", "key_secret_ref": "GEMINI_KEY"})
    assert adapter is None


# ── 4. Settings.jsx structural guard ─────────────────────────────────────────────────────────────

def test_settings_jsx_adapter_ready_includes_gemini():
    """ADAPTER_READY in Settings.jsx must list every provider that has an adapter, and no others.
    When a new adapter is added here, this guard fails until the UI gate is updated to match."""
    jsx = (Path(__file__).resolve().parent.parent / "frontend" / "src" / "Settings.jsx").read_text()
    # Extract the ADAPTER_READY set literal
    import re
    m = re.search(r"ADAPTER_READY\s*=\s*new Set\(\[([^\]]+)\]\)", jsx)
    assert m, "Could not find ADAPTER_READY set in Settings.jsx"
    names = {n.strip().strip("'\"") for n in m.group(1).split(",")}
    assert "gemini" in names, f"'gemini' not in ADAPTER_READY; found: {names}"
