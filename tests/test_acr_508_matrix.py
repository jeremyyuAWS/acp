"""Phase 6.2 — a matrix row says which requirement set it came from, and a 508 edition gets 508 rows.

#1532 found a report that declared the Section 508 edition and contained none of Section 508:
`build_matrix` took only `report_id` and read the WCAG catalog, so `template.edition` said one
thing and the 120 missing rows said another. It closed that by refusing the edition. 6.1 landed
the requirements. This is the builder that can actually produce them.

6.3 OPENED THE GATE, so the fixture that used to supply availability is gone: a 508 report is
created through the API now, and these tests exercise the real builder rather than a patched one.
What stays is the refusal — `build_matrix` still raises for an edition whose requirement sets this
build cannot supply, which is the EU and INT editions until EN 301 549 has a catalog.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import acr_catalog  # noqa: E402


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


def test_a_508_edition_carries_both_requirement_sets():
    matrix = acr_catalog.build_matrix("rep508", acr_catalog.EDITION_508)
    by_set: dict[str, int] = {}
    for row in matrix:
        by_set[row["requirement_set"]] = by_set.get(row["requirement_set"], 0) + 1
    assert by_set == {acr_catalog.REQ_WCAG: 55, acr_catalog.REQ_SECTION_508: 120}
    assert len(matrix) == 175


def test_508_rows_carry_a_chapter_and_no_wcag_axes():
    """The whole point of the column. A 508 row that carried a level would render inside a WCAG
    conformance table, which is the false-claim shape #1532 fixed arriving by another route."""
    rows = [r for r in acr_catalog.build_matrix("rep508", acr_catalog.EDITION_508)
            if r["requirement_set"] == acr_catalog.REQ_SECTION_508]
    assert {r["chapter"] for r in rows} == {"3", "4", "5", "6"}
    assert all(r["level"] is None for r in rows)
    assert all(r["principle"] is None for r in rows)
    assert all(r["guideline"] is None for r in rows)


def test_508_rows_start_unevaluated_like_every_other_row():
    """PRD §10 — publication is blocked while an applicable row is unevaluated, and a 508 row is
    not exempt from that just because it arrived from a different catalog."""
    rows = [r for r in acr_catalog.build_matrix("rep508", acr_catalog.EDITION_508)
            if r["requirement_set"] == acr_catalog.REQ_SECTION_508]
    assert all(r["workflow_state"] == acr_catalog.NOT_EVALUATED for r in rows)
    assert all(r["final_status"] is None for r in rows)
    assert all(r["applicable"] is True for r in rows)
    assert all(r["approval_state"] == "unapproved" for r in rows)


def test_hardware_is_not_quietly_dropped():
    """69 of the 120 rows are Chapter 4, and for a hosted web application every one of them ends
    Not Applicable. Applicability is a human decision with required remarks (PRD §10), so the
    builder does not pre-empt it — the cost is a bulk-mark affordance owed to the UI, not a
    chapter this function omits."""
    rows = [r for r in acr_catalog.build_matrix("rep508", acr_catalog.EDITION_508)
            if r["chapter"] == "4"]
    assert len(rows) == 69
    assert all(r["applicable"] is True for r in rows)


def test_numbers_do_not_collide_between_the_two_catalogs():
    """criterion_num is half the primary key. A WCAG number ("1.4.3") and a 508 number ("402.2.1")
    must never be the same string, or one row would silently overwrite the other on insert."""
    matrix = acr_catalog.build_matrix("rep508", acr_catalog.EDITION_508)
    nums = [r["criterion_num"] for r in matrix]
    assert len(nums) == len(set(nums))


def test_an_edition_this_build_cannot_supply_is_refused(monkeypatch):
    """The layer below the routes, for the reason #1532 gave: a report restored, imported or
    migrated never passed them. Every edition is supplied in the committed tree now, so the
    refusal is exercised against an arranged absence — the guard has to keep working for the next
    standard, and for a deployment missing a catalog file."""
    monkeypatch.setattr(acr_catalog, "requirement_sets_available",
                        lambda: frozenset({acr_catalog.REQ_WCAG, acr_catalog.REQ_SECTION_508}))
    with pytest.raises(ValueError) as e:
        acr_catalog.build_matrix("repeu", acr_catalog.EDITION_EU)
    assert "EN 301 549" in str(e.value)
    assert "false claim" in str(e.value)


def test_a_refusal_names_only_what_is_actually_missing(monkeypatch):
    """INT obliges all three sets. With two supplied, naming the supplied ones would send the
    author looking for a catalog that is already there."""
    monkeypatch.setattr(acr_catalog, "requirement_sets_available",
                        lambda: frozenset({acr_catalog.REQ_WCAG, acr_catalog.REQ_SECTION_508}))
    with pytest.raises(ValueError) as e:
        acr_catalog.build_matrix("repint", acr_catalog.EDITION_INT)
    assert "EN 301 549" in str(e.value)
    assert "Section 508" not in str(e.value), "naming a set that IS supplied misdirects the author"


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


def test_the_508_edition_is_offerable_for_real():
    """Held shut through 6.1 and 6.2, opened by 6.3 when the exports could print the rows. The EU
    and INT editions joined it in 6.4; this test is about 508 keeping its place in the list."""
    available = acr_catalog.requirement_sets_available()
    assert {acr_catalog.REQ_WCAG, acr_catalog.REQ_SECTION_508} <= available
    assert acr_catalog.offerable_editions()[:2] == [
        acr_catalog.EDITION_WCAG, acr_catalog.EDITION_508]
