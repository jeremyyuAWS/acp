"""Ollama availability probe: survive a scale-from-zero cold start, but don't pay for it
when nothing is listening.

The demo's Ollama is a Container App with minReplicas=0. ACA holds a request open while the
replica activates, so a COLD Ollama looks like a timeout, not a refusal. The original 3s
probe could never outlast that, so vision_is_available() always returned False in production
and every image fell through to "needs human alt text" instead of getting an AI-drafted one.
"""
from __future__ import annotations
import sys
from pathlib import Path

import httpx
import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import ai  # noqa: E402


class _Resp:
    def __init__(self, models): self._models = models
    def raise_for_status(self): pass
    def json(self): return {"models": [{"name": n} for n in self._models]}


def _fake_get(script, models, seen):
    """Each call pops the next outcome: 'ok' | 'timeout' | 'connect'."""
    it = iter(script)

    def get(url, timeout=None):
        kind = next(it)
        seen.append((kind, timeout))
        if kind == "timeout":
            raise httpx.ReadTimeout("activating from zero")
        if kind == "connect":
            raise httpx.ConnectError("connection refused")
        return _Resp(models)
    return get


@pytest.fixture(autouse=True)
def _clear_cache():
    ai.reset_probe_cache()
    yield
    ai.reset_probe_cache()


def test_warm_ollama_with_vision_model(monkeypatch):
    seen = []
    monkeypatch.setattr(httpx, "get", _fake_get(["ok"], ["moondream"], seen))
    assert ai.vision_is_available() is True
    assert seen == [("ok", ai.OLLAMA_PROBE_TIMEOUT)]      # one fast probe, no long wait


def test_cold_start_is_tolerated(monkeypatch):
    """The regression: fast probe times out while ACA activates, retry with the long budget."""
    seen = []
    monkeypatch.setattr(httpx, "get", _fake_get(["timeout", "ok"], ["moondream"], seen))
    assert ai.vision_is_available() is True
    assert [t for _, t in seen] == [ai.OLLAMA_PROBE_TIMEOUT, ai.OLLAMA_COLD_START_TIMEOUT]


def test_no_listener_fails_fast(monkeypatch):
    """Local dev with no Ollama: a refusal is not a cold start — never wait out the budget."""
    seen = []
    monkeypatch.setattr(httpx, "get", _fake_get(["connect"], [], seen))
    assert ai.vision_is_available() is False
    assert len(seen) == 1                                  # no cold-start retry


def test_cold_start_that_never_wakes(monkeypatch):
    seen = []
    monkeypatch.setattr(httpx, "get", _fake_get(["timeout", "timeout"], [], seen))
    assert ai.vision_is_available() is False
    assert len(seen) == 2


def test_text_only_ollama_is_not_vision_capable(monkeypatch):
    """is_available() is True but vision_is_available() must be False — the distinction the
    alt-text remediator gates on."""
    monkeypatch.setattr(httpx, "get", _fake_get(["ok"], ["llama3.1:8b"], []))
    assert ai.vision_is_available() is False
    ai.reset_probe_cache()
    monkeypatch.setattr(httpx, "get", _fake_get(["ok"], ["llama3.1:8b"], []))
    assert ai.is_available() is True


def test_probe_is_memoised_across_files(monkeypatch):
    """vision_is_available() runs once per remediated file; a 50-doc scan against a cold or
    absent Ollama must not pay the probe 50 times."""
    seen = []
    monkeypatch.setattr(httpx, "get", _fake_get(["ok", "ok", "ok"], ["moondream"], seen))
    assert ai.vision_is_available() is True
    assert ai.vision_is_available() is True
    assert ai.is_available() is True
    assert len(seen) == 1                                  # cached; only the first call probed
