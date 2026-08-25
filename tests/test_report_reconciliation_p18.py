"""P-18 — Report-level reconciliation checks before rendering.

Validates that _reconciliation_checks catches inconsistencies and that
build_report renders an integrity warning when they are present.
"""
import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

from pypdf import PdfReader


def _flat(pdf: bytes) -> str:
    text = "".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(pdf)).pages)
    return re.sub(r"\s+", " ", text)


_META_GOOD = {"target": "WCAG 2.1 AA", "version": "3.1", "hash": "deadbeef1234abcd"}
_META_NO_HASH = {"target": "WCAG 2.1 AA", "version": "3.1", "hash": ""}
_RUN = {"id": "p18-001", "completed_at": "2026-08-24T12:00:00",
        "avg_score": 95, "owner_email": "ada@example.com"}
_FILES = [{"file": "doc.docx", "compliant": 1, "score": 95, "status": "pass", "issues": []}]
_FACTS_OK = {
    "documents": [{"file": "doc.docx", "evaluated": 10, "findings": 0,
                   "not_evaluated": 0, "remediated": 0, "remaining": 0,
                   "approvals": 0, "not_evaluated_criteria": [], "review_criteria": [],
                   "by_mode": {"auto": 10}}],
    "scope": {
        "catalog_size": 20,
        "by_mode": {"auto": 10},
        "not_evaluated_criteria": [],
        "review_criteria": [],
        "human_only_criteria": [],
        "formats_not_opened": [],
    },
    "remediated_total": 0,
    "approvals_total": 0,
    "review": {"reviewed": 0, "approved": 0, "rejected": 0, "skipped": 0},
}


# ── _reconciliation_checks unit tests ────────────────────────────────────────

def test_no_issues_when_data_consistent():
    """P-18: no discrepancies on clean, consistent inputs."""
    from report import _reconciliation_checks
    issues = _reconciliation_checks(_FILES, _FACTS_OK, _META_GOOD)
    assert issues == []


def test_missing_hash_flagged():
    """P-18: absent rubric hash produces a discrepancy."""
    from report import _reconciliation_checks
    issues = _reconciliation_checks(_FILES, _FACTS_OK, _META_NO_HASH)
    assert any("hash" in i.lower() for i in issues), issues


def test_orphan_facts_document_flagged():
    """P-18: a file in facts['documents'] that is not in the files list is flagged."""
    from report import _reconciliation_checks
    facts = {**_FACTS_OK, "documents": [
        {"file": "doc.docx", "evaluated": 10, "findings": 0,
         "not_evaluated": 0, "remediated": 0, "remaining": 0, "approvals": 0,
         "not_evaluated_criteria": [], "review_criteria": [], "by_mode": {}},
        {"file": "ghost.pdf", "evaluated": 5, "findings": 0,
         "not_evaluated": 0, "remediated": 0, "remaining": 0, "approvals": 0,
         "not_evaluated_criteria": [], "review_criteria": [], "by_mode": {}},
    ]}
    issues = _reconciliation_checks(_FILES, facts, _META_GOOD)
    assert any("ghost.pdf" in i for i in issues), issues


def test_catalog_overflow_flagged():
    """P-18: not_evaluated + human_only > catalog_size is flagged."""
    from report import _reconciliation_checks
    facts = {**_FACTS_OK, "scope": {
        **_FACTS_OK["scope"],
        "catalog_size": 4,  # 3 + 2 = 5 > 4 → impossible
        "not_evaluated_criteria": ["1.1.1", "1.2.1", "1.3.1"],
        "human_only_criteria": ["1.4.1", "1.4.3"],
    }}
    issues = _reconciliation_checks(_FILES, facts, _META_GOOD)
    assert any("catalog" in i.lower() or "catalog_size" in i for i in issues), issues


def test_review_arithmetic_flagged():
    """P-18: approved + rejected + skipped > reviewed is flagged."""
    from report import _reconciliation_checks
    facts = {**_FACTS_OK, "review": {
        "reviewed": 3, "approved": 2, "rejected": 2, "skipped": 1,
    }}
    issues = _reconciliation_checks(_FILES, facts, _META_GOOD)
    assert any("review" in i.lower() for i in issues), issues


def test_remediated_total_overflow_flagged():
    """P-18: remediated_total > len(files) is flagged."""
    from report import _reconciliation_checks
    facts = {**_FACTS_OK, "remediated_total": 99}
    issues = _reconciliation_checks(_FILES, facts, _META_GOOD)
    assert any("remediated" in i.lower() for i in issues), issues


# ── build_report integration tests ───────────────────────────────────────────

def test_no_integrity_warning_on_clean_inputs():
    """P-18: integrity warning box is absent when all checks pass."""
    from report import build_report
    t = _flat(build_report(_RUN, _FILES, _META_GOOD, facts=_FACTS_OK))
    assert "Report integrity" not in t


def test_integrity_warning_appears_on_bad_inputs():
    """P-18: integrity warning box appears when reconciliation fails."""
    from report import build_report
    t = _flat(build_report(_RUN, _FILES, _META_NO_HASH, facts=_FACTS_OK))
    assert "Report integrity" in t


def test_integrity_warning_still_produces_valid_pdf():
    """P-18: a PDF is still produced when reconciliation fails — warn, don't crash."""
    from report import build_report
    pdf = build_report(_RUN, _FILES, _META_NO_HASH, facts=_FACTS_OK)
    assert pdf[:5] == b"%PDF-"
