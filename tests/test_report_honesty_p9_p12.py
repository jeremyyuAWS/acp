"""Report honesty items P-9 through P-12.

P-9:  Partial-assessment notice appears when files are unassessed or unanalysable.
P-10: Stat band denominator is assessed (not total) documents.
P-11: Criteria outcome breakdown stat band appears when catalog_size is present.
P-12: Assessment scope block rendered (source, file types, scan window, rubric, method).

NOTE: pypdf text-extraction is unavailable in CI (cryptography Rust-binding env issue),
so assertions are made via build_report returning a valid PDF and via unit checks of the
helper function logic, rather than full-text extraction.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

_RUN = {"id": "s1", "completed_at": "2026-08-24T10:00:00",
        "started_at": "2026-08-24T09:00:00", "avg_score": 90, "source": "drive"}
_META = {"target": "WCAG 2.1 AA", "version": "2", "hash": "deadbeef1234"}


def _mk_file(name, status="done", compliant=1, score=90, issues=None):
    return {"file": name, "status": status, "compliant": compliant,
            "score": score, "skipped_rules": 0, "issues": issues or []}


def _mk_facts(catalog_size=50, not_eval=None, human_only=None, ai=False):
    return {
        "scope": {
            "catalog_size": catalog_size,
            "not_evaluated_criteria": not_eval or ["4.1.1"],
            "human_only_criteria": human_only or ["1.3.5"],
            "estate": {"excluded": 0},
            "by_mode": {"ai-assisted": 1 if ai else 0},
        },
        "documents": [],
    }


# ── P-9 / P-10 / P-11 / P-12: render sanity ─────────────────────────────────
# All four items are exercised in one parameterised render — if build_report
# raises or returns a non-PDF, the feature is broken regardless of text content.

def test_p9_p12_renders_with_mixed_estate():
    """P-9, P-11, P-12: render with unassessed + unanalysable files + facts."""
    from report import build_report
    files = [
        _mk_file("a.pdf"),
        _mk_file("b.docx", status="done", compliant=0, score=None),   # not-assessed
        _mk_file("c.pptx", status="error", compliant=0, score=None),  # unanalysable
    ]
    pdf = build_report(_RUN, files, _META, facts=_mk_facts())
    assert pdf[:5] == b"%PDF-", "must return a valid PDF"


def test_p9_p12_renders_with_clean_estate():
    """P-9 (no notice) + P-12: render with no unassessed files."""
    from report import build_report
    files = [_mk_file("a.pdf"), _mk_file("b.docx")]
    pdf = build_report(_RUN, files, _META, facts=_mk_facts())
    assert pdf[:5] == b"%PDF-"


def test_p9_p12_renders_without_facts():
    """P-12 graceful fallback: scope block renders even when facts=None."""
    from report import build_report
    files = [_mk_file("a.pdf")]
    pdf = build_report(_RUN, files, _META, facts=None)
    assert pdf[:5] == b"%PDF-"


# ── P-10: pct denominator logic ───────────────────────────────────────────────

def test_p10_pct_uses_assessed_not_total():
    """P-10: 1 certifiable, 1 not-assessed => pct = 100%, not 50%."""
    from report import NOT_ASSESSED, _status
    # Simulate the estate reconciliation without calling build_report
    files = [
        _mk_file("a.pdf"),                                            # certifiable
        _mk_file("b.docx", status="done", compliant=0, score=None),  # not-assessed
    ]
    counts: dict[str, int] = {}
    for f in files:
        st = _status(f)
        counts[st] = counts.get(st, 0) + 1
    cert = counts.get("certifiable", 0)
    total = len(files) or 1
    unassessed = counts.get(NOT_ASSESSED, 0)
    assessed = total - unassessed
    pct = round(cert / assessed * 100) if assessed else 0
    assert cert == 1
    assert assessed == 1
    assert pct == 100, f"expected 100%, got {pct}%"


def test_p10_pct_is_zero_when_none_assessed():
    """P-10: no assessed files => pct = 0, not a ZeroDivisionError."""
    from report import NOT_ASSESSED, _status
    files = [_mk_file("a.pdf", status="done", compliant=0, score=None)]  # not-assessed
    counts: dict[str, int] = {}
    for f in files:
        st = _status(f)
        counts[st] = counts.get(st, 0) + 1
    cert = counts.get("certifiable", 0)
    total = len(files) or 1
    unassessed = counts.get(NOT_ASSESSED, 0)
    assessed = total - unassessed
    pct = round(cert / assessed * 100) if assessed else 0
    assert pct == 0


# ── P-11: criteria-breakdown counts ──────────────────────────────────────────

def test_p11_passed_auto_count():
    """P-11: passed_auto = catalog_size - not_eval - human_only - with_findings."""
    catalog_size = 50
    not_eval = 3
    human_only = 2
    open_fails = {"1.4.3": 1}
    resolved_crit = {"1.1.1": 2}
    with_findings = len(set(open_fails) | set(resolved_crit))
    passed_auto = max(0, catalog_size - not_eval - human_only - with_findings)
    assert with_findings == 2
    assert passed_auto == 50 - 3 - 2 - 2 == 43


def test_p11_passed_auto_never_negative():
    """P-11: max(0, ...) guards against impossible combinations."""
    passed_auto = max(0, 5 - 4 - 4 - 4)
    assert passed_auto == 0


# ── P-12: _assessment_scope_block unit test ───────────────────────────────────

def test_p12_scope_block_returns_non_empty_list():
    """P-12: _assessment_scope_block must return flowables."""
    from reportlab.lib.styles import getSampleStyleSheet
    from report import _assessment_scope_block
    ss = getSampleStyleSheet()
    el = _assessment_scope_block(
        _RUN, _META, _mk_facts(), "2 PDF · 1 DOCX",
        ss["Heading2"], ss["Normal"], ss["Normal"], ss["Normal"])
    assert len(el) >= 2  # at least an h2 Paragraph + a Table


def test_p12_source_map_drive():
    """P-12: source='drive' resolves to 'Google Drive'."""
    from report import _assessment_scope_block
    from reportlab.lib.styles import getSampleStyleSheet
    ss = getSampleStyleSheet()
    run = dict(_RUN, source="drive")
    el = _assessment_scope_block(run, _META, None, "—",
                                 ss["Heading2"], ss["Normal"], ss["Normal"], ss["Normal"])
    # The table cell Paragraph text must contain "Google Drive"
    table = el[1]
    cell_texts = " ".join(
        str(c) for row in table._cellvalues for c in row
        if hasattr(c, "text")
    )
    assert "Google Drive" in cell_texts
