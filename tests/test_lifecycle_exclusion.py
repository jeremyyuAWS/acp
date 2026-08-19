"""Pure unit tests for wcag_codeset.lifecycle_exclusion — the archival/deletion count the Assess
scope preview shows (Deva #6 / Discover-Assess PRD §4.5). No HTTP and no control-plane import: the
projection over per-file inventory rows is exercised directly, so it needs only the light `store`
constant and `wcag_codeset`/`estate_inventory`.
"""
from __future__ import annotations

import sys
from pathlib import Path

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import store                      # noqa: E402 — after sys.path insert
import wcag_codeset              # noqa: E402

# The store is the single authority for the flagged set; the projection just consumes it.
EXCLUDED = store.Store.LIFECYCLE_EXCLUDED_DEFAULT   # Archive/Delete Candidate, Archived, Deleted


def _row(file, status="Active", mime=""):
    return {"file": file, "mime": mime, "lifecycle_status": status}


def test_no_excluded_statuses_is_zeros():
    # With an empty flagged set nothing can be excluded — the caller passed no statuses.
    out = wcag_codeset.lifecycle_exclusion([_row("a.docx", "Archived")], None, ())
    assert out == {"lifecycle_excluded": 0, "lifecycle_eligible_excluded": 0}


def test_counts_flagged_total_and_eligible_subset():
    rows = [
        _row("keep.docx", "Active"),                       # not flagged
        _row("old.pdf", "Archive Candidate"),              # flagged, assessable format
        _row("gone.pptx", "Delete Candidate"),             # flagged, assessable format
        _row("dead.xlsx", "Deleted"),                      # flagged, assessable format
        _row("logo.png", "Archived", mime="image/png"),    # flagged, NOT an assessable format
    ]
    out = wcag_codeset.lifecycle_exclusion(rows, None, EXCLUDED)   # default = Core 17
    assert out["lifecycle_excluded"] == 4                  # every flagged file, image included
    assert out["lifecycle_eligible_excluded"] == 3         # the image was never assessable anyway


def test_missing_or_null_status_reads_as_active():
    rows = [{"file": "a.docx"}, {"file": "b.pdf", "lifecycle_status": None}]
    out = wcag_codeset.lifecycle_exclusion(rows, None, EXCLUDED)
    assert out == {"lifecycle_excluded": 0, "lifecycle_eligible_excluded": 0}


def test_subset_codes_narrow_the_eligible_exclusion():
    # 2.1.1 Keyboard has only a pptx lane, so a flagged docx counts to the total but not to the
    # eligible exclusion for this code-set; a flagged pptx counts to both.
    rows = [_row("old.docx", "Archived"), _row("deck.pptx", "Delete Candidate")]
    out = wcag_codeset.lifecycle_exclusion(rows, ["2.1.1"], EXCLUDED)
    assert out["lifecycle_excluded"] == 2
    assert out["lifecycle_eligible_excluded"] == 1


def test_empty_rows_is_zeros():
    for empty in (None, []):
        out = wcag_codeset.lifecycle_exclusion(empty, None, EXCLUDED)
        assert out == {"lifecycle_excluded": 0, "lifecycle_eligible_excluded": 0}
