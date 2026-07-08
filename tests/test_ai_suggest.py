"""Unit tests for the AI-drafted fix-suggestion helper (semantic HITL lane).

No Ollama is required: we assert prompt shaping and that suggest_fix degrades to None
(never raises) when the model is unreachable — the reviewer then writes the value by hand.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
import ai  # noqa: E402


def test_suggest_prompt_is_rule_specific():
    alt = ai._suggest_prompt("1.1.1", "Non-text Content", "deck.pptx", "figure 3")
    assert "alt text" in alt
    assert "cannot see the image" in alt          # honest no-vision template path
    assert "figure 3" in alt                       # finding detail is threaded in

    link = ai._suggest_prompt("2.4.4", "Link Purpose", "page.html", "")
    assert "link text" in link
    assert "destination or purpose" in link


def test_suggest_fix_degrades_to_none_without_ollama(monkeypatch):
    # Force the HTTP call to fail; suggest_fix must swallow it and return None.
    import httpx

    def _boom(*a, **k):
        raise httpx.ConnectError("no ollama")

    monkeypatch.setattr(httpx, "post", _boom)
    assert ai.suggest_fix("1.1.1", "Non-text Content", "A", "deck.pptx") is None


def test_suggest_fix_parses_model_reply(monkeypatch):
    import httpx

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"response": '  "West-region revenue chart"  '}

    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Resp())
    out = ai.suggest_fix("1.1.1", "Non-text Content", "A", "deck.pptx")
    assert out is not None
    assert out["suggestion"] == "West-region revenue chart"   # trimmed + de-quoted
    assert out["kind"] == "alt text"
    assert out["is_template"] is True                          # 1.1.1 = no-vision template
