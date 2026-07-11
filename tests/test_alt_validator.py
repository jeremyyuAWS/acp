"""Semantic alt-text validator (ADR 0019 §3 / #123) — consistency cross-check, not a fabricated score.

The model independently re-describes the image; we compare content-word recall between that and the
proposed alt. Agreement on subject/type → consistent; a gross mismatch → divergent (+ the second
description as evidence). Hermetic: the vision call is mocked, so this tests the honest scoring logic,
not the model.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import ai  # noqa: E402


def _with_second(monkeypatch, second):
    monkeypatch.setattr(ai, "_vision_generate", lambda *a, **k: second)


def test_consistent_when_independent_description_agrees(monkeypatch):
    _with_second(monkeypatch, "A bar chart of quarterly revenue across regions.")
    r = ai.validate_alt_text(b"img", "Bar chart showing quarterly revenue by region.")
    assert r["verdict"] == "consistent" and r["agrees"] is True
    assert {"bar", "chart", "revenue"} <= set(r["shared_terms"])


def test_divergent_on_wrong_subject(monkeypatch):
    # The proposed alt claims a photo of people; the model independently sees a bar chart → mismatch.
    _with_second(monkeypatch, "A bar chart of quarterly revenue across regions.")
    r = ai.validate_alt_text(b"img", "A photograph of a group of people at a conference.")
    assert r["verdict"] == "divergent" and r["agrees"] is False
    assert r["second_opinion"].startswith("A bar chart")     # handed to the reviewer as evidence


def test_short_correct_alt_is_not_falsely_flagged(monkeypatch):
    # A short but correct alt vs a long re-description: recall (not raw overlap) keeps it consistent.
    _with_second(monkeypatch,
                 "The image is a screenshot of a financial Q4 revenue report slide with several rows.")
    r = ai.validate_alt_text(b"img", "Screenshot of a Q4 revenue report slide.")
    assert r["verdict"] == "consistent"


def test_none_when_model_unavailable_or_empty(monkeypatch):
    _with_second(monkeypatch, None)
    assert ai.validate_alt_text(b"img", "anything") is None
    _with_second(monkeypatch, "a description")
    assert ai.validate_alt_text(b"", "alt") is None          # no image
    assert ai.validate_alt_text(b"img", "  ") is None        # no alt


def test_verdict_is_an_enum_never_a_number(monkeypatch):
    _with_second(monkeypatch, "A flowchart of a remediation workflow.")
    r = ai.validate_alt_text(b"img", "Flowchart of the remediation workflow.")
    assert r["verdict"] in ("consistent", "divergent")
    import json
    assert "%" not in json.dumps(r)
