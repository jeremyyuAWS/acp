"""Phase 6.4 groundwork — the EN 301 549 catalog, committed empty, and the rule that reads it.

WHY A STUB IS WORTH COMMITTING. 6.1, 6.2 and 6.3 each cost one lesson about the order in which an
edition becomes offerable, and the EU edition is the next place to spend them. The content is what
is blocked; the shape, the readers and the gate are not. So the file lands empty, records the
question it is waiting on, and is held to being empty by the tests below.

WHAT IS BLOCKED IS REPRODUCTION, NOT ACCESS. Measured from this repo's network on 2026-09-06:

    GET https://www.etsi.org/deliver/.../en_301549v030201p.pdf
      -> HTTP 200, 2 285 361 bytes, application/pdf

The standard is published free of charge. Whether its requirement text may be reproduced in this
repository is the open question — the same shape as ADR 0053's about the ITI VPAT template, and a
question for counsel rather than engineering. Saying "the source cannot be obtained" would be
false, and the stub says so in `_meta.source_reachable` rather than implying otherwise.

THE RULE THIS FILE MOSTLY EXISTS FOR. A requirement set is available only when it is BOTH populated
and renderable — 6.3's lesson written into code instead of a comment. An empty catalog reads as
nothing to offer, so this file changes no behaviour.

THE RENDERER LANDED FIRST, and the tests below say so rather than describing the older state. EN
301 549 is in `_RENDERABLE` now: the projection groups its clauses and both the HTML and Word
renderers print them. The EU edition is still refused, because the catalog holds nothing — which
is the conjunction working, not a contradiction. What remains for 6.4 is exactly one thing, the
requirement text.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import acr_catalog  # noqa: E402

STUB = ACP / "config" / "en-301-549.json"


def test_the_stub_is_committed_and_empty():
    """Empty is the claim. A catalog with invented rows in it would be the exact thing PRD §19
    forbids — a document naming a standard it does not contain, with a file appearing to back it."""
    assert STUB.exists()
    assert acr_catalog.en_301_549_requirements() == []
    assert acr_catalog.en_301_549_sourced() is False


def test_the_stub_records_what_it_is_waiting_on():
    meta = acr_catalog.en_301_549_meta()
    assert meta["status"] == "not-sourced"
    assert meta["version"].startswith("V3.2.1")
    assert "etsi.org" in meta["source_url"]
    # The distinction that keeps the note honest: the source is reachable, the reuse is the
    # question. A reader who takes "blocked" to mean "cannot be downloaded" will look in the wrong
    # place for the unblock.
    assert "200" in meta["source_reachable"]
    assert any("REDISTRIBUTION" in reason or "reproduced" in reason
               for reason in meta["blocked_on"])


def test_the_stub_records_the_row_shape_it_will_be_filled_with():
    """So the eventual parse has a target, and so the renderer can be written against something."""
    shape = acr_catalog.en_301_549_meta()["row_shape"]
    assert set(shape) == {"num", "name", "clause", "kind"}
    # The clause map mirrors config/section-508.json's `_meta.chapters` shape exactly — {num:
    # {"name": ...}} — so acr_export_preview._catalog_division_names reads both with one function.
    clauses = acr_catalog.en_301_549_meta()["clauses"]
    assert clauses["9"]["name"] == "Web"
    assert clauses["11"]["name"] == "Software"


def test_the_eu_and_int_editions_are_still_refused():
    assert acr_catalog.REQ_EN_301_549 not in acr_catalog.requirement_sets_available()
    assert acr_catalog.offerable_editions() == [
        acr_catalog.EDITION_WCAG, acr_catalog.EDITION_508]
    for edition in (acr_catalog.EDITION_EU, acr_catalog.EDITION_INT):
        assert acr_catalog.missing_requirement_sets(edition) == frozenset(
            {acr_catalog.REQ_EN_301_549}), edition


def test_committing_the_stub_changed_nothing_about_what_is_offered():
    """The whole point of landing it empty. If this fails, a file with no requirements in it has
    started counting as a standard this build can report against."""
    assert acr_catalog.requirement_sets_available() == frozenset(
        {acr_catalog.REQ_WCAG, acr_catalog.REQ_SECTION_508})


# ── the rule: populated AND renderable ────────────────────────────────────────────────────────

def test_an_empty_catalog_and_an_absent_one_are_the_same_answer(tmp_path, monkeypatch):
    """Presence is not supply. A rule keyed on the file existing would read the stub as content."""
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"_meta": {}, "requirements": []}), encoding="utf-8")
    monkeypatch.setattr(acr_catalog, "_SECTION_508_PATH", empty)
    assert acr_catalog.requirement_sets_available() == frozenset({acr_catalog.REQ_WCAG})

    monkeypatch.setattr(acr_catalog, "_SECTION_508_PATH", tmp_path / "gone.json")
    assert acr_catalog.requirement_sets_available() == frozenset({acr_catalog.REQ_WCAG})


def test_populating_the_catalog_is_not_enough_on_its_own(tmp_path, monkeypatch):
    """6.3's lesson, enforced rather than remembered.

    A populated catalog with no renderer produces a document naming a standard it does not print —
    #1532's defect, arriving by a third route. EN 301 549 is renderable NOW, so the unrenderable
    half of the conjunction is demonstrated by taking it back out: the rule has to keep refusing a
    set the exports cannot lay out, whichever set that happens to be.
    """
    filled = tmp_path / "en.json"
    filled.write_text(json.dumps({
        "_meta": {"standard": "EN 301 549"},
        "requirements": [{"num": "9.1.1.1", "name": "Non-text content", "clause": "9",
                          "kind": "requirement"}],
    }), encoding="utf-8")
    monkeypatch.setattr(acr_catalog, "_EN_301_549_PATH", filled)
    monkeypatch.setattr(acr_catalog, "_RENDERABLE", frozenset(
        {acr_catalog.REQ_WCAG, acr_catalog.REQ_SECTION_508}))
    acr_catalog._load_en.cache_clear()

    assert acr_catalog._catalog_populated(acr_catalog.REQ_EN_301_549) is True
    assert acr_catalog.REQ_EN_301_549 not in acr_catalog.requirement_sets_available()
    assert acr_catalog.offerable_editions() == [
        acr_catalog.EDITION_WCAG, acr_catalog.EDITION_508]
    acr_catalog._load_en.cache_clear()


def test_the_renderer_landed_before_the_content_and_the_gate_still_holds():
    """The state this slice leaves the repo in, asserted so it cannot be mistaken for the other
    ordering. EN 301 549 IS renderable — the projection and both renderers lay out its clauses —
    and the EU edition is still refused, because the catalog holds nothing. Renderer first was
    deliberate: it depends on no licensing answer, so the day the text lands the edition opens
    without a renderer being written under time pressure."""
    assert acr_catalog.REQ_EN_301_549 in acr_catalog._RENDERABLE
    assert acr_catalog._catalog_populated(acr_catalog.REQ_EN_301_549) is False
    assert acr_catalog.REQ_EN_301_549 not in acr_catalog.requirement_sets_available()


def test_the_edition_opens_only_when_both_halves_are_there(tmp_path, monkeypatch):
    """The other direction, so the rule is shown to be a conjunction and not a way of saying no.

    With the catalog populated — the set is already renderable — the EU edition becomes offerable
    and build_matrix emits its rows. This test is what will pass unchanged on the day the
    requirement text lands, which is the one thing 6.4 still needs.
    """
    filled = tmp_path / "en.json"
    filled.write_text(json.dumps({
        "_meta": {"standard": "EN 301 549"},
        "requirements": [{"num": "9.1.1.1", "name": "Non-text content", "clause": "9",
                          "kind": "requirement"},
                         {"num": "11.7", "name": "User preferences", "clause": "11",
                          "kind": "requirement"}],
    }), encoding="utf-8")
    monkeypatch.setattr(acr_catalog, "_EN_301_549_PATH", filled)
    acr_catalog._load_en.cache_clear()

    assert acr_catalog.REQ_EN_301_549 in acr_catalog.requirement_sets_available()
    assert acr_catalog.offerable_editions() == [
        acr_catalog.EDITION_WCAG, acr_catalog.EDITION_508,
        acr_catalog.EDITION_EU, acr_catalog.EDITION_INT]
    acr_catalog._load_en.cache_clear()


def test_the_wcag_catalog_is_read_by_the_same_rule(tmp_path, monkeypatch):
    """It stores its rows under `criteria`, not `requirements`. A rule that only knew one key
    would drop WCAG out of the available set and refuse every edition there is."""
    assert acr_catalog._catalog_populated(acr_catalog.REQ_WCAG) is True
    monkeypatch.setattr(acr_catalog, "_CATALOG_PATH", tmp_path / "gone.json")
    assert acr_catalog._catalog_populated(acr_catalog.REQ_WCAG) is False


def test_an_unknown_requirement_set_is_not_populated():
    assert acr_catalog._catalog_populated("iso-9001") is False
