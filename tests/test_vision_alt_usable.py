"""The vision draft must clear a usability floor or defer to a human — a weak model (moondream) can
return non-empty GARBAGE that the empty-check misses. Cases are taken from the 2026-08-12 vision
bake-off, where moondream emitted symbol runs and single-token fragments on real document images."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import ai  # noqa: E402


def test_rejects_the_bakeoff_garbage():
    for junk in ["", "   ", "~~~~~~~~~~~~~~Moviaio~~~~~~~~~~~~~~", "!!!Readings #1!",
                 "...", "Q3", "x", "-- --", "###", "1"]:
        assert ai._is_usable_alt(junk) is False, f"should reject: {junk!r}"


def test_accepts_real_descriptions():
    for good in [
        "Bar chart of Q3 admissions by department, Emergency highest at 480.",
        "Mova.io logo.",
        "Flowchart of the patient intake process with five steps.",
        "Scatter plot of blood pressure readings with one high outlier at 168 mmHg.",
        "Medication schedule table.",
    ]:
        assert ai._is_usable_alt(good) is True, f"should accept: {good!r}"


def test_describe_image_defers_to_human_on_garbage(monkeypatch):
    # Non-empty garbage from the model → describe_image returns None, which routes the image to a
    # human (the same path an empty reply takes) instead of writing nonsense alt into the document.
    monkeypatch.setattr(ai, "_vision_generate", lambda *a, **k: "~~~~~~Moviaio~~~~~~")
    assert ai.describe_image(b"imagebytes") is None


def test_describe_image_returns_a_usable_draft(monkeypatch):
    monkeypatch.setattr(ai, "_vision_generate", lambda *a, **k: "Bar chart of admissions by department.")
    out = ai.describe_image(b"imagebytes")
    assert out and out["alt"] == "Bar chart of admissions by department."
