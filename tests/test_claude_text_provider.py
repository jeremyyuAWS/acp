"""Tests for the Claude-as-primary-text-provider path.

The implementation lives behind the providers seam (providers.claude_text_generate /
providers.text_provider_provenance); ai.suggest_fix calls through it without knowing
which vendor is in play. Tests patch providers._ANTHROPIC_KEY and httpx.post.

Verifies:
  1. claude_text_generate returns None when _ANTHROPIC_KEY is absent (no call made).
  2. claude_text_generate parses Claude's Messages-API response shape correctly.
  3. claude_text_generate returns None on HTTP failure (graceful degradation).
  4. suggest_fix uses the cloud provider when configured, result carries provider/zone.
  5. suggest_fix falls back to Ollama when claude_text_generate returns None.
  6. provenance() reports the cloud provider when the key is set, ollama otherwise.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
import ai
import providers


# ── providers.claude_text_generate unit tests ─────────────────────────────────

def test_claude_text_generate_returns_none_without_key(monkeypatch):
    monkeypatch.setattr(providers, "_ANTHROPIC_KEY", "")
    result = providers.claude_text_generate("any prompt")
    assert result is None


def test_claude_text_generate_parses_messages_api_response(monkeypatch):
    monkeypatch.setattr(providers, "_ANTHROPIC_KEY", "test-key")

    class _Resp:
        def raise_for_status(self): pass
        def json(self):
            return {
                "content": [{"type": "text", "text": "Quarterly revenue bar chart."}],
                "usage": {"input_tokens": 120, "output_tokens": 8},
            }

    import httpx
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Resp())
    result = providers.claude_text_generate("describe this")
    assert result is not None
    assert result["text"] == "Quarterly revenue bar chart."
    assert result["prompt_tokens"] == 120
    assert result["completion_tokens"] == 8
    assert result["cost_usd"] > 0
    assert result["provider"] == "anthropic"
    assert result["zone"] == "cloud"
    assert result["model"] == providers.CLAUDE_TEXT_MODEL


def test_claude_text_generate_uses_governed_model_override(monkeypatch):
    monkeypatch.setattr(providers, "_ANTHROPIC_KEY", "test-key")
    sent = {}
    class _Resp:
        def raise_for_status(self): pass
        def json(self):
            return {"content": [{"type": "text", "text": "Useful destination"}],
                    "usage": {"input_tokens": 1000, "output_tokens": 100}}
    import httpx
    def _post(*_args, **kwargs):
        sent.update(kwargs["json"])
        return _Resp()
    monkeypatch.setattr(httpx, "post", _post)
    result = providers.claude_text_generate("draft", model="claude-sonnet-5")
    assert sent["model"] == "claude-sonnet-5"
    assert result["model"] == "claude-sonnet-5"
    # Derived from the model's own row, not written out. This asserted 0.0045 — 1000 in + 100 out
    # at Sonnet 4.6's (3.00, 15.00), which claude-sonnet-5 was wrongly priced at. Correcting the
    # table made this fail for being right, and the literal hid it: the price never appears here,
    # only its product, so a grep for the old numbers does not find this line.
    #
    # The VALUE lives in tests/test_claude_list_prices.py. Here the table is an input, so a price
    # change moves this expectation and a broken multiplication still fails it.
    price = providers._price_for("claude-sonnet-5")
    assert price, "claude-sonnet-5 has no row in _PRICE_PER_1M"
    assert result["cost_usd"] == round(1000 / 1e6 * price[0] + 100 / 1e6 * price[1], 6)


def test_claude_text_generate_returns_none_on_http_failure(monkeypatch):
    monkeypatch.setattr(providers, "_ANTHROPIC_KEY", "test-key")
    import httpx
    monkeypatch.setattr(httpx, "post", lambda *a, **k: (_ for _ in ()).throw(
        httpx.ConnectError("unreachable")
    ))
    assert providers.claude_text_generate("prompt") is None


def test_claude_text_generate_returns_none_on_empty_content(monkeypatch):
    monkeypatch.setattr(providers, "_ANTHROPIC_KEY", "test-key")

    class _Resp:
        def raise_for_status(self): pass
        def json(self): return {"content": [], "usage": {}}

    import httpx
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Resp())
    assert providers.claude_text_generate("prompt") is None


# ── suggest_fix with cloud provider ──────────────────────────────────────────

def test_suggest_fix_uses_cloud_provider_when_key_set(monkeypatch):
    monkeypatch.setattr(providers, "_ANTHROPIC_KEY", "test-key")

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
    assert out["model"] == providers.CLAUDE_TEXT_MODEL
    assert out["provider"] == "anthropic"
    assert out["processing_zone"] == "cloud"
    assert out["cost_usd"] >= 0
    # Exactly one HTTP call to the cloud endpoint, no Ollama call.
    assert len(calls) == 1
    assert "anthropic.com" in calls[0]


def test_suggest_fix_falls_back_to_ollama_when_cloud_returns_none(monkeypatch):
    monkeypatch.setattr(providers, "_ANTHROPIC_KEY", "test-key")

    call_urls = []

    class _OllamaResp:
        def raise_for_status(self): pass
        def json(self): return {"response": "Descriptive link text here."}

    def _post(url, **k):
        call_urls.append(url)
        if "anthropic" in url:
            # Return empty content so claude_text_generate returns None.
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
    # Both cloud and Ollama were tried.
    assert any("anthropic" in u for u in call_urls)
    assert any("ollama" in u or "11434" in u for u in call_urls)


# ── provenance() ─────────────────────────────────────────────────────────────

def test_provenance_reports_cloud_provider_when_key_set(monkeypatch):
    monkeypatch.setattr(providers, "_ANTHROPIC_KEY", "test-key")
    p = ai.provenance()
    assert p["provider"] == "anthropic"
    assert p["zone"] == "cloud"
    assert p["model"] == providers.CLAUDE_TEXT_MODEL
    assert p["host"] == "api.anthropic.com"


def test_provenance_reports_ollama_when_no_key(monkeypatch):
    monkeypatch.setattr(providers, "_ANTHROPIC_KEY", "")
    p = ai.provenance()
    assert p["provider"] == "ollama"
    assert p["model"] == ai.OLLAMA_MODEL



def test_governed_anthropic_vault_key_serves_selected_text_without_env(monkeypatch, caplog):
    import core
    import httpx
    import secret_store
    monkeypatch.setattr(providers, '_ANTHROPIC_KEY', '')
    monkeypatch.setattr(providers, '_config_for', lambda name: {
        'enabled': True, 'key_secret_ref': 'keyvault:fixture-anthropic'} if name == 'anthropic' else {})
    monkeypatch.setattr(core.store, 'get_setting', lambda name: 'anthropic' if name == 'ai_text_provider' else None)
    sentinel = 'fixture-private-vault-value'
    monkeypatch.setattr(secret_store, 'read_ref', lambda ref: sentinel)
    calls = []
    class Resp:
        def raise_for_status(self): pass
        def json(self):
            return {'content': [{'type': 'text', 'text': 'A useful draft'}],
                    'usage': {'input_tokens': 10, 'output_tokens': 4}}
    def post(*args, **kwargs):
        calls.append(kwargs)
        return Resp()
    monkeypatch.setattr(httpx, 'post', post)
    assert providers.active_text_provider() == 'anthropic'
    assert providers._text_key_for('anthropic') == sentinel
    draft = providers.text_generate('draft')
    assert draft['text'] == 'A useful draft'
    assert calls[0]['headers']['x-api-key'] == sentinel
    assert sentinel not in repr(draft)
    assert sentinel not in caplog.text


def test_anthropic_vision_reference_alone_does_not_activate_text(monkeypatch):
    import core
    monkeypatch.setattr(providers, '_ANTHROPIC_KEY', '')
    monkeypatch.delenv('ACP_TEXT_PROVIDER', raising=False)
    monkeypatch.setattr(core.store, 'get_setting', lambda name: None)
    monkeypatch.setattr(providers, '_config_for', lambda name: {'enabled': True, 'key_secret_ref': 'fixture'})
    monkeypatch.setattr(providers, '_resolve_key', lambda cfg: 'fixture-key')
    assert providers.active_text_provider() is None


def test_disabled_anthropic_reference_is_not_resolved(monkeypatch):
    monkeypatch.setattr(providers, '_ANTHROPIC_KEY', '')
    monkeypatch.setattr(providers, '_config_for', lambda name: {'enabled': False, 'key_secret_ref': 'fixture'})
    monkeypatch.setattr(providers, '_resolve_key', lambda cfg: (_ for _ in ()).throw(AssertionError('disabled reference resolved')))
    assert providers._text_key_for('anthropic') == ''


def test_anthropic_reference_failure_retains_env_fallback(monkeypatch):
    monkeypatch.setattr(providers, '_ANTHROPIC_KEY', 'fixture-env-key')
    monkeypatch.setattr(providers, '_config_for', lambda name: {'enabled': True, 'key_secret_ref': 'fixture'})
    monkeypatch.setattr(providers, '_resolve_key', lambda cfg: None)
    assert providers._text_key_for('anthropic') == 'fixture-env-key'
