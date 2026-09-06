"""Phase 6.2 — a matrix row says which requirement set it came from, and a 508 edition gets 508 rows.

#1532 found a report that declared the Section 508 edition and contained none of Section 508:
`build_matrix` took only `report_id` and read the WCAG catalog, so `template.edition` said one
thing and the 120 missing rows said another. It closed that by refusing the edition. 6.1 landed
the requirements. This is the builder that can actually produce them.

WHAT IS AND IS NOT REACHABLE YET. `requirement_sets_available()` still returns WCAG alone, so a
508 report cannot be CREATED through the API — the routes refuse it and `build_matrix` refuses it
below them. The tests here reach the 508 path by supplying the availability the projection cannot
yet render for, which is deliberate: the plumbing is proven before the gate opens, not after. 6.3
opens it, when the export can print a Revised Section 508 Report.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import acr_catalog  # noqa: E402


@pytest.fixture
def _508_supplied(monkeypatch):
    """Pretend this build can supply Section 508, without pretending it can render it.

    Patching `requirement_sets_available` rather than editing the module keeps the real gate shut
    for every other test in the suite, and makes the dependency explicit: everything below is
    about the BUILDER, and none of it claims the edition is offerable.
    """
    monkeypatch.setattr(acr_catalog, "requirement_sets_available",
                        lambda: frozenset({acr_catalog.REQ_WCAG, acr_catalog.REQ_SECTION_508}))


def test_the_wcag_edition_is_unchanged_and_is_still_the_default():
    """Every pre-Phase-6 caller passes no edition at all, and must get exactly what it got."""
    default = acr_catalog.build_matrix("rep1")
    explicit = acr_catalog.build_matrix("rep1", acr_catalog.EDITION_WCAG)
    assert default == explicit
    assert len(default) == 55
    assert {r["requirement_set"] for r in default} == {acr_catalog.REQ_WCAG}
    assert all(r["chapter"] is None for r in default)
    assert all(r["level"] in ("A", "AA") for r in default)


def test_every_wcag_row_still_carries_its_wcag_axes():
    """The refactor that introduced _blank_row could have dropped these silently — a matrix with
    no principle still renders, in the wrong order, with a blank column."""
    for row in acr_catalog.build_matrix("rep1"):
        assert row["principle"]
        assert row["guideline"]
        assert row["criterion_name"]


def test_a_508_edition_carries_both_requirement_sets(_508_supplied):
    matrix = acr_catalog.build_matrix("rep508", acr_catalog.EDITION_508)
    by_set: dict[str, int] = {}
    for row in matrix:
        by_set[row["requirement_set"]] = by_set.get(row["requirement_set"], 0) + 1
    assert by_set == {acr_catalog.REQ_WCAG: 55, acr_catalog.REQ_SECTION_508: 120}
    assert len(matrix) == 175


def test_508_rows_carry_a_chapter_and_no_wcag_axes(_508_supplied):
    """The whole point of the column. A 508 row that carried a level would render inside a WCAG
    conformance table, which is the false-claim shape #1532 fixed arriving by another route."""
    rows = [r for r in acr_catalog.build_matrix("rep508", acr_catalog.EDITION_508)
            if r["requirement_set"] == acr_catalog.REQ_SECTION_508]
    assert {r["chapter"] for r in rows} == {"3", "4", "5", "6"}
    assert all(r["level"] is None for r in rows)
    assert all(r["principle"] is None for r in rows)
    assert all(r["guideline"] is None for r in rows)


def test_508_rows_start_unevaluated_like_every_other_row(_508_supplied):
    """PRD §10 — publication is blocked while an applicable row is unevaluated, and a 508 row is
    not exempt from that just because it arrived from a different catalog."""
    rows = [r for r in acr_catalog.build_matrix("rep508", acr_catalog.EDITION_508)
            if r["requirement_set"] == acr_catalog.REQ_SECTION_508]
    assert all(r["workflow_state"] == acr_catalog.NOT_EVALUATED for r in rows)
    assert all(r["final_status"] is None for r in rows)
    assert all(r["applicable"] is True for r in rows)
    assert all(r["approval_state"] == "unapproved" for r in rows)


