"""config/vpat-2.5rev.json — the ITI VPAT® template's headings, and the line it must not cross.

The catalog exists so a renderer can lay a report out the way a reader of the official template
expects. Two things therefore have to hold, and only the first is about correctness:

  1. the headings are the template's, per edition, with the requirement sets each edition obliges;
  2. NOTHING BUT HEADINGS IS IN HERE.

(2) is the owner's 2026-09-07 decision (ADR 0053, Q2) expressed as a test rather than as a comment,
because a comment saying "prose must not be reproduced" does not fail when prose is reproduced.
"""
import json
import pathlib

import pytest

from api import acr_catalog

CATALOG = pathlib.Path(__file__).resolve().parent.parent / "config" / "vpat-2.5rev.json"

# What each edition obliges. Duplicated from the generator's own check deliberately: the generator
# proves the catalog matches the templates it parsed, and this proves the catalog matches what
# acr_catalog builds a matrix from. Those are different claims and a single source would hide a
# disagreement between them.
OBLIGES = {
    "VPAT 2.5Rev WCAG": ["wcag-2.2-aa"],
    "VPAT 2.5Rev 508": ["wcag-2.2-aa", "section-508"],
    "VPAT 2.5Rev EU": ["wcag-2.2-aa", "en-301-549"],
    "VPAT 2.5Rev INT": ["wcag-2.2-aa", "section-508", "en-301-549"],
}


def test_every_offerable_edition_has_a_structure():
    """The conjunction that matters: an edition ACP will sell is one the renderer can lay out."""
    for edition in acr_catalog.offerable_editions():
        assert acr_catalog.vpat_report_sections(edition), edition


def test_each_edition_carries_exactly_the_sets_it_obliges():
    for edition, sets in OBLIGES.items():
        got = [s["requirement_set"] for s in acr_catalog.vpat_report_sections(edition)]
        assert got == sets, edition


def test_the_structure_agrees_with_the_matrix_it_will_render():
    """Headings and rows must name the same requirement sets, or a section prints empty.

    This is the check that would have caught #1532's defect at the layout layer: a report whose
    document names a standard its matrix does not carry.
    """
    for edition in OBLIGES:
        headings = {s["requirement_set"] for s in acr_catalog.vpat_report_sections(edition)}
        rows = {r["requirement_set"] for r in acr_catalog.build_matrix("r", edition)}
        assert headings == rows, edition


@pytest.mark.parametrize("edition", sorted(OBLIGES))
def test_the_wcag_section_has_the_templates_three_level_tables(edition):
    wcag = [s for s in acr_catalog.vpat_report_sections(edition)
            if s["requirement_set"] == "wcag-2.2-aa"]
    assert len(wcag) == 1
    assert wcag[0]["subsections"] == [
        "Table 1: Success Criteria, Level A",
        "Table 2: Success Criteria, Level AA",
        "Table 3: Success Criteria, Level AAA",
    ]


def test_the_508_edition_heads_its_wcag_section_2_0_not_2_x():
    """Not a typo, and the reason the headings are a catalog rather than a constant.

    The 508 edition incorporates WCAG 2.0, so ITI heads that section `WCAG 2.0 Report` where the
    other three say `WCAG 2.x Report`. A renderer with one hard-coded string gets one edition wrong
    and no test would notice, because the rows underneath would be identical.
    """
    def heading(edition):
        return next(s["heading"] for s in acr_catalog.vpat_report_sections(edition)
                    if s["requirement_set"] == "wcag-2.2-aa")

    assert heading("VPAT 2.5Rev 508") == "WCAG 2.0 Report"
    for other in ("VPAT 2.5Rev WCAG", "VPAT 2.5Rev EU", "VPAT 2.5Rev INT"):
        assert heading(other) == "WCAG 2.x Report", other


def test_the_columns_are_the_templates_three():
    assert acr_catalog.vpat_table_columns() == [
        "Criteria", "Conformance Level", "Remarks and Explanations"]
    assert acr_catalog.vpat_standards_columns() == [
        "Standard/Guideline", "Included In Report"]


def test_the_508_and_en_sections_name_chapters_and_clauses():
    """The template's own words for the divisions, which are not the standards' own words.

    EN 301 549 calls clause 10 "Non-web documents"; the template writes "Clause 10: Non-web
    Documents" in the EU edition and "Non-Web Documents" in INT. Capturing ITI's inconsistency
    rather than normalising it is the point — a normalised catalog would silently stop matching
    the document it claims to follow.
    """
    five_oh_eight = next(s for s in acr_catalog.vpat_report_sections("VPAT 2.5Rev 508")
                         if s["requirement_set"] == "section-508")
    assert five_oh_eight["subsections"] == [
        "Chapter 3: Functional Performance Criteria (FPC)",
        "Chapter 4: Hardware",
        "Chapter 5: Software",
        "Chapter 6: Support Documentation and Services",
    ]
    en = next(s for s in acr_catalog.vpat_report_sections("VPAT 2.5Rev EU")
              if s["requirement_set"] == "en-301-549")
    assert en["subsections"][0] == "Clause 4: Functional Performance Statements (FPS)"
    assert en["subsections"][-1] == "Clause 13: ICT Providing Relay or Emergency Service Access"
    assert len(en["subsections"]) == 10, "clauses 4-13"


# ── the reproduction line ─────────────────────────────────────────────────────────────────────

def test_no_instructional_prose_was_reproduced():
    """ITI's instructional sections are named in `_meta.not_reproduced` and must appear nowhere.

    Listing them is not decoration: it is the difference between "we did not copy the prose" and
    "we know exactly which prose we did not copy", and the second is the claim ADR 0053 needs.
    """
    meta = acr_catalog.vpat_structure_meta()
    assert "Essential Requirements for Authors" in meta["not_reproduced"]
    assert "Legal Disclaimer (Company)" in meta["not_reproduced"]
    editions = json.dumps(json.loads(CATALOG.read_text())["editions"])
    for banned in meta["not_reproduced"]:
        assert banned not in editions, banned


def test_every_heading_is_a_title_and_not_a_sentence():
    """The same length-and-full-stop test the EN 301 549 generator uses to tell the two apart."""
    for edition in OBLIGES:
        for section in acr_catalog.vpat_report_sections(edition):
            for text in [section["heading"], *section["subsections"]]:
                assert len(text) <= 80, (edition, text)
                assert not text.rstrip().endswith("."), (edition, text)


def test_the_catalog_records_what_it_may_and_may_not_reproduce():
    scope = acr_catalog.vpat_structure_meta()["reproduction_scope"]
    assert "HEADINGS" in scope
    # The half that is easiest to lose: Q2 being answered says nothing about the mark.
    assert "Q1" in scope and "CALLED a VPAT" in scope


def test_the_template_file_itself_is_not_vendored():
    """Option C, asserted. The decision was a scope, not a permission to redistribute the file."""
    config = CATALOG.parent
    assert not list(config.glob("*.docx")), list(config.glob("*.docx"))
    assert not list(config.glob("*vpat*.dotx"))


def test_provenance_is_recorded_for_a_future_revision():
    """When ITI publishes 2.6 this is what tells a reader which revision the layout matched."""
    meta = acr_catalog.vpat_structure_meta()
    assert meta["template"] == "ITI VPAT® 2.5Rev"
    assert meta["revision"] == "April 2025"
    assert meta["source_page"].startswith("https://www.itic.org/")
    assert meta["retrieved"]
