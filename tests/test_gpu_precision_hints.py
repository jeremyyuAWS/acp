"""GPU-assisted logotype hint on the images-of-text card — a hint, never a decision.

looks_like_logotype (llava yes/no, validated 6/6 on the real Husqvarna/Movate brand marks):
a POSITIVE vision read prepends a logotype hint to the 1.4.9 strict-band card's rationale; a
negative/absent read changes nothing, and a vision crash never sinks the card.

A sibling GPU precision filter for 1.3.3 sensory rewrites was built, live-validated, and
REJECTED (2026-07-11): llama3.2 returned descriptive phrases as control "names" and
suppressed a genuine finding's rewrite on the real corpus. See the note in
proposals.propose_sensory_rewrite — recall must never depend on a model judgement.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import ai  # noqa: E402
import ocr  # noqa: E402
import proposals  # noqa: E402


@pytest.fixture
def _ocr_strict(monkeypatch):
    """One image in the 1.4.9 strict-only band (few words)."""
    imgs = [b"img0"]
    monkeypatch.setattr(ocr, "is_available", lambda: True)
    monkeypatch.setattr(ocr, "_embedded_images", lambda p, e: list(imgs))
    monkeypatch.setattr(ocr, "_ocr_words", lambda img, min_pixels=0: 4)
    monkeypatch.setattr(ocr, "ocr_text", lambda img, **kw: "Movate brand mark")
    monkeypatch.setattr(proposals, "thumb_b64", lambda img, **kw: None)
    return imgs


def test_positive_vision_read_prepends_the_logotype_hint(_ocr_strict, monkeypatch):
    monkeypatch.setattr(ai, "looks_like_logotype", lambda img, **k: True)
    out = proposals.propose_images_of_text("d.pptx", ".pptx")
    assert len(out) == 1
    assert out[0]["rationale"].startswith("The vision model reads this image as a logotype")
    assert "1.4.9" in out[0]["rationale"]              # the honest SC text is still there


@pytest.mark.parametrize("verdict", [False, None])
def test_negative_or_absent_read_changes_nothing(_ocr_strict, monkeypatch, verdict):
    monkeypatch.setattr(ai, "looks_like_logotype", lambda img, **k: verdict)
    out = proposals.propose_images_of_text("d.pptx", ".pptx")
    assert len(out) == 1
    assert not out[0]["rationale"].startswith("The vision model")


def test_a_vision_crash_never_sinks_the_card(_ocr_strict, monkeypatch):
    monkeypatch.setattr(ai, "looks_like_logotype",
                        lambda img, **k: (_ for _ in ()).throw(RuntimeError("gpu gone")))
    assert len(proposals.propose_images_of_text("d.pptx", ".pptx")) == 1


# ── the judge itself: strict parse, one-word replies allowed, fails to None ─────

def test_judge_returns_none_when_vision_unavailable(monkeypatch):
    monkeypatch.setattr(ai, "vision_is_available", lambda: False)
    assert ai.looks_like_logotype(b"img") is None
    assert ai.looks_like_logotype(b"") is None


def test_judge_parses_yes_no_and_rejects_prose(monkeypatch):
    monkeypatch.setattr(ai, "vision_is_available", lambda: True)
    seen = {}
    for reply, want in [("Yes", True), ("no, it is a chart", False), ("It could be", None)]:
        def fake(prompt, img, reply=reply, **kw):
            seen.update(kw)
            return reply
        monkeypatch.setattr(ai, "_vision_generate", fake)
        assert ai.looks_like_logotype(b"img") is want
    # Regression: the alt-text honesty guard rejects one-word replies, so the judge MUST
    # call with clean=False — a re-defaulted call silently breaks every verdict to None.
    assert seen.get("clean") is False
