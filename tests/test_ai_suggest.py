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


# ── Vision alt text (llava-class model) ──────────────────────────────────────

def test_clean_alt_strips_leads_and_labels():
    assert ai._clean_alt("The image displays a red barn.") == "A red barn."
    assert ai._clean_alt("This image shows a bar chart of revenue") == "A bar chart of revenue"
    assert ai._clean_alt('Alt text: "A dog on a beach"') == "A dog on a beach"
    assert ai._clean_alt("  a photo   of\n a cat  ") == "A cat"
    assert ai._clean_alt("") == ""


def _vision_resp(monkeypatch, text):
    import httpx

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"response": text}

    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Resp())


def test_describe_image_returns_clean_alt(monkeypatch):
    _vision_resp(monkeypatch, "The image shows a wheelchair-accessible ramp entrance.")
    out = ai.describe_image(b"\x89PNGfakebytes", filename="lobby.docx")
    assert out is not None
    assert out["alt"] == "A wheelchair-accessible ramp entrance."   # lead stripped, capitalised
    assert out["model"] == ai.OLLAMA_VISION_MODEL


def test_describe_image_rejects_one_word_reply(monkeypatch):
    # A degenerate reply that wouldn't clear 1.1.1 must be treated as a miss.
    _vision_resp(monkeypatch, "image")
    assert ai.describe_image(b"bytes", filename="x.docx") is None


def test_describe_image_degrades_to_none_without_ollama(monkeypatch):
    import httpx

    def _boom(*a, **k):
        raise httpx.ConnectError("no ollama")

    monkeypatch.setattr(httpx, "post", _boom)
    assert ai.describe_image(b"bytes") is None
    assert ai.describe_image(b"") is None                            # no bytes → None


def test_suggest_fix_uses_vision_when_image_supplied(monkeypatch):
    _vision_resp(monkeypatch, "A campus map with step-free routes highlighted.")
    out = ai.suggest_fix("1.1.1", "Non-text Content", "A", "map.docx",
                         image_bytes=b"\x89PNGrealimage")
    assert out is not None
    assert out["suggestion"] == "A campus map with step-free routes highlighted."
    assert out["is_template"] is False                              # genuine alt, not a template
    assert out["kind"] == "alt text"


def test_suggest_fix_falls_back_to_template_when_vision_fails(monkeypatch):
    # Vision returns junk → fall through to the text-model template path (still 1.1.1).
    import httpx
    calls = {"n": 0}

    class _Resp:
        def __init__(self, text):
            self._t = text

        def raise_for_status(self):
            pass

        def json(self):
            return {"response": self._t}

    def _post(*a, **k):
        calls["n"] += 1
        # 1st + 2nd calls = vision: the full prompt, then the bare retry a compact model needs
        # (ai._minimal_vision_prompt). Both junk here — vision only really fails once BOTH have
        # been tried. 3rd = the text template.
        return _Resp("image" if calls["n"] <= 2 else "Describe: [what the image shows]")

    monkeypatch.setattr(httpx, "post", _post)
    out = ai.suggest_fix("1.1.1", "Non-text Content", "A", "map.docx", image_bytes=b"bytes")
    assert out is not None
    assert out["is_template"] is True                               # fell back to template
    assert calls["n"] == 3


def test_vision_prompt_is_ocr_and_chart_aware():
    # Phase 1 of the AI-propose expansion: alt text must READ embedded text (headlines,
    # labels, data) and describe charts by type + key figure — the customer's #1 opportunity.
    low = ai._vision_prompt("q3.pptx", "Quarterly figures").lower()
    assert "read any text inside" in low
    assert "chart" in low and ("takeaway" in low or "figure" in low)
    assert "verbatim" in low                        # embedded text must be preserved, not lost


def test_describe_image_captures_chart_content(monkeypatch):
    _vision_resp(monkeypatch, "Bar chart comparing quarterly 2026 sales; Q4 highest at $2.1M.")
    out = ai.describe_image(b"\x89PNGfake", filename="sales.pptx", context="Revenue")
    assert out and out["alt"] == "Bar chart comparing quarterly 2026 sales; Q4 highest at $2.1M."
    assert "$2.1M" in out["alt"]                     # the key figure survives cleaning
