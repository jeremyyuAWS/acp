"""VPAT editions — an edition is a claim about CONTENT, and the claim is checked (PRD phase 6).

THE DEFECT THIS FILE EXISTS FOR, measured against this repo at c1dbe89c before the fix:

    report = {'vpat_edition': 'VPAT 2.5Rev 508', ...}
    proj = acr_export_preview.project(report, acr_catalog.build_matrix('acr_demo'))
    proj['template']['edition']            -> 'VPAT 2.5Rev 508'
    len(proj['criteria'])                  -> 55      (all WCAG 2.2 A+AA)
    508 chapter rows (302.x, 501-504, ...) -> NONE
    proj['totals']['total']                -> 55

The exported document declared itself the Section 508 edition and contained none of Section 508 —
not a missing feature but a false statement, in the one document that exists to stop false
statements, headed for a procurement file it cannot be recalled from (PRD §17).

`vpat_edition` was free text at every layer: a text input in AcrMetadataForm, present-but-
unchecked in REQUIRED_METADATA, and ignored by build_matrix, whose signature took only report_id.
Nothing in the system disagreed with the claim because nothing in the system read it.

WHY THE GATE IS "IS THE CATALOG THERE", NOT "DID SOMEBODY TICK A BOX". The check asks whether this
deployment can populate the requirement sets the edition obliges — so it opens when the content
arrives and not before. A 508 catalog landing makes the 508 edition offerable with no edit to the
gate; that ordering is what keeps the claim true rather than merely asserted.
"""
from __future__ import annotations

import sys
from pathlib import Path

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import acr_catalog  # noqa: E402
import acr_export_preview  # noqa: E402
import acr_validation  # noqa: E402


def _clean_report(**over):
    """A report with every required metadata field filled, so the only blocker under test is ours."""
    report = {f: "given" for f in acr_validation.REQUIRED_METADATA}
    report.update({f: "given" for f in acr_validation.ADVISORY_METADATA})
    report["vpat_edition"] = acr_catalog.EDITION_WCAG
    report.update(over)
    return report


# ── the vocabulary ────────────────────────────────────────────────────────────────────────────

def test_iti_publishes_exactly_four_editions():
    assert acr_catalog.EDITIONS == {
        "VPAT 2.5Rev WCAG", "VPAT 2.5Rev 508", "VPAT 2.5Rev EU", "VPAT 2.5Rev INT",
    }


def test_each_edition_obliges_a_different_requirement_set():
    """The reason an edition cannot be a label: the four names denote four different documents."""
    req = acr_catalog.EDITION_REQUIREMENT_SETS
    assert req[acr_catalog.EDITION_WCAG] == {acr_catalog.REQ_WCAG}
    assert req[acr_catalog.EDITION_508] == {acr_catalog.REQ_WCAG, acr_catalog.REQ_SECTION_508}
    assert req[acr_catalog.EDITION_EU] == {acr_catalog.REQ_WCAG, acr_catalog.REQ_EN_301_549}
    assert req[acr_catalog.EDITION_INT] == {
        acr_catalog.REQ_WCAG, acr_catalog.REQ_SECTION_508, acr_catalog.REQ_EN_301_549}
    # Every edition carries WCAG; that is what makes the WCAG tables common to all four.
    assert all(acr_catalog.REQ_WCAG in s for s in req.values())


def test_only_the_wcag_edition_is_offerable_while_wcag_is_the_only_catalog():
    """Pinned to what the repo CONTAINS, so adding a catalog without wiring it fails here.

    config/wcag-2.2-aa.json is the only requirement catalog in this repo — verified by listing
    config/, not assumed. The other three editions are unbuilt, not broken, and the distinction is
    the whole point of `missing_requirement_sets` being separate from `edition_known`.
    """
    assert acr_catalog.requirement_sets_available() == {acr_catalog.REQ_WCAG}
    assert acr_catalog.offerable_editions() == [acr_catalog.EDITION_WCAG]
    for edition in (acr_catalog.EDITION_508, acr_catalog.EDITION_EU, acr_catalog.EDITION_INT):
        assert acr_catalog.missing_requirement_sets(edition), edition


def test_a_typo_and_an_unbuilt_edition_are_different_questions():
    """Conflating them tells an author to hunt for a spelling mistake in a correct spelling."""
    assert not acr_catalog.edition_known("VPAT 2.5Rev Section 508")   # not ITI's name
    assert acr_catalog.edition_known(acr_catalog.EDITION_508)         # real name, unbuilt content
    assert acr_catalog.missing_requirement_sets(acr_catalog.EDITION_508)
    # An unknown edition has no requirement sets to be missing — it is answered by the other check.
    assert acr_catalog.missing_requirement_sets("nonsense") == frozenset()


# ── the publication gate ──────────────────────────────────────────────────────────────────────

def test_the_wcag_edition_publishes_with_no_edition_blocker():
    blockers = acr_validation.validate(_clean_report(), [], {})
    assert [b for b in blockers if b.category == acr_validation.CATEGORY_EDITION_MISMATCH] == []


def test_a_508_report_cannot_publish_while_508_requirements_are_absent():
    """The regression. Before the fix this produced a publishable, exportable, false document."""
    blockers = acr_validation.validate(
        _clean_report(vpat_edition=acr_catalog.EDITION_508), [], {})
    rows = [b for b in blockers if b.category == acr_validation.CATEGORY_EDITION_MISMATCH]
    assert len(rows) == 1
    assert rows[0].blocking is True
    assert rows[0].detail["missing_requirement_sets"] == [acr_catalog.REQ_SECTION_508]
    # The message must name the standard, not just say "invalid" — the author has to know what is
    # absent in order to decide between waiting and picking the WCAG edition.
    assert "Section 508" in rows[0].message


def test_the_int_edition_names_both_absent_standards_not_just_the_first():
    blockers = acr_validation.validate(
        _clean_report(vpat_edition=acr_catalog.EDITION_INT), [], {})
    row = [b for b in blockers if b.category == acr_validation.CATEGORY_EDITION_MISMATCH][0]
    assert row.detail["missing_requirement_sets"] == [
        acr_catalog.REQ_EN_301_549, acr_catalog.REQ_SECTION_508]


def test_an_unknown_edition_is_blocked_as_a_typo_and_lists_the_real_ones():
    blockers = acr_validation.validate(_clean_report(vpat_edition="VPAT 3 Ultra"), [], {})
    row = [b for b in blockers if b.category == acr_validation.CATEGORY_EDITION_MISMATCH][0]
    assert row.blocking is True
    for real in acr_catalog.EDITIONS:
        assert real in row.message


def test_the_gate_stands_at_the_exit_not_only_the_entrance():
    """A report that predates the route guard still cannot publish a false claim.

    The route refuses a bad edition on the way in, but rows created before this change — or
    restored, imported or migrated — never passed it. Validation is the gate of record precisely
    because it runs on stored state rather than on a request body.
    """
    smuggled = _clean_report(vpat_edition=acr_catalog.EDITION_EU)
    assert any(b.category == acr_validation.CATEGORY_EDITION_MISMATCH and b.blocking
               for b in acr_validation.validate(smuggled, [], {}))


# ── the document itself ───────────────────────────────────────────────────────────────────────

def test_the_projection_still_renders_a_wcag_report_unchanged():
    """The fix must not move the honest path. 55 criteria, edition on the template block."""
    proj = acr_export_preview.project(
        _clean_report(), acr_catalog.build_matrix("acr_demo"))
    assert proj["template"]["edition"] == acr_catalog.EDITION_WCAG
    assert proj["totals"]["total"] == 55
    assert len(proj["criteria"]) == 55
