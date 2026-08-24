"""P-17 — Improved evidence presentation.

_evidence_section() emits location/page/element, expected condition,
evidence-collection timestamp, confidence, explicit redaction markers,
and truncation notices when the relevant fields are present in an
evidence entry.
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


_RUN = {"id": "p17-001", "completed_at": "2026-08-24T12:00:00",
        "avg_score": 88, "owner_email": "ada@example.com"}
_META = {"target": "WCAG 2.1 AA", "version": "3.1", "hash": "deadbeef1234abcd"}
_FACTS_EMPTY = {
    "documents": [],
    "scope": {"catalog_size": 10, "by_mode": {"auto": 10},
              "not_evaluated_criteria": [], "review_criteria": [],
              "human_only_criteria": [], "formats_not_opened": []},
    "remediated_total": 0, "approvals_total": 0,
    "review": {"reviewed": 0, "approved": 0, "rejected": 0, "skipped": 0},
}


def _make_evidence(extra_fields: dict) -> list:
    """Return a minimal applied-evidence entry with extra_fields merged in."""
    entry = {
        "criterion": "1.1.1 Non-text Content",
        "before": "img without alt",
        "after": 'img alt="Chart showing Q2 revenue"',
    }
    entry.update(extra_fields)
    return [{"file": "doc.docx",
             "applied": [entry],
             "proposed": []}]


def _build(evidence):
    from report import build_report
    files = [{"file": "doc.docx", "compliant": 1, "score": 100,
              "status": "pass", "remediated_at": "2026-08-24T10:00:00",
              "issues": []}]
    return _flat(build_report(_RUN, files, _META, facts=_FACTS_EMPTY,
                              evidence=evidence))


# ── location ──────────────────────────────────────────────────────────────────

def test_location_field_appears():
    t = _build(_make_evidence({"location": "Section 3 header"}))
    assert "Location" in t
    assert "Section 3 header" in t


def test_page_field_appears():
    t = _build(_make_evidence({"page": 7}))
    assert "page 7" in t


def test_element_field_appears():
    t = _build(_make_evidence({"element": "#hero-img"}))
    assert "element #hero-img" in t


def test_location_page_element_combined():
    t = _build(_make_evidence({"location": "body", "page": 2, "element": "img.logo"}))
    assert "body" in t
    assert "page 2" in t
    assert "element img.logo" in t


def test_no_location_when_absent():
    t = _build(_make_evidence({}))
    assert "Location" not in t


# ── expected condition ────────────────────────────────────────────────────────

def test_expected_field_appears():
    t = _build(_make_evidence({"expected": "All non-text content must have a text alternative"}))
    assert "Expected" in t
    assert "All non-text content must have a text alternative" in t


def test_no_expected_when_absent():
    t = _build(_make_evidence({}))
    assert "Expected" not in t


# ── evidence-collection timestamp ────────────────────────────────────────────

def test_collected_at_iso_appears():
    t = _build(_make_evidence({"collected_at": "2026-08-24T09:15:00"}))
    assert "Collected" in t
    assert "2026-08-24 09:15:00" in t


def test_collected_at_utc_label():
    t = _build(_make_evidence({"collected_at": "2026-08-24T09:15:00Z"}))
    assert "UTC" in t


def test_no_collected_when_absent():
    t = _build(_make_evidence({}))
    assert "Collected" not in t


# ── confidence ────────────────────────────────────────────────────────────────

def test_confidence_numeric_appears():
    t = _build(_make_evidence({"confidence": 0.97}))
    assert "Confidence" in t
    assert "0.97" in t


def test_confidence_label_appears():
    t = _build(_make_evidence({"confidence": "high"}))
    assert "Confidence" in t
    assert "high" in t


def test_no_confidence_when_absent():
    t = _build(_make_evidence({}))
    assert "Confidence" not in t


# ── redaction markers ─────────────────────────────────────────────────────────

def test_redacted_before_shows_label():
    t = _build(_make_evidence({"before": "[REDACTED]"}))
    assert "[redacted]" in t.lower()


def test_redacted_after_shows_label():
    t = _build(_make_evidence({"after": "[REDACTED]"}))
    assert "[redacted]" in t.lower()


def test_none_before_shows_dash():
    """None before is 'not available', not 'redacted' — rendered as em-dash."""
    t = _build(_make_evidence({"before": None}))
    assert "—" in t


# ── truncation notice ─────────────────────────────────────────────────────────

def test_long_before_shows_truncation_notice():
    t = _build(_make_evidence({"before": "x" * 2500}))
    assert "truncated" in t.lower()


def test_long_after_shows_truncation_notice():
    t = _build(_make_evidence({"after": "y" * 2500}))
    assert "truncated" in t.lower()


def test_short_value_no_truncation_notice():
    t = _build(_make_evidence({"before": "short text", "after": "fixed text"}))
    assert "truncated" not in t.lower()


# ── valid PDF with all new fields at once ─────────────────────────────────────

def test_pdf_valid_with_all_p17_fields():
    evidence = _make_evidence({
        "location": "page header",
        "page": 1,
        "element": "h1",
        "expected": "Images must have descriptive alt text",
        "collected_at": "2026-08-24T08:00:00",
        "confidence": "high",
    })
    from report import build_report
    files = [{"file": "doc.docx", "compliant": 1, "score": 100,
              "status": "pass", "remediated_at": "2026-08-24T10:00:00",
              "issues": []}]
    pdf = build_report(_RUN, files, _META, facts=_FACTS_EMPTY, evidence=evidence)
    assert pdf[:5] == b"%PDF-"
