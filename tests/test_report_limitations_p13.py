"""P-13 — Material-limitations notice in the PDF report.

Three classes of limitation, each only when the scan state warrants it:
  1. Files that couldn't be analysed (error status) — named individually.
  2. Review-recommended criteria — count + names surfaced prominently.
  3. Owner/author metadata absent — noted when owner_email is absent.

The section must:
  - never render when none of the three apply (no boilerplate)
  - always be driven by real scan state, not static text
  - appear before the outcome stat band (near the executive summary)
"""
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

_RUN_WITH_OWNER = {"id": "s-p13", "completed_at": "2026-08-24T00:00:00", "avg_score": 90,
                   "owner_email": "ada@example.com"}
_RUN_NO_OWNER = {**_RUN_WITH_OWNER, "owner_email": None}
_META = {"target": "AA", "version": "1.2", "hash": "abc"}
_FILES_OK = [{"file": "ok.docx", "compliant": 1, "score": 100, "status": "pass", "issues": []}]
_FILES_ERR = [
    {"file": "ok.docx", "compliant": 1, "score": 100, "status": "pass", "issues": []},
    {"file": "locked.pdf", "compliant": 0, "score": None, "status": "error", "issues": []},
    {"file": "corrupt.docx", "compliant": 0, "score": None, "status": "error", "issues": []},
]


def _flat(pdf: bytes) -> str:
    import re
    from pypdf import PdfReader
    text = "".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(pdf)).pages)
    return re.sub(r"\s+", " ", text)


def _facts_with_review(review_criteria=None):
    return {
        "documents": [{"file": "ok.docx", "evaluated": 10, "findings": 0, "not_evaluated": 5,
                        "remediated": 0, "remaining": 0, "approvals": 0,
                        "not_evaluated_criteria": [], "review_criteria": [],
                        "by_mode": {"auto": 10}}],
        "scope": {
            "catalog_size": 15,
            "by_mode": {"auto": 10},
            "not_evaluated_criteria": [],
            "review_criteria": review_criteria or [],
            "human_only_criteria": [],
            "formats_not_opened": [],
        },
        "remediated_total": 0,
        "approvals_total": 0,
        "review": {"reviewed": 0, "approved": 0, "rejected": 0, "skipped": 0},
    }


# ── Section does not render boilerplate ───────────────────────────────────────

def test_no_limitations_section_when_no_limitations():
    """P-13: the notice is absent when no material limitations apply."""
    from report import build_report
    t = _flat(build_report(_RUN_WITH_OWNER, _FILES_OK, _META, facts=_facts_with_review()))
    assert "Material Limitations" not in t


# ── Unanalysable files ────────────────────────────────────────────────────────

def test_failed_files_named_in_limitations():
    """P-13: files with error status are named individually in the notice."""
    from report import build_report
    t = _flat(build_report(_RUN_WITH_OWNER, _FILES_ERR, _META, facts=_facts_with_review()))
    assert "Material Limitations" in t
    assert "locked.pdf" in t
    assert "corrupt.docx" in t


def test_failed_file_count_in_limitations():
    """P-13: the count of failed files is shown next to their names."""
    from report import build_report
    t = _flat(build_report(_RUN_WITH_OWNER, _FILES_ERR, _META, facts=_facts_with_review()))
    assert "2" in t and "could not be opened" in t


# ── Review-recommended criteria ───────────────────────────────────────────────

def test_review_criteria_named_in_limitations():
    """P-13: review-recommended criteria appear with their SC id and name."""
    from report import build_report
    review = [{"sc": "1.1.1", "name": "Non-text Content"},
              {"sc": "1.4.3", "name": "Contrast (Minimum)"}]
    t = _flat(build_report(_RUN_WITH_OWNER, _FILES_OK, _META,
                           facts=_facts_with_review(review_criteria=review)))
    assert "Material Limitations" in t
    assert "review-recommended" in t
    assert "1.1.1" in t and "Non-text Content" in t
    assert "1.4.3" in t and "Contrast" in t


def test_no_review_clause_when_no_review_criteria():
    """P-13: no 'review-recommended' clause appears when the list is empty."""
    from report import build_report
    t = _flat(build_report(_RUN_WITH_OWNER, _FILES_ERR, _META, facts=_facts_with_review()))
    assert "review-recommended" not in t


# ── Owner metadata ────────────────────────────────────────────────────────────

def test_missing_owner_noted_in_limitations():
    """P-13: absence of owner_email is flagged as a material limitation."""
    from report import build_report
    t = _flat(build_report(_RUN_NO_OWNER, _FILES_OK, _META, facts=_facts_with_review()))
    assert "Material Limitations" in t
    assert "Owner" in t and "metadata" in t


def test_owner_clause_absent_when_owner_present():
    """P-13: owner clause is omitted when owner_email is set."""
    from report import build_report
    t = _flat(build_report(_RUN_WITH_OWNER, _FILES_OK, _META, facts=_facts_with_review()))
    assert "Material Limitations" not in t


# ── Multiple limitations combine ──────────────────────────────────────────────

def test_multiple_limitations_all_appear():
    """P-13: all applicable limitations render in one notice block."""
    from report import build_report
    review = [{"sc": "1.1.1", "name": "Non-text Content"}]
    t = _flat(build_report(_RUN_NO_OWNER, _FILES_ERR, _META,
                           facts=_facts_with_review(review_criteria=review)))
    assert "locked.pdf" in t
    assert "review-recommended" in t
    assert "Owner" in t and "metadata" in t


# ── Positioning ───────────────────────────────────────────────────────────────

def test_limitations_appears_before_outcome_summary():
    """P-13: the notice is near the executive summary, before the stat band."""
    from report import build_report
    review = [{"sc": "1.1.1", "name": "Non-text Content"}]
    t = _flat(build_report(_RUN_WITH_OWNER, _FILES_OK, _META,
                           facts=_facts_with_review(review_criteria=review)))
    assert t.index("Material Limitations") < t.index("Outcome summary")
