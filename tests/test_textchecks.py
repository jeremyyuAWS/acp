"""1.3.3 Sensory Characteristics + 3.1.2 Language of Parts (api/textchecks.py).

1.3.3 is a pure regex (always tested). 3.1.2 uses langdetect; its OCR-equivalent
round-trip is skipped when langdetect isn't installed.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import textchecks as tc  # noqa: E402


# ── 1.3.3 ──
@pytest.mark.parametrize("text", [
    "To continue, click the round button at the bottom.",
    "Select the option on the right to proceed.",
    "Press the square icon above to expand.",
    "See the panel to the left for details.",
])
def test_sensory_flags_shape_and_location_instructions(text):
    f = tc.detect_sensory(text)
    assert len(f) == 1 and f[0]["wcag"].startswith("1.3.3")


@pytest.mark.parametrize("text", [
    "Click the Submit button to continue.",
    "Select 'Accept' from the Terms menu.",
    "The round table in the lobby seats eight guests.",  # no instruction verb near shape
    "",
])
def test_sensory_ignores_non_sensory_instructions(text):
    assert tc.detect_sensory(text) == []


def test_sensory_one_finding_per_document():
    text = "Click the round button. Also press the icon on the left. And see the box above."
    assert len(tc.detect_sensory(text)) == 1


# ── 3.1.2 ──
_HAS_LANGDETECT = tc._langdetect_available()
needs_langdetect = pytest.mark.skipif(not _HAS_LANGDETECT, reason="langdetect not installed")

_EN = ("The annual report summarises our financial performance and outlines the "
       "strategy for the coming year across every operating region worldwide.")
_FR = ("Le rapport annuel resume nos resultats financiers et decrit la strategie "
       "pour l annee a venir dans chacune de nos regions d exploitation mondiales.")


@needs_langdetect
def test_language_parts_flags_mixed_language_document():
    f = tc.detect_language_parts(_EN + "\n\n" + _FR)
    assert len(f) == 1 and f[0]["wcag"].startswith("3.1.2")


@needs_langdetect
def test_language_parts_ignores_single_language_document():
    assert tc.detect_language_parts(_EN + "\n\n" + _EN) == []


@needs_langdetect
def test_language_parts_reproducible():
    doc = _EN + "\n\n" + _FR
    assert tc.detect_language_parts(doc) == tc.detect_language_parts(doc)


def test_language_parts_short_text_no_flag():
    assert tc.detect_language_parts("Bonjour. Hello.") == []


def test_content_findings_never_raises_on_junk():
    assert isinstance(tc.content_findings(""), list)
    assert isinstance(tc.content_findings("x" * 5), list)
