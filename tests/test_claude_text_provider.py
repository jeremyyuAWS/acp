"""Tests for the Claude-as-primary-text-provider path in ai.suggest_fix.

Verifies:
  1. _claude_text_generate returns None when ANTHROPIC_API_KEY is absent (no call made).
  2. _claude_text_generate parses Claude's Messages-API response shape correctly.
  3. _claude_text_generate returns None on HTTP failure (graceful degradation).
  4. suggest_fix uses Claude when configured, and the result carries provider/zone.
  5. suggest_fix falls back to Ollama when Claude returns None (ANTHROPIC_API_KEY set but API fails).
  6. provenance() reports anthropic when the key is set, ollama otherwise.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
import ai


# ── _claude_text_generate unit tests ─────────────────────────────────────────

def test_claude_text_generate_returns_none_without_key(monkeypatch):
    monkeypatch.setattr(ai, "_ANTHROPIC_KEY", "")
    result = ai._claude_text_generate("any prompt")
    assert result is None


def test_claude_text_generate_parses_messages_api_response(monkeypatch):
    monkeypatch.setattr(ai, "_ANTHROPIC_KEY", "test-key")

    class _Resp:
        def raise_for_status(self): pass
        def json(self):
            return {
                "content": [{"type": "text", "text": "Quarterly revenue bar chart."}],
                "usage": {"input_tokens": 120, "output_tokens": 8},
            }

    import httpx
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Resp())
    result = ai._claude_text_generate("describe this")
    assert result is not None
    assert result["text"] == "Quarterly revenue bar chart."
    assert result["prompt_tokens"] == 120
    assert result["completion_tokens"] == 8
    assert result["cost_usd"] > 0


def test_claude_text_generate_returns_none_on_http_failure(monkeypatch):
    monkeypatch.setattr(ai, "_ANTHROPIC_KEY", "test-key")
    import httpx
    monkeypatch.setattr(httpx, "post", lambda *a, **k: (_ for _ in ()).throw(
        httpx.ConnectError("unreachable")
    ))
    assert ai._claude_text_generate("prompt") is None


def test_claude_text_generate_returns_none_on_empty_content(monkeypatch):
    monkeypatch.setattr(ai, "_ANTHROPIC_KEY", "test-key")

    class _Resp:
        def raise_for_status(self): pass
        def json(self): return {"content": [], "usage": {}}

    import httpx
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Resp())
    assert ai._claude_text_generate("prompt") is None


# ── suggest_fix with Claude ───────────────────────────────────────────────────

def test_suggest_fix_uses_claude_when_key_set(monkeypatch):
    monkeypatch.setattr(ai, "_ANTHROPIC_KEY", "test-key")

    class _Resp:
        def raise_for_status(self): pass
        def json(self):
            return {
                "content": [{"type": "text", "text": "Click here to view the quarterly report."}],
                "usage": {"input_tokens": 90, "output_tokens": 9},
            }

    import httpx
    calls = []
    def _post(url, **k):
        calls.append(url)
        return _Resp()
    monkeypatch.setattr(httpx, "post", _post)

    out = ai.suggest_fix("2.4.4", "Link Purpose", "A", "report.docx", detail="Click here")
    assert out is not None
    assert out["suggestion"] == "Click here to view the quarterly report."
    assert out["model"] == ai.CLAUDE_TEXT_MODEL
    assert out["provider"] == "anthropic"
    assert out["processing_zone"] == "cloud"
    assert out["cost_usd"] >= 0
    # Exactly one HTTP call to the Anthropic endpoint, no Ollama call.
    assert len(calls) == 1
    assert "anthropic.com" in calls[0]


def test_suggest_fix_falls_back_to_ollama_when_claude_returns_none(monkeypatch):
    monkeypatch.setattr(ai, "_ANTHROPIC_KEY", "test-key")

    call_urls = []

    class _OllamaResp:
        def raise_for_status(self): pass
        def json(self): return {"response": "Descriptive link text here."}

    def _post(url, **k):
        call_urls.append(url)
        if "anthropic" in url:
            # Return empty content so _claude_text_generate returns None.
            class _Empty:
                def raise_for_status(self): pass
                def json(self): return {"content": [], "usage": {}}
            return _Empty()
        return _OllamaResp()

    import httpx
    monkeypatch.setattr(httpx, "post", _post)

    out = ai.suggest_fix("2.4.4", "Link Purpose", "A", "doc.docx")
    assert out is not None
    assert out["suggestion"] == "Descriptive link text here."
    assert out.get("model") == ai.OLLAMA_MODEL
    assert "provider" not in out     # Ollama path does not add governance fields
    # Both Claude and Ollama were tried.
    assert any("anthropic" in u for u in call_urls)
    assert any("ollama" in u or "11434" in u for u in call_urls)


# ── provenance() ─────────────────────────────────────────────────────────────

def test_provenance_reports_anthropic_when_key_set(monkeypatch):
    monkeypatch.setattr(ai, "_ANTHROPIC_KEY", "test-key")
    p = ai.provenance()
    assert p["provider"] == "anthropic"
    assert p["zone"] == "cloud"
    assert p["model"] == ai.CLAUDE_TEXT_MODEL
    assert p["host"] == "api.anthropic.com"


def test_provenance_reports_ollama_when_no_key(monkeypatch):
    monkeypatch.setattr(ai, "_ANTHROPIC_KEY", "")
    p = ai.provenance()
    assert p["provider"] == "ollama"
    assert p["model"] == ai.OLLAMA_MODEL
