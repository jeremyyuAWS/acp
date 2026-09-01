"""config/wcag-2.2-aa.json — the ACR's applicable-criteria catalog (ADR 0047).

WHY THE COUNTS ARE PINNED HERE. The catalog is the denominator of the whole report: every
criterion in it is one a human must decide before publication, and one that appears in the
exported conformance table. A criterion silently missing from it is a criterion nobody is ever
asked about — no error, no gap, just a shorter report that reads as complete. That failure is
invisible at every stage until a customer's procurement reviewer finds it, so the shape of the
catalog is asserted rather than trusted.

The numbers below were DERIVED by parsing the W3C Recommendation (scripts/gen_wcag_catalog.py),
not recalled. They are pinned so that a regeneration that quietly produces a different set has to
be looked at by a person.
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

CATALOG_PATH = ACP / "config" / "wcag-2.2-aa.json"


def test_the_catalog_is_wcag_22_level_a_and_aa():
    m = acr_catalog.meta()
    assert m["standard"] == "WCAG"
    assert m["version"] == "2.2"
    assert m["levels"] == ["A", "AA"]
    assert m["source"] == "https://www.w3.org/TR/WCAG22/"


def test_the_criteria_count_and_level_split_are_exactly_what_the_spec_says():
    """55 = 31 Level A + 24 Level AA, after 4.1.1 Parsing was made obsolete in 2.2.

    A regeneration that changes any of these three numbers is either a real spec change (rare,
    and worth a human reading it) or a parser regression (likely, and worth catching here).
    """
    criteria = acr_catalog.criteria()
    assert len(criteria) == 55
    levels = {}
    for row in criteria:
        levels[row["level"]] = levels.get(row["level"], 0) + 1
    assert levels == {"A": 31, "AA": 24}
    assert acr_catalog.meta()["criteria_count"] == 55


def test_4_1_1_parsing_is_not_in_the_catalog():
    """Obsolete in WCAG 2.2. Its presence would mean the catalog was built from a 2.1 document —
    and every criterion in the catalog is one a human is required to decide, so an obsolete one
    is work nobody should ever be asked to do."""
    assert acr_catalog.criterion("4.1.1") is None
    assert "4.1.1" not in acr_catalog.numbers()


@pytest.mark.parametrize("num,level", [
    ("2.4.11", "AA"),   # Focus Not Obscured (Minimum)
    ("2.5.7", "AA"),    # Dragging Movements
    ("2.5.8", "AA"),    # Target Size (Minimum)
    ("3.2.6", "A"),     # Consistent Help
    ("3.3.7", "A"),     # Redundant Entry
    ("3.3.8", "AA"),    # Accessible Authentication (Minimum)
])
def test_the_criteria_wcag_22_added_are_present_at_the_right_level(num, level):
    """The 2.2 delta. If the catalog were built from WCAG 2.1 by mistake it would look entirely
    reasonable — same structure, plausible count — and these six would simply be absent."""
    row = acr_catalog.criterion(num)
    assert row is not None, f"{num} is missing — the catalog may have been built from WCAG 2.1"
    assert row["level"] == level


def test_every_criterion_carries_its_principle_and_guideline():
    """Needed for the VPAT table's grouping. A criterion with no principle sorts into a nameless
    bucket in the export rather than failing, which is why it is checked here."""
    for row in acr_catalog.criteria():
        assert row["principle"] in ("Perceivable", "Operable", "Understandable", "Robust"), row
        assert row["guideline"], row
        assert row["name"], row


def test_the_catalog_hash_is_stable_across_reordering_and_meta_edits():
    """A report stamps this hash at creation and a snapshot freezes it, so a published ACR stays
    interpretable after the catalog advances. It must therefore identify the SET OF CRITERIA, not
    the file's bytes — otherwise reformatting the JSON would orphan every existing report."""
    import hashlib

    raw = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    baseline = acr_catalog.catalog_hash()

    def _hash(criteria):
        payload = json.dumps(sorted(criteria, key=lambda r: r["num"]),
                             sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    assert _hash(raw["criteria"]) == baseline
    assert _hash(list(reversed(raw["criteria"]))) == baseline, "hash depends on ordering"
    # …but it MUST change when a criterion changes, or it cannot detect catalog drift at all.
    mutated = [dict(r) for r in raw["criteria"]]
    mutated[0]["level"] = "AAA"
    assert _hash(mutated) != baseline, "hash is insensitive to a criterion's content"


def test_the_generator_and_the_runtime_agree_about_the_hash():
    """Two implementations of one fact is how the stamped hash and the checked hash drift apart.
    They are kept byte-identical; this is what notices if one is edited alone."""
    import gen_wcag_catalog

    raw = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    assert gen_wcag_catalog.catalog_hash(raw) == acr_catalog.catalog_hash()


def test_a_new_report_matrix_covers_every_criterion_and_starts_unevaluated():
    """PRD §21.2 — the system creates the COMPLETE applicable criteria matrix. And PRD §10: every
    row starts in the internal not-evaluated state, which blocks publication until a human acts."""
    matrix = acr_catalog.build_matrix("rep1")
    assert len(matrix) == 55
    assert {r["criterion_num"] for r in matrix} == set(acr_catalog.numbers())
    for row in matrix:
        assert row["workflow_state"] == acr_catalog.NOT_EVALUATED
        assert row["final_status"] is None
        assert row["draft_status"] is None
        assert row["approval_state"] == "unapproved"
        assert row["applicable"] is True


def test_the_vpat_vocabulary_is_exactly_four_terms():
    """PRD §9: "Do not invent additional final statuses." The internal workflow states are a
    DISJOINT set — if they ever overlap, an internal state can be exported as a conformance
    level, which is the failure the two-column design exists to prevent."""
    assert acr_catalog.FINAL_STATUSES == {
        "Supports", "Partially Supports", "Does Not Support", "Not Applicable"}
    assert acr_catalog.WORKFLOW_STATES.isdisjoint(acr_catalog.FINAL_STATUSES)
    assert acr_catalog.REMARKS_REQUIRED < acr_catalog.FINAL_STATUSES
    assert "Supports" not in acr_catalog.REMARKS_REQUIRED