def test_hardware_is_not_quietly_dropped(_508_supplied):
    """69 of the 120 rows are Chapter 4, and for a hosted web application every one of them ends
    Not Applicable. Applicability is a human decision with required remarks (PRD §10), so the
    builder does not pre-empt it — the cost is a bulk-mark affordance owed to the UI, not a
    chapter this function omits."""
    rows = [r for r in acr_catalog.build_matrix("rep508", acr_catalog.EDITION_508)
            if r["chapter"] == "4"]
    assert len(rows) == 69
    assert all(r["applicable"] is True for r in rows)


def test_numbers_do_not_collide_between_the_two_catalogs(_508_supplied):
    """criterion_num is half the primary key. A WCAG number ("1.4.3") and a 508 number ("402.2.1")
    must never be the same string, or one row would silently overwrite the other on insert."""
    matrix = acr_catalog.build_matrix("rep508", acr_catalog.EDITION_508)
    nums = [r["criterion_num"] for r in matrix]
    assert len(nums) == len(set(nums))


def test_an_edition_this_build_cannot_supply_is_refused():
    """The layer below the routes, for the reason #1532 gave: a report restored, imported or
    migrated never passed them."""
    with pytest.raises(ValueError) as e:
        acr_catalog.build_matrix("rep508", acr_catalog.EDITION_508)
    assert "Revised Section 508" in str(e.value)
    assert "false claim" in str(e.value)


def test_the_eu_edition_is_refused_even_once_508_is_supplied(_508_supplied):
    """EN 301 549 is a separate requirement set with a separate source, and supplying one must not
    open the gate on the other."""
    with pytest.raises(ValueError) as e:
        acr_catalog.build_matrix("repeu", acr_catalog.EDITION_EU)
    assert "EN 301 549" in str(e.value)


def test_an_unknown_edition_is_refused_with_a_different_message():
    """"Misspelled" and "not yet built" are different problems and get different messages —
    the distinction acr_catalog.missing_requirement_sets was written to preserve."""
    with pytest.raises(ValueError) as e:
        acr_catalog.build_matrix("rep", "VPAT 2.5Rev Section 508")
    assert "not one of the four VPAT editions" in str(e.value)


def test_the_store_round_trips_the_requirement_set(isolated_store):
    """The builder's row shape is useless if the INSERT drops it on the floor.

    Exercised through the store rather than the API on purpose: this is the half a route test
    cannot see, because a report's rows are read back through `SELECT *` and an absent column
    reads as an absent key, not as an error.
    """
    matrix = acr_catalog.build_matrix("rep-store")
    isolated_store.create_acr_report("rep-store", owner_email="o@acp.test",
                                     catalog_hash=acr_catalog.catalog_hash(),
                                     criteria=matrix, metadata={})
    rows = isolated_store.list_acr_criteria("rep-store", owner_email="o@acp.test")
    assert len(rows) == 55
    assert {r["requirement_set"] for r in rows} == {acr_catalog.REQ_WCAG}
    assert all(r["chapter"] is None for r in rows)


def test_a_row_from_pre_phase_6_code_is_stored_as_wcag(isolated_store):
    """An old caller passes rows with neither key. Those rows ARE WCAG rows — build_matrix could
    not read another catalog before this slice — so they must land labelled, not NULL, or the
    projection would have to guess at exactly the point guessing is forbidden."""
    legacy = [{"criterion_num": "1.1.1", "criterion_name": "Non-text Content",
               "level": "A", "principle": "Perceivable", "guideline": "1.1"}]
    isolated_store.create_acr_report("rep-old", owner_email="o@acp.test",
                                     catalog_hash="x", criteria=legacy, metadata={})
    row = isolated_store.list_acr_criteria("rep-old", owner_email="o@acp.test")[0]
    assert row["requirement_set"] == acr_catalog.REQ_WCAG
    assert row["chapter"] is None


def test_the_508_edition_is_still_not_offerable_for_real():
    """The fixture above supplies availability; the module must not. If this ever fails without
    6.3 having landed, a 508 report can be created whose export prints no Section 508 rows."""
    assert acr_catalog.requirement_sets_available() == frozenset({acr_catalog.REQ_WCAG})
    assert acr_catalog.offerable_editions() == [acr_catalog.EDITION_WCAG]
