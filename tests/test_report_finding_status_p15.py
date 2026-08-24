"""P-15 — Per-finding status with seven named states.

_finding_status() derives the correct label from issue fields and the file's
certifiable flag. The file inventory 'Findings' cell shows a per-finding
breakdown rather than collapsing to a single coarse label.
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


# ── _finding_status unit tests ────────────────────────────────────────────────

def test_plain_issue_on_non_certifiable_file_is_open():
    from report import _finding_status
    assert _finding_status({}, False) == "Open"


def test_plain_issue_on_certifiable_file_is_verified_resolved():
    from report import _finding_status
    assert _finding_status({}, True) == "Verified resolved"


def test_explicit_status_open():
    from report import _finding_status
    assert _finding_status({"status": "open"}, True) == "Open"


def test_explicit_status_remediation_attempted():
    from report import _finding_status
    assert _finding_status({"status": "remediation_attempted"}, False) == "Remediation attempted"


def test_explicit_status_awaiting_rescan():
    from report import _finding_status
    assert _finding_status({"status": "awaiting_rescan"}, True) == "Awaiting re-scan"


def test_explicit_status_verified_resolved():
    from report import _finding_status
    assert _finding_status({"status": "verified_resolved"}, False) == "Verified resolved"


def test_explicit_status_accepted_exception():
    from report import _finding_status
    assert _finding_status({"status": "accepted_exception"}, False) == "Accepted exception"


def test_explicit_status_false_positive():
    from report import _finding_status
    assert _finding_status({"status": "false_positive"}, False) == "False positive"


def test_explicit_status_reopened():
    from report import _finding_status
    assert _finding_status({"status": "reopened"}, False) == "Reopened"


def test_flag_false_positive():
    from report import _finding_status
    assert _finding_status({"false_positive": True}, False) == "False positive"


def test_flag_fp():
    from report import _finding_status
    assert _finding_status({"fp": True}, False) == "False positive"


def test_flag_accepted_exception():
    from report import _finding_status
    assert _finding_status({"accepted_exception": True}, False) == "Accepted exception"


def test_flag_exception():
    from report import _finding_status
    assert _finding_status({"exception": True}, False) == "Accepted exception"


def test_flag_reopened():
    from report import _finding_status
    assert _finding_status({"reopened": True}, False) == "Reopened"


def test_flag_awaiting_rescan():
    from report import _finding_status
    assert _finding_status({"awaiting_rescan": True}, False) == "Awaiting re-scan"


def test_remediated_at_on_non_certifiable_is_remediation_attempted():
    """P-15 key case: remediation ran but re-scan has not confirmed it — not 'fixed'."""
    from report import _finding_status
    assert _finding_status({"remediated_at": "2026-08-24T12:00:00"}, False) == "Remediation attempted"


def test_remediated_at_on_certifiable_is_verified_resolved():
    """P-15: remediation + re-scan confirmed (certifiable) → Verified resolved."""
    from report import _finding_status
    assert _finding_status({"remediated_at": "2026-08-24T12:00:00"}, True) == "Verified resolved"


# ── build_report integration: Findings cell no longer says "remediated" ───────

_RUN = {"id": "p15-001", "completed_at": "2026-08-24T12:00:00",
        "avg_score": 95, "owner_email": "ada@example.com"}
_META = {"target": "WCAG 2.1 AA", "version": "3.1", "hash": "deadbeef1234abcd"}
_FACTS_EMPTY = {
    "documents": [],
    "scope": {"catalog_size": 10, "by_mode": {"auto": 10},
              "not_evaluated_criteria": [], "review_criteria": [],
              "human_only_criteria": [], "formats_not_opened": []},
    "remediated_total": 0, "approvals_total": 0,
    "review": {"reviewed": 0, "approved": 0, "rejected": 0, "skipped": 0},
}


def test_certifiable_file_with_issues_shows_verified_resolved():
    """P-15: certifiable file's findings display as 'Verified resolved' in the inventory."""
    from report import build_report
    files = [{"file": "doc.docx", "compliant": 1, "score": 95, "status": "pass",
               "remediated_at": "2026-08-24T10:00:00",
               "issues": [{"wcag": "1.1.1", "severity": "SERIOUS"}]}]
    t = _flat(build_report(_RUN, files, _META, facts=_FACTS_EMPTY))
    assert "Verified resolved" in t


def test_non_certifiable_file_shows_open():
    """P-15: finding on non-certifiable file shows 'Open'."""
    from report import build_report
    files = [{"file": "bad.docx", "compliant": 0, "score": 60, "status": "done",
               "issues": [{"wcag": "1.4.3", "severity": "CRITICAL"}]}]
    t = _flat(build_report(_RUN, files, _META, facts=_FACTS_EMPTY))
    assert "Open" in t


def test_finding_with_remediation_attempted_flag():
    """P-15: issue with remediation_attempted flag on non-certifiable file."""
    from report import build_report
    files = [{"file": "pending.pdf", "compliant": 0, "score": 70, "status": "done",
               "issues": [{"wcag": "2.4.1", "severity": "MODERATE",
                            "remediation_attempted": True}]}]
    t = _flat(build_report(_RUN, files, _META, facts=_FACTS_EMPTY))
    assert "Remediation attempted" in t


def test_pdf_still_valid_with_mixed_statuses():
    """P-15: report with multiple status types is still a valid PDF."""
    from report import build_report
    files = [
        {"file": "ok.docx", "compliant": 1, "score": 100, "status": "pass",
         "issues": [{"wcag": "1.1.1", "severity": "MINOR"}]},
        {"file": "open.pdf", "compliant": 0, "score": 50, "status": "done",
         "issues": [{"wcag": "1.4.3", "severity": "CRITICAL"},
                    {"wcag": "2.4.6", "severity": "SERIOUS", "awaiting_rescan": True}]},
    ]
    pdf = build_report(_RUN, files, _META, facts=_FACTS_EMPTY)
    assert pdf[:5] == b"%PDF-"
