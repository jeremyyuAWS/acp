"""'Draft with AI' must be able to look at the image.

/ai/suggest never passed image bytes, and ai.suggest_fix only consults the vision model when
handed them — so WCAG 1.1.1 always fell through to the text model, which is explicitly told it
cannot see and to emit a fill-in template. The reviewer got a guess derived from the filename,
under a message claiming a vision model had described the image.
"""
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import ai as _ai  # noqa: E402


# ── ai.suggest_fix: the image is what unlocks vision ──────────────────────────

def test_image_bytes_reach_the_vision_model(monkeypatch):
    seen = {}

    def fake_describe(img, *, filename="", context="", style="", **_):
        seen["img"] = img
        return {"alt": "A nurse reviews a chart with a patient.", "model": "llava:7b"}

    monkeypatch.setattr(_ai, "describe_image", fake_describe)
    out = _ai.suggest_fix("1.1.1", "Non-text Content", "A", "deck.pptx", image_bytes=b"PNGBYTES")
    assert seen["img"] == b"PNGBYTES"
    assert out["is_template"] is False
    assert out["suggestion"] == "A nurse reviews a chart with a patient."
    assert out["model"] == "llava:7b"
    assert "reason" not in out          # a real description explains itself


def test_without_an_image_1_1_1_can_only_template(monkeypatch):
    """The regression. No bytes → vision is never consulted → a filename guess."""
    called = []
    monkeypatch.setattr(_ai, "describe_image", lambda *a, **k: called.append(1))

    import httpx

    class _R:
        @staticmethod
        def raise_for_status(): pass
        @staticmethod
        def json(): return {"response": "Describe: [what the image shows]"}

    monkeypatch.setattr(httpx, "post", lambda *a, **k: _R())
    out = _ai.suggest_fix("1.1.1", "Non-text Content", "A", "deck.pptx")
    assert called == []                                  # vision never asked
    assert out["is_template"] is True
    assert "cannot see the image" in out["reason"]       # honest about WHY


def test_vision_that_fails_falls_back_and_says_so(monkeypatch):
    """Bytes in hand but no vision model → template, with a DIFFERENT reason."""
    monkeypatch.setattr(_ai, "describe_image", lambda *a, **k: None)

    import httpx

    class _R:
        @staticmethod
        def raise_for_status(): pass
        @staticmethod
        def json(): return {"response": "Describe: [what the image shows]"}

    monkeypatch.setattr(httpx, "post", lambda *a, **k: _R())
    out = _ai.suggest_fix("1.1.1", "Non-text Content", "A", "d.pptx", image_bytes=b"X")
    assert out["is_template"] is True
    assert "no vision model is available" in out["reason"]


# ── the route wires the locator through ───────────────────────────────────────

def _stub_core(monkeypatch, trace):
    import core
    monkeypatch.setattr(core, "store", types.SimpleNamespace(
        get_ai_enabled=lambda: True,
        get_trace_row=lambda s, f, r: trace))


def test_route_hands_the_located_image_to_suggest_fix(monkeypatch):
    import routes.ai as rai
    _stub_core(monkeypatch, {"rule_name": "Non-text Content", "level": "A", "detail": ""})
    monkeypatch.setattr(_ai, "is_available", lambda: True)
    monkeypatch.setattr(rai, "_image_for_locator", lambda *a, **k: b"THE-IMAGE")

    got = {}

    def fake_suggest(**kw):
        got.update(kw)
        return {"suggestion": "alt", "is_template": False}

    monkeypatch.setattr(_ai, "suggest_fix", fake_suggest)
    rai.ai_suggest(request=object(), scan_id="s1", file="deck.pptx", rule_id="1.1.1",
                   locator="ppt/slides/slide1.xml#rId2")
    assert got["image_bytes"] == b"THE-IMAGE"


def test_route_never_fetches_an_image_for_a_non_image_criterion(monkeypatch):
    """2.4.4 link purpose has no picture; don't re-download the document to find one."""
    import routes.ai as rai
    _stub_core(monkeypatch, {"rule_name": "Link Purpose", "level": "A", "detail": ""})
    monkeypatch.setattr(_ai, "is_available", lambda: True)
    monkeypatch.setattr(rai, "_image_for_locator",
                        lambda *a, **k: pytest.fail("must not fetch an image for 2.4.4"))

    got = {}
    monkeypatch.setattr(_ai, "suggest_fix", lambda **kw: (got.update(kw), {"suggestion": "x"})[1])
    rai.ai_suggest(request=object(), scan_id="s1", file="p.docx", rule_id="2.4.4", locator=None)
    assert got["image_bytes"] is None


def test_image_lookup_degrades_to_none_when_source_is_unreachable(monkeypatch):
    """Every failure in the fetch ladder must return None, never 500 the review inbox."""
    import routes.ai as rai
    import routes.scans as rs
    monkeypatch.setattr(rs, "_source_bytes_for_render", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("drive down")))
    assert rai._image_for_locator(object(), "s1", "d.pptx", "word/document.xml#rId9") is None


def test_image_lookup_is_skipped_without_a_locator():
    import routes.ai as rai
    assert rai._image_for_locator(object(), "s1", "d.pptx", None) is None
