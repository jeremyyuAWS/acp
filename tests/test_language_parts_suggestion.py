"""3.1.2 prescriptive auto-detect (user ask 2026-07-12: "can't AI detect it's French?").

The review card for Language of Parts used to fetch a generic text-model draft, which
produced rule-mismatched nonsense ("add alt text", "rename the file with hyphens"). The
language of a passage is machine-detectable: language_parts_suggestion runs seeded
langdetect over the document text — including OCR text with letter-spacing artifacts
("Le r appor t t r i mest r i el") — and pre-fills the card with the detected language +
the actual passage as evidence. Deterministic, real detections only (ADR 0016); the
/ai/suggest route answers 3.1.2 from it BEFORE any model, and falls back to an honest
template (never the text model) when nothing detects.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import proposals  # noqa: E402
import textchecks  # noqa: E402

needs_langdetect = pytest.mark.skipif(
    not textchecks._langdetect_available(), reason="langdetect not installed")

_EN = ("The quarterly report shows significant revenue growth across all European "
       "regions this year. To approve the request, open the compliance dashboard and "
       "select the pending documents queue for your department today.")
_FR = ("Le rapport trimestriel montre une croissance significative des revenus dans "
       "toutes les régions européennes cette année selon la direction financière.")
# The exact artifact class from the live card: OCR of stylized rendered text splits
# words into fragments, so word-based segmentation/gating can never see "rapport".
_FR_OCR = ("Le r appor t t r i mest r i el mont r e une cr oi ssance si gni fi cat i ve "
           "des r evenus dans t out es l es r égi ons eur opéennes cet t e année")


@needs_langdetect
def test_detects_french_passage_in_mixed_text():
    r = proposals.language_parts_suggestion(f"{_EN}\n{_FR}\n{_EN}")
    assert r is not None and r["deterministic"] is True and r["is_template"] is False
    assert 'lang="fr"' in r["suggestion"] and "French" in r["suggestion"]
    assert "Le rapport trimestriel" in r["suggestion"]     # the evidence is the real passage
    assert r["model"] == "langdetect (deterministic)"
    assert any(lang["code"] == "fr" for lang in r["languages"])


@needs_langdetect
def test_detects_french_through_ocr_letter_spacing():
    # The user's exact question: the text is badly formatted (OCR fragments), but the
    # language is still detectable once spaces are collapsed to let char n-grams work.
    r = proposals.language_parts_suggestion(f"{_EN}\n{_FR_OCR}\n{_EN}")
    assert r is not None
    assert 'lang="fr"' in r["suggestion"]
    # the sample shown to the reviewer stays the ORIGINAL text (what they see on screen)
    assert "Le r appor t" in r["suggestion"]


@needs_langdetect
def test_single_language_text_returns_none():
    # One language across the whole text is the document's PRIMARY language (3.1.1), not a
    # part — suggesting it would be wrong, so the card degrades to the honest template.
    assert proposals.language_parts_suggestion(f"{_EN} {_EN}") is None


def test_empty_and_unavailable_degrade_to_none():
    assert proposals.language_parts_suggestion("") is None


def test_despace_only_fires_on_fragmented_text():
    assert proposals._despace_ocr("normal English words here okay") == "normal English words here okay"
    assert " " not in proposals._despace_ocr("t r i mest r i el mont r e")
    # Non-alphabetic tokens mean it is a slash-list/numbered line, NOT OCR letter-splitting —
    # joining "4 frontier / mini / nano" minted a confident-but-wrong "Italian" on a real doc.
    unchanged = "4 frontier / mini / nano model tiers"
    assert proposals._despace_ocr(unchanged) == unchanged


@needs_langdetect
def test_code_segments_never_detect_as_language():
    # extract_text on an HTML file includes inline CSS, which langdetect confidently
    # mislabels ('h1 { margin: 0 }' → Romanian) — a real false positive on the demo corpus.
    css = ("h1 { margin: 0 0 8px; font-size: 30px; }\n"
           "card { border: 1px solid #e1e1e1; border-radius: 10px; padding: 14px; }\n")
    assert proposals.language_parts_suggestion(f"{_EN}\n{css}\n{_EN}") is None
    assert textchecks.detect_language_parts(f"{_EN}\n{css}\n{_EN}") == []       # detector too
    # …but genuine foreign prose in the same document still detects.
    es = ("Bienvenidos — la inscripción abierta para sus beneficios ya está disponible para "
          "todos los empleados y sus familias este año.")
    r = proposals.language_parts_suggestion(f"{_EN}\n{css}\n{es}\n{_EN}")
    assert r is not None and 'lang="es"' in r["suggestion"]


def test_route_answers_312_before_any_model():
    # The wiring: /ai/suggest short-circuits 3.1.2 to the deterministic path, and its
    # fallback is a template — the generic text model is unreachable for this rule.
    src = (Path(__file__).resolve().parent.parent / "api" / "routes" / "ai.py").read_text()
    assert "_language_parts_draft" in src
    suggest = src[src.index("def ai_suggest"):]            # scope to the suggest route
    assert suggest.index('rule_id == "3.1.2"') < suggest.index("ollama_only")
    assert '"is_template": True' in suggest                # honest fallback, not llama


def test_card_labels_deterministic_detection_honestly():
    card = (Path(__file__).resolve().parent.parent / "frontend" / "src" / "EvidenceCard.jsx").read_text()
    assert "Detected deterministically" in card            # not "AI draft · llama3.2"
    assert "r.deterministic" in card
