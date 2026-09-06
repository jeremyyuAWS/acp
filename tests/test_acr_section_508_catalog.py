"""The Revised Section 508 requirement catalog — Phase 6, the 508 edition's missing content.

#1532 made `vpat_edition` a checked claim: an edition obliges a report to carry a requirement set,
and publication is refused when this build cannot supply one. Only WCAG could be supplied, so
three of ITI's four editions were refused. This is the first of the two missing sets.

The numbers below were DERIVED by parsing 36 CFR Part 1194 Appendix C
(scripts/gen_section_508_catalog.py), not recalled — the distinction is not academic here. The
generator's own spot-check list was first written from memory and named 602.4 "Support
Documentation Alternate Formats"; the regulation calls it "Alternate Formats for Non-Electronic
Support Documentation", and the guard caught it on the first run. They are pinned so that a
regeneration producing a different set has to be looked at by a person.

THE GATE IS OPEN NOW, and the two tests at the bottom used to assert the opposite. They were held
that way through 6.1 and 6.2 on purpose: offering an edition takes the requirements, a matrix
builder that emits their rows, and a projection every export renders them from, and opening it on
the catalog alone would have produced a document naming Section 508 and printing none of it. 6.3
landed the third, so the assertions flipped with it rather than ahead of it.
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

CATALOG_PATH = ACP / "config" / "section-508.json"
SOURCE_PATH = ACP / "config" / "section-508-source.xml"

# Per chapter, from the regulation. Chapter 4 is hardware and dominates the count — which is a
# fact about Section 508, not a bug, and is why scoping the matrix is its own decision.
EXPECTED_PER_CHAPTER = {"3": 10, "4": 69, "5": 33, "6": 8}
TOTAL = 120


def test_the_catalog_and_its_source_are_both_committed():
    """--check must never fetch, so the source it re-parses has to be in the tree."""
    assert CATALOG_PATH.exists(), "config/section-508.json is missing"
    assert SOURCE_PATH.exists(), "config/section-508-source.xml is missing — --check would be blind"


def test_every_reportable_chapter_is_present_and_complete():
    counts: dict[str, int] = {}
    for row in acr_catalog.section_508_requirements():
        counts[row["chapter"]] = counts.get(row["chapter"], 0) + 1
    assert counts == EXPECTED_PER_CHAPTER
    assert len(acr_catalog.section_508_requirements()) == TOTAL


def test_chapter_7_is_excluded_because_it_names_documents_not_requirements():
    """Appendix C carries a Chapter 7 (Referenced Standards). A product does not conform to it."""
    assert all(r["chapter"] in EXPECTED_PER_CHAPTER
               for r in acr_catalog.section_508_requirements())
    assert acr_catalog.section_508_requirement("702.1") is None


@pytest.mark.parametrize("num,name,chapter", [
    ("302.1", "Without Vision", "3"),
    ("302.9", "With Limited Language, Cognitive, and Learning Abilities", "3"),
    ("402.2.1", "Information Displayed On-Screen", "4"),
    ("502.4", "Platform Accessibility Features", "5"),
    ("602.4", "Alternate Formats for Non-Electronic Support Documentation", "6"),
])
def test_named_requirements_match_the_regulation(num, name, chapter):
    """Checkable by eye against 36 CFR 1194 Appendix C, which is the point of pinning them."""
    row = acr_catalog.section_508_requirement(num)
    assert row is not None, f"{num} missing from the catalog"
    assert row["name"] == name
    assert row["chapter"] == chapter


def test_requirements_are_in_regulation_order_and_unique():
    nums = [r["num"] for r in acr_catalog.section_508_requirements()]
    assert len(nums) == len(set(nums))
    assert nums == sorted(nums, key=lambda n: tuple(int(p) for p in n.split(".")))


def test_scope_provisions_are_marked_rather_than_dropped():
    """Which rows a report answers is a scoping decision, made later and from data."""
    rows = acr_catalog.section_508_requirements()
    kinds = {r["kind"] for r in rows}
    assert kinds == {"scope", "requirement"}
    assert acr_catalog.section_508_requirement("501.1")["kind"] == "scope"
    assert acr_catalog.section_508_requirement("502.4")["kind"] == "requirement"
    # A catalog that marked everything scope, or nothing, would satisfy the set check above.
    assert 10 < sum(1 for r in rows if r["kind"] == "scope") < TOTAL // 2


def test_provenance_names_the_regulation_and_the_date_it_was_read_at():
    meta = acr_catalog.section_508_meta()
    assert meta["citation"].startswith("36 CFR Part 1194")
    assert "ecfr.gov" in meta["source_url"]
    assert meta["ecfr_date"]
    assert meta["total"] == TOTAL
    assert "Chapter 7" in meta["derivation"], "the exclusion has to be stated, not just done"


def test_the_generator_and_the_runtime_agree_about_the_hash():
    """The same guard tests/test_acr_catalog.py holds over the WCAG catalog, for the same reason:
    a report stamps a hash, and the script that writes the file must compute it the same way the
    runtime that reads it does."""
    import gen_section_508_catalog

    raw = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    assert gen_section_508_catalog.catalog_hash(raw) == acr_catalog.section_508_hash()


def test_check_mode_passes_against_the_committed_catalog():
    """CI runs this; it must be green on the tree as committed, and it must not fetch."""
    import gen_section_508_catalog

    committed = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    source = SOURCE_PATH.read_text(encoding="utf-8")
    assert gen_section_508_catalog.check(committed, source) == []


def test_check_mode_catches_a_dropped_requirement():
    """A guard that cannot fail is indistinguishable from one that passed."""
    import gen_section_508_catalog

    committed = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    committed["requirements"] = [r for r in committed["requirements"] if r["num"] != "302.1"]
    problems = gen_section_508_catalog.check(committed, None)
    assert problems, "dropping a functional performance criterion went unnoticed"
    assert any("chapter 3" in p for p in problems)


def test_check_mode_catches_drift_only_the_source_can_see():
    """The re-parse is the guard's teeth, and it needed its own test to prove it.

    Written after a bite check found nothing: disabling the comparison against the vendored source
    left every test green, because the others assert `check` returns NO problems and removing a
    check can only remove problems. So this alters a requirement the counts and the spot-check list
    both miss — 403.1 is neither the first nor the last of its chapter and is not spot-checked —
    and only a re-parse of the regulation can tell.
    """
    import gen_section_508_catalog

    committed = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    for row in committed["requirements"]:
        if row["num"] == "403.1":
            row["name"] = "Biometrics May Be The Only Means"
    source = SOURCE_PATH.read_text(encoding="utf-8")
    assert gen_section_508_catalog.check(committed, None) == [], (
        "the count and spot checks are supposed to miss this — otherwise it proves nothing")
    problems = gen_section_508_catalog.check(committed, source)
    assert any("vendored source" in p for p in problems)


def test_check_mode_catches_a_renamed_requirement():
    import gen_section_508_catalog

    committed = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    for row in committed["requirements"]:
        if row["num"] == "302.1":
            row["name"] = "Without Sight"
    problems = gen_section_508_catalog.check(committed, None)
    assert any("302.1" in p for p in problems)


def test_the_508_edition_is_offerable_now_that_the_whole_chain_exists():
    """This test used to assert the opposite, and the change is the record of what it took.

    Offering an edition takes three things, not one: the requirements (this catalog, 6.1), a
    matrix builder that emits their rows (6.2), and a projection every export renders them from
    (6.3). It was held shut through 6.1 and 6.2 precisely so the gate could not open on content
    nothing could print — PRD §19, never claim conformance to a standard the document does not
    contain.
    """
    assert acr_catalog.section_508_available() is True
    assert {acr_catalog.REQ_WCAG, acr_catalog.REQ_SECTION_508} <= (
        acr_catalog.requirement_sets_available())
    assert acr_catalog.missing_requirement_sets(acr_catalog.EDITION_508) == frozenset()
    assert acr_catalog.offerable_editions()[:2] == [
        acr_catalog.EDITION_WCAG, acr_catalog.EDITION_508]


def test_the_wcag_edition_carries_no_508_rows():
    """The default edition is unchanged by any of this: a WCAG report is 55 WCAG rows and nothing
    else, which is what stops the 508 requirements leaking into a document that never claimed
    them."""
    matrix = acr_catalog.build_matrix("rep-wcag")
    assert len(matrix) == 55
    assert not any(r["criterion_num"].startswith(("30", "40", "50", "60")) for r in matrix)
