"""P-14: stable finding identifiers.

_finding_id() must be deterministic, stable across renders, and exposed in the evidence
section headings so auditors can cross-reference findings across exports.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

_RUN = {"id": "s1", "completed_at": "2026-08-24T10:00:00",
        "started_at": "2026-08-24T09:00:00", "avg_score": 90, "source": "drive"}
_META = {"target": "WCAG 2.1 AA", "version": "2", "hash": "deadbeef1234"}


# ── _finding_id unit tests ─────────────────────────────────────────────────────

def test_finding_id_is_deterministic():
    """Same inputs always produce the same ID."""
    from report import _finding_id
    assert _finding_id("a.pdf", "1.1.1 Non-text Content", "img1") == \
           _finding_id("a.pdf", "1.1.1 Non-text Content", "img1")


def test_finding_id_is_eight_chars():
    """ID is always exactly 8 hex characters."""
    from report import _finding_id
    fid = _finding_id("doc.docx", "1.4.3 Contrast (Minimum)", "")
    assert len(fid) == 8
    assert all(c in "0123456789abcdef" for c in fid)


def test_finding_id_differs_by_criterion():
    """Different criterion → different ID (same file, same location)."""
    from report import _finding_id
    id1 = _finding_id("a.pdf", "1.1.1 Non-text Content", "p1")
    id2 = _finding_id("a.pdf", "1.4.3 Contrast (Minimum)", "p1")
    assert id1 != id2


def test_finding_id_differs_by_file():
    """Different file → different ID (same criterion, same location)."""
    from report import _finding_id
    id1 = _finding_id("a.pdf", "1.1.1 Non-text Content", "img1")
    id2 = _finding_id("b.pdf", "1.1.1 Non-text Content", "img1")
    assert id1 != id2


def test_finding_id_differs_by_location():
    """Different location → different ID (same file, same criterion)."""
    from report import _finding_id
    id1 = _finding_id("a.pdf", "1.1.1 Non-text Content", "img1")
    id2 = _finding_id("a.pdf", "1.1.1 Non-text Content", "img2")
    assert id1 != id2


def test_finding_id_stable_without_location():
    """Empty/omitted location still produces a stable ID."""
    from report import _finding_id
    assert _finding_id("a.pdf", "1.1.1 Non-text Content") == \
           _finding_id("a.pdf", "1.1.1 Non-text Content", "")


# ── build_report renders valid PDF with evidence containing IDs ────────────────

def _mk_file(name, status="done", compliant=1, score=90, issues=None):
    return {"file": name, "status": status, "compliant": compliant,
            "score": score, "skipped_rules": 0, "issues": issues or []}


def test_p14_pdf_renders_with_applied_evidence():
    """build_report returns valid PDF when evidence with applied fixes is present."""
    from report import build_report
    files = [_mk_file("a.pdf", compliant=1, score=95)]
    evidence = [{
        "file": "a.pdf",
        "applied": [{
            "criterion": "1.1.1 Non-text Content",
            "before": "decorative image",
            "after": 'alt=""',
            "value": None,
            "source": None,
            "note": None,
            "decision": None,
            "reviewer": None,
            "reviewed_at": None,
            "thumb": None,
            "validated": True,
        }],
        "proposed": [],
    }]
    pdf = build_report(_RUN, files, _META, evidence=evidence)
    assert pdf[:5] == b"%PDF-"


def test_p14_pdf_renders_with_proposed_evidence():
    """build_report returns valid PDF when evidence with proposed (not applied) items present."""
    from report import build_report
    files = [_mk_file("b.docx", compliant=0, score=60,
                      issues=[{"wcag": "1.4.3", "ruleId": "r1", "severity": "MINOR",
                               "detail": "low contrast"}])]
    evidence = [{
        "file": "b.docx",
        "applied": [],
        "proposed": [{
            "criterion": "1.4.3 Contrast (Minimum)",
            "validated": False,
            "proposals": [{"proposed_value": "use #595959", "rationale": "passes 4.5:1",
                           "source": "ai", "why_review": "colour judgment"}],
        }],
    }]
    pdf = build_report(_RUN, files, _META, evidence=evidence)
    assert pdf[:5] == b"%PDF-"
