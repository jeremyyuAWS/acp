"""GPU-assisted 3.1.5 Reading Level proposer — plain-language rewrites for human approval.

Hermetic: the model call (ai.simplify_text) and the detector gate are mocked, so this tests the
selection + shaping logic (target real prose, skip list/heading blobs, preserve the before/after
proposal shape), not the model.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import proposals  # noqa: E402
import ai  # noqa: E402
import textchecks  # noqa: E402

_PROSE = ("The organization must fundamentally reconsider its longstanding operational assumptions "
          "because the accelerating pace of technological transformation renders previously "
          "dependable strategic frameworks increasingly inadequate for contemporary conditions.")


def _gate_on(monkeypatch):
    monkeypatch.setattr(textchecks, "detect_reading_level", lambda t: [{"wcag": "3.1.5"}])
    monkeypatch.setattr(ai, "is_available", lambda: True)
    monkeypatch.setattr(ai, "simplify_text", lambda s, **k: "A short, clear rewrite that keeps the facts.")


def test_proposes_a_plain_language_rewrite_for_dense_prose(monkeypatch):
    _gate_on(monkeypatch)
    props = proposals.propose_reading_level(_PROSE, filename="f.docx", ai_enabled=True)
    assert props and props[0]["before"].startswith("The organization")
    assert props[0]["proposed_value"] == "A short, clear rewrite that keeps the facts."
    assert "3.1" not in props[0]["proposed_value"]                       # it's the rewrite, not a code
    assert "human judgement" in props[0]["source"].lower()               # never auto-applied


def test_skips_flattened_list_and_heading_blobs(monkeypatch):
    _gate_on(monkeypatch)
    listy = ("Executive Sponsor: Suresh Business Owner: Boopesh IT Decision Maker: Priya "
             "Timeline: Q3 Budget: Approved Scope: Global Risk: Medium Status: Active Phase: One")
    assert proposals.propose_reading_level(listy, filename="f.docx", ai_enabled=True) == []


def test_gated_off_when_not_flagged_or_ai_disabled(monkeypatch):
    monkeypatch.setattr(ai, "is_available", lambda: True)
    monkeypatch.setattr(textchecks, "detect_reading_level", lambda t: [])   # doc not above the bar
    assert proposals.propose_reading_level(_PROSE, filename="f.docx", ai_enabled=True) == []
    _gate_on(monkeypatch)
    assert proposals.propose_reading_level(_PROSE, filename="f.docx", ai_enabled=False) == []


def test_no_proposal_when_the_rewrite_equals_the_source(monkeypatch):
    _gate_on(monkeypatch)
    monkeypatch.setattr(ai, "simplify_text", lambda s, **k: s)            # model returned it unchanged
    assert proposals.propose_reading_level(_PROSE, filename="f.docx", ai_enabled=True) == []
