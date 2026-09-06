"""The EN 301 549 catalog — Phase 6.4's last piece, and the licensing constraint it works under.

This file used to be test_acr_en_301_549_stub.py and asserted the opposite of most of what it
asserts now: that the catalog was empty and the EU edition refused. It was written that way on
purpose, because the content was blocked on a question only the owner could answer. On 2026-09-06
they answered it narrowly — clause NUMBERS and TITLES may be reproduced here, the normative
requirement text may not — and that is enough to populate the catalog and open the edition.

So the assertions flip, and the ordering that got here is worth keeping legible:

  6.1  the requirements        config/section-508.json                    (508)
  6.2  rows in the matrix      build_matrix(report_id, edition)
  6.3  rows in the document    the projection and all three renderers
  6.4  the requirements        config/en-301-549.json                     (EU) — this
       and the renderer first, which is why nothing else had to change

WHAT THE LICENSING CONSTRAINT MEANS FOR THE TESTS. Two of them exist only to enforce it: the
catalog carries exactly four fields per row, and no field reads as requirement text rather than a
title. A catalog that quietly grew a "text" field would breach the permission this feature was
given, and no other test in the repo would notice.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))
sys.path.insert(0, str(ACP / "scripts"))

import acr_catalog  # noqa: E402

CATALOG = ACP / "config" / "en-301-549.json"
WCAG = ACP / "config" / "wcag-2.2-aa.json"

# From the standard's own contents page, per clause. Pinned so a regeneration that produces a
# different shape has to be looked at by a person.
EXPECTED_PER_CLAUSE = {"4": 12, "5": 34, "6": 18, "7": 9, "8": 28,
                       "9": 58, "10": 58, "11": 83, "12": 6, "13": 8}
TOTAL = 314


def test_the_catalog_is_populated():
    assert acr_catalog.en_301_549_sourced() is True
    assert len(acr_catalog.en_301_549_requirements()) == TOTAL


def test_every_reportable_clause_is_present_and_complete():
    counts: dict[str, int] = {}
    for row in acr_catalog.en_301_549_requirements():
        counts[row["clause"]] = counts.get(row["clause"], 0) + 1
    assert counts == EXPECTED_PER_CLAUSE


def test_clauses_1_to_3_and_14_are_excluded():
    """They say what the document is and how to claim against it, not what a product must do —
    the same reasoning that drops Chapter 7 from the Section 508 catalog."""
    clauses = {r["clause"] for r in acr_catalog.en_301_549_requirements()}
    assert clauses == set(EXPECTED_PER_CLAUSE)
    nums = {r["num"] for r in acr_catalog.en_301_549_requirements()}
    assert not any(n.startswith(("1.", "2.", "3.", "14.")) for n in nums)


@pytest.mark.parametrize("num,name", [
    ("4.2.1", "Usage without vision"),
    ("9.1.1.1", "Non-text content"),
    ("10.1.1.1", "Non-text content"),
    ("11.7", "User preferences"),
    ("13.1.2", "Text relay services"),
])
def test_named_clauses_match_the_standard(num, name):
    """Checkable by eye against any published copy of the contents page."""
    rows = {r["num"]: r["name"] for r in acr_catalog.en_301_549_requirements()}
    assert rows.get(num) == name


def test_no_row_is_a_heading():
    """A clause with sub-clauses is a heading, not something a product conforms to. Derived from
    the numbering rather than judged, so a regeneration that stopped applying the rule shows up
    here rather than as extra rows nobody can answer."""
    nums = [r["num"] for r in acr_catalog.en_301_549_requirements()]
    for num in nums:
        assert not any(other.startswith(f"{num}.") for other in nums), f"{num} has children"


def test_clause_9_carries_the_success_criteria_not_just_the_guidelines():
    """The gap that nearly shipped. The contents page lists clause 9 to guideline depth — 9.1.1
    Text alternatives — and stopping there would have produced a EU report with sixteen rows where
    the standard has fifty-six, while still calling itself the EU edition."""
    nine = [r["num"] for r in acr_catalog.en_301_549_requirements() if r["clause"] == "9"]
    assert "9.1.1.1" in nine
    assert "9.1.1" not in nine, "the guideline is a heading; its criteria are the rows"
    assert sum(1 for n in nine if n.count(".") == 3) >= 50


def test_the_wcag_derived_titles_agree_with_this_repos_wcag_catalog():
    """The measurement that justified reading titles out of the PDF body at all.

    EN clause 9.x.y.z IS WCAG x.y.z, so the two can be compared — and body headings are the noisy
    source (parsed alone they yield truncated titles like "Concurrent voice and").

    CASE IS NORMALISED, AND THAT IS NOT A FUDGE: EN 301 549 writes its titles in sentence case
    throughout ("Non-text content") where WCAG uses title case ("Non-text Content"), so a
    case-sensitive comparison measures a house style rather than a mismatch. An earlier reading of
    this comparison reported "44 exact" without saying it had folded case, which overstated it —
    the figure was always case-insensitive.

    What remains after folding case is five real word-level differences, listed rather than
    tolerated by a fuzzy comparison: "close enough" would also accept a title that was truncated
    or wrong. Measured on 2026-09-06 against config/wcag-2.2-aa.json.
    """
    wcag = {c["num"]: c["name"] for c in json.loads(WCAG.read_text(encoding="utf-8"))["criteria"]}
    house_style = {
        "9.1.2.1": "Audio-only and video-only (pre-recorded)",
        "9.1.2.2": "Captions (pre-recorded)",
        "9.1.2.3": "Audio description or media alternative (pre-recorded)",
        "9.1.2.5": "Audio description (pre-recorded)",
        "9.1.4.1": "Use of colour",
    }
    exact = differing = absent = 0
    for row in acr_catalog.en_301_549_requirements():
        if row["clause"] != "9" or row["num"].count(".") != 3:
            continue
        criterion = wcag.get(row["num"][2:])
        if criterion is None:
            absent += 1
        elif criterion.casefold() == row["name"].casefold():
            exact += 1
        else:
            assert row["num"] in house_style, f"{row['num']}: {row['name']!r} vs {criterion!r}"
            assert row["name"] == house_style[row["num"]]
            differing += 1
    assert (exact, differing, absent) == (44, 5, 6)


# ── the licensing constraint, enforced ────────────────────────────────────────────────────────

def test_the_catalog_carries_no_requirement_text():
    """The permission was for numbers and titles. A row with prose in it would breach it, and
    nothing else in this repo would notice."""
    for row in acr_catalog.en_301_549_requirements():
        assert set(row) == {"num", "name", "clause", "kind"}, row["num"]
        assert len(row["name"]) <= 90, row
        assert not row["name"].rstrip().endswith("."), row

    raw = json.loads(CATALOG.read_text(encoding="utf-8"))
    assert "requirement_text" not in json.dumps(raw)
    assert raw["_meta"]["reproduction_scope"].startswith("Clause NUMBERS and TITLES only")


def test_no_source_pdf_is_vendored():
    """The WCAG and Section 508 generators commit their sources; this one must not, because the
    source is the whole standard. --check is weaker as a result, and the generator says so."""
    assert not list((ACP / "config").glob("*en_301549*"))
    assert not list((ACP / "config").glob("en-301-549-source*"))


def test_check_mode_passes_and_catches_contamination():
    import gen_en_301_549_catalog

    committed = json.loads(CATALOG.read_text(encoding="utf-8"))
    assert gen_en_301_549_catalog.check(committed) == []

    committed["requirements"][0]["name"] = (
        "Where ICT is a closed functionality, it shall be operable without requiring the user to "
        "attach or install assistive technology.")
    problems = gen_en_301_549_catalog.check(committed)
    assert any("requirement text" in p for p in problems)


def test_check_mode_catches_a_heading_creeping_back_in():
    import gen_en_301_549_catalog

    committed = json.loads(CATALOG.read_text(encoding="utf-8"))
    committed["requirements"].append(
        {"num": "9.1.1", "name": "Text alternatives", "clause": "9", "kind": "requirement"})
    committed["_meta"]["total"] += 1
    committed["_meta"]["clauses"]["9"]["count"] += 1
    problems = gen_en_301_549_catalog.check(committed)
    assert any("heading" in p for p in problems)


def test_check_mode_catches_an_emptied_catalog():
    """An empty catalog silently un-offers the EU edition — the failure would show up as an
    edition disappearing from a dropdown, a long way from its cause."""
    import gen_en_301_549_catalog

    problems = gen_en_301_549_catalog.check({"_meta": {"status": "sourced"}, "requirements": []})
    assert any("no requirements" in p for p in problems)


# ── what the population unlocks ───────────────────────────────────────────────────────────────

def test_all_four_editions_are_offerable_now():
    """The end of the sequence #1532 started. It found a report declaring the Section 508 edition
    and containing none of it; the fix refused every edition this build could not supply, and
    three of the four were refused. All four can be supplied now."""
    assert acr_catalog.requirement_sets_available() == frozenset(
        {acr_catalog.REQ_WCAG, acr_catalog.REQ_SECTION_508, acr_catalog.REQ_EN_301_549})
    assert acr_catalog.offerable_editions() == [
        acr_catalog.EDITION_WCAG, acr_catalog.EDITION_508,
        acr_catalog.EDITION_EU, acr_catalog.EDITION_INT]
    for edition in acr_catalog.EDITIONS:
        assert acr_catalog.missing_requirement_sets(edition) == frozenset(), edition


def test_the_int_edition_carries_all_three_standards():
    matrix = acr_catalog.build_matrix("rep-int", acr_catalog.EDITION_INT)
    counts: dict[str, int] = {}
    for row in matrix:
        counts[row["requirement_set"]] = counts.get(row["requirement_set"], 0) + 1
    assert counts == {acr_catalog.REQ_WCAG: 55, acr_catalog.REQ_SECTION_508: 120,
                      acr_catalog.REQ_EN_301_549: TOTAL}


def test_an_en_row_carries_its_clause_as_the_division():
    rows = [r for r in acr_catalog.build_matrix("rep-eu", acr_catalog.EDITION_EU)
            if r["requirement_set"] == acr_catalog.REQ_EN_301_549]
    assert {r["chapter"] for r in rows} == set(EXPECTED_PER_CLAUSE)
    assert all(r["level"] is None and r["principle"] is None for r in rows)


# ── the rule that got us here, still enforced in both directions ──────────────────────────────

def test_an_empty_catalog_and_an_absent_one_are_the_same_answer(tmp_path, monkeypatch):
    """Presence is not supply. Held over from the stub, because it is the rule that kept the
    edition shut while the catalog was empty — and the one that will shut it again if a deployment
    ships without the file."""
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"_meta": {}, "requirements": []}), encoding="utf-8")
    monkeypatch.setattr(acr_catalog, "_EN_301_549_PATH", empty)
    acr_catalog._load_en.cache_clear()
    assert acr_catalog.REQ_EN_301_549 not in acr_catalog.requirement_sets_available()

    monkeypatch.setattr(acr_catalog, "_EN_301_549_PATH", tmp_path / "gone.json")
    assert acr_catalog.REQ_EN_301_549 not in acr_catalog.requirement_sets_available()
    acr_catalog._load_en.cache_clear()


def test_populated_is_still_not_enough_without_a_renderer(monkeypatch):
    """The other half of the conjunction. The catalog is populated now, so the unrenderable case
    is shown by taking EN back out of _RENDERABLE: a set the exports cannot lay out must stay
    refused however complete its catalog is."""
    monkeypatch.setattr(acr_catalog, "_RENDERABLE", frozenset(
        {acr_catalog.REQ_WCAG, acr_catalog.REQ_SECTION_508}))
    assert acr_catalog._catalog_populated(acr_catalog.REQ_EN_301_549) is True
    assert acr_catalog.REQ_EN_301_549 not in acr_catalog.requirement_sets_available()
    assert acr_catalog.offerable_editions() == [
        acr_catalog.EDITION_WCAG, acr_catalog.EDITION_508]
