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

WHAT THIS DELIBERATELY DOES NOT ASSERT: that the 508 edition is now offerable. It is not. A
matrix builder and a projection that render these rows in their own chapters come next; until
then `requirement_sets_available()` still returns WCAG alone, and the test at the bottom holds it
there so the gate cannot open on a catalog the rest of the pipeline cannot render.
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


def test_the_508_edition_is_offerable_now_that_the_matrix_and_projection_landed():
    """This test used to assert the opposite, exactly as its predecessor said it would.

    It read: "When the matrix builder and the projection land, this test changes with them."
    They landed — `build_matrix` takes an edition and appends the 508 requirement rows, and
    `acr_export_preview` groups rows into sections so the chapters print under their own
    headings. So the gate opens, and it opens because the content arrived rather than because a
    list was edited.

    A gate that stayed shut after its condition was met would be as wrong as one that never
    closed, and much harder to notice.
    """
    assert acr_catalog.section_508_available() is True
    assert acr_catalog.requirement_sets_available() == frozenset(
        {acr_catalog.REQ_WCAG, acr_catalog.REQ_SECTION_508})
    assert acr_catalog.missing_requirement_sets(acr_catalog.EDITION_508) == frozenset()
    assert acr_catalog.offerable_editions() == [acr_catalog.EDITION_WCAG, acr_catalog.EDITION_508]
    # EN 301 549 was never sourced (etsi.org 403s the build environment), so these stay refused.
    for edition in (acr_catalog.EDITION_EU, acr_catalog.EDITION_INT):
        assert acr_catalog.missing_requirement_sets(edition) == {acr_catalog.REQ_EN_301_549}


def test_a_matrix_built_without_an_edition_is_still_wcag_only():
    """Unchanged on purpose: no existing caller and no existing report may be silently re-scoped
    by the edition parameter arriving. The default stays exactly what it always produced."""
    matrix = acr_catalog.build_matrix("rep-508")
    assert len(matrix) == 55
    assert not any(r["criterion_num"].startswith(("30", "40", "50", "60")) for r in matrix)


def test_a_508_matrix_carries_the_requirement_rows_and_not_the_scope_rows():
    """The concrete form of the claim above — measured, which is how #1532's defect was found.

    Only `kind == "requirement"` becomes a row. "502.1 General. Software shall interoperate with
    assistive technology AND SHALL CONFORM TO 502" is a pointer to the sub-provisions below it;
    asking a human to decide it separately would demand a status and remarks for a sentence that
    says nothing the leaves do not.
    """
    matrix = acr_catalog.build_matrix("rep-508", acr_catalog.EDITION_508)
    nums = {r["criterion_num"] for r in matrix}
    reqs = [r for r in acr_catalog.section_508_requirements() if r["kind"] == "requirement"]
    assert len(matrix) == 55 + len(reqs)
    assert "1.4.3" in nums                                   # the WCAG rows are still there
    assert {"302.1", "502.3.14", "603.3"} <= nums            # chapters 3, 5 and 6
    assert "501.1" not in nums and "502.1" not in nums       # scope/General rows are not claims


def test_a_508_row_has_no_wcag_level_and_carries_its_chapter_for_grouping():
    rows = {r["criterion_num"]: r for r in
            acr_catalog.build_matrix("rep-508", acr_catalog.EDITION_508)}
    assert rows["502.3.14"]["level"] is None                 # there is no "AA" in Section 508
    assert rows["502.3.14"]["principle"] == "Software"       # the chapter, used as the heading
    assert rows["1.4.3"]["level"] == "AA"                    # and WCAG rows are untouched
    assert rows["1.4.3"]["principle"] == "Perceivable"


def test_chapter_four_starts_applicable_rather_than_assumed_not_applicable():
    """Hardware will be Not Applicable for most software — but that is a human decision with
    required remarks (PRD §10), never one the catalog makes quietly on somebody's behalf."""
    rows = {r["criterion_num"]: r for r in
            acr_catalog.build_matrix("rep-508", acr_catalog.EDITION_508)}
    hardware = [r for r in rows.values() if r["principle"] == "Hardware"]
    assert hardware, "chapter 4 produced no rows"
    assert all(r["applicable"] is True for r in hardware)
    assert all(r["workflow_state"] == acr_catalog.NOT_EVALUATED for r in hardware)


def test_the_projection_groups_the_chapters_under_their_own_headings():
    """The third prerequisite the gate waited on: a reader must see where WCAG ends."""
    import acr_export_preview
    proj = acr_export_preview.project(
        {"vpat_edition": acr_catalog.EDITION_508},
        acr_catalog.build_matrix("rep-508", acr_catalog.EDITION_508))
    labels = [s["label"] for s in proj["sections"]]
    assert labels[:4] == ["Perceivable", "Operable", "Understandable", "Robust"]
    assert "Functional Performance Criteria" in labels
    assert "Software" in labels
    assert labels.index("Robust") < labels.index("Functional Performance Criteria")
    # Every row lands in exactly one section, and none is lost in the grouping.
    assert sum(len(s["criteria"]) for s in proj["sections"]) == len(proj["criteria"])


def test_the_projection_orders_dotted_numbers_numerically_not_as_text():
    import acr_export_preview
    proj = acr_export_preview.project(
        {"vpat_edition": acr_catalog.EDITION_508},
        acr_catalog.build_matrix("rep-508", acr_catalog.EDITION_508))
    order = [c["criterion_num"] for c in proj["criteria"]]
    assert order.index("502.3.2") < order.index("502.3.10"), "text sort would invert these"
