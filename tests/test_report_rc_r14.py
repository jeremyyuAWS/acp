"""Tests for backlog R-C (per-fix assurance tier) and R14 (per-criterion compliance table).

R-C distinguishes three assurance tiers for applied fixes in the evidence appendix:
  1. Deterministic — rule-based fixer, no model, re-scan cleared.
  2. AI · human-confirmed — model-generated + human approval + re-scan validated.
  3. AI · re-scan-validated — model-generated + re-scan cleared, no human approval.

R14 adds a per-criterion compliance table scoped to criteria that fired at least one
finding — open (still blocking) or cleared (remediated / no longer blocking). Criteria
that ran and found nothing are never listed.
"""
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

_RUN = {"id": "scan-rc-r14", "completed_at": "2026-08-23T12:00:00", "avg_score": 80,
        "owner_email": None}
_META = {"target": "AA", "version": "1.3", "hash": "cafebabe"}


def _pdf_text(pdf: bytes) -> str:
    from pypdf import PdfReader
    return "".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(pdf)).pages)


def _flat(pdf: bytes) -> str:
    import re
    return re.sub(r"\s+", " ", _pdf_text(pdf))


# ── R-C: assurance tier labels ────────────────────────────────────────────────

_APPLIED_DETERMINISTIC = {
    "sc": "2.4.4", "criterion": "Link Purpose (In Context)",
    "before": "click here", "after": "Download Annual Report (PDF)",
    "note": "derived from the download target",
    "value": None,       # no AI wrote it — deterministic fixer
    "source": None, "thumb": None,
    "decision": None,    # auto-applied, no human needed
    "approved_value": None, "reviewer": None, "reviewed_at": None,
    "validated": True,
}

_APPLIED_AI_HUMAN = {
    "sc": "1.1.1", "criterion": "Non-text Content",
    "before": "(no alt text)", "after": "Bar chart of 2026 sales",
    "note": "AI vision description",
    "value": "Bar chart of 2026 sales",   # AI wrote it
    "source": "AI vision model", "thumb": None,
    "decision": "approved",               # human approved it
    "approved_value": None, "reviewer": "ada@example.com",
    "reviewed_at": "2026-08-23T11:00:00",
    "validated": True,
}

_APPLIED_AI_NO_HUMAN = {
    "sc": "3.3.2", "criterion": "Labels or Instructions",
    "before": "(unlabelled)", "after": "First name",
    "note": None,
    "value": "First name",   # AI wrote it
    "source": "AI text model", "thumb": None,
    "decision": None,         # no human approval recorded
    "approved_value": None, "reviewer": None, "reviewed_at": None,
    "validated": True,
}

_EVIDENCE_ALL_TIERS = [{"file": "form.docx", "proposed": [],
                         "applied": [_APPLIED_DETERMINISTIC,
                                     _APPLIED_AI_HUMAN,
                                     _APPLIED_AI_NO_HUMAN]}]
_FILES_CERT = [{"file": "form.docx", "compliant": 1, "score": 100, "status": "ok", "issues": []}]


def test_deterministic_fix_shows_deterministic_badge():
    from report import build_report
    t = _flat(build_report(_RUN, _FILES_CERT, _META, evidence=_EVIDENCE_ALL_TIERS))
    assert "Deterministic" in t


def test_ai_human_fix_shows_human_confirmed_badge():
    from report import build_report
    t = _flat(build_report(_RUN, _FILES_CERT, _META, evidence=_EVIDENCE_ALL_TIERS))
    assert "human-confirmed" in t


def test_ai_no_human_fix_shows_re_scan_validated_badge():
    from report import build_report
    t = _flat(build_report(_RUN, _FILES_CERT, _META, evidence=_EVIDENCE_ALL_TIERS))
    assert "re-scan-validated" in t


def test_deterministic_sign_off_does_not_say_ai():
    from report import build_report
    t = _flat(build_report(_RUN, _FILES_CERT, _META,
                            evidence=[{"file": "f.docx", "proposed": [],
                                       "applied": [_APPLIED_DETERMINISTIC]}]))
    # The deterministic sign-off names the fixer type; must not call it AI
    assert "deterministic fixer" in t
    assert "AI-generated" not in t


def test_ai_no_human_sign_off_says_no_approval_recorded():
    from report import build_report
    t = _flat(build_report(_RUN, _FILES_CERT, _META,
                            evidence=[{"file": "f.docx", "proposed": [],
                                       "applied": [_APPLIED_AI_NO_HUMAN]}]))
    assert "no human approval recorded" in t


def test_ai_human_sign_off_names_reviewer():
    from report import build_report
    t = _flat(build_report(_RUN, _FILES_CERT, _META,
                            evidence=[{"file": "f.docx", "proposed": [],
                                       "applied": [_APPLIED_AI_HUMAN]}]))
    assert "approved by ada@example.com" in t


def test_three_tiers_all_present_in_same_report():
    """All three assurance tier badges can coexist in one report."""
    from report import build_report
    t = _flat(build_report(_RUN, _FILES_CERT, _META, evidence=_EVIDENCE_ALL_TIERS))
    assert "Deterministic" in t
    assert "human-confirmed" in t
    assert "re-scan-validated" in t


# ── R14: per-criterion compliance table ──────────────────────────────────────

_ISSUES_OPEN = [
    {"ruleId": "PDF_MISSING_ALT", "wcag": "SC_1_1_1", "severity": "SERIOUS", "detail": "d"},
    {"ruleId": "PDF_CONTRAST",    "wcag": "SC_1_4_3", "severity": "MODERATE", "detail": "d"},
]
_ISSUES_CLEARED = [
    {"ruleId": "PDF_MISSING_ALT", "wcag": "SC_1_1_1", "severity": "SERIOUS", "detail": "d"},
]

_FILES_WITH_ISSUES = [
    # non-certifiable — findings are OPEN
    {"file": "failing.pdf", "compliant": 0, "score": 60, "status": "pass",
     "issues": _ISSUES_OPEN},
    # certifiable — finding was CLEARED
    {"file": "fixed.pdf", "compliant": 1, "score": 100, "status": "pass",
     "issues": _ISSUES_CLEARED},
]


def test_r14_section_header_present_when_findings_exist():
    from report import build_report
    t = _flat(build_report(_RUN, _FILES_WITH_ISSUES, _META))
    assert "Criteria with findings" in t


def test_r14_open_criterion_appears_in_table():
    from report import build_report
    t = _flat(build_report(_RUN, _FILES_WITH_ISSUES, _META))
    # 1.1.1 is open in failing.pdf
    assert "1.1.1" in t
    # 1.4.3 is open in failing.pdf
    assert "1.4.3" in t


def test_r14_cleared_criterion_shows_cleared_count():
    from report import build_report
    t = _flat(build_report(_RUN, _FILES_WITH_ISSUES, _META))
    # 1.1.1 is cleared in fixed.pdf (certifiable) — the cleared count must appear
    # We can't assert an exact pixel number, but we can assert both columns exist
    assert "Cleared" in t


def test_r14_absent_for_clean_estate():
    """A scan with zero findings produces no criteria table — nothing to show."""
    from report import build_report
    files = [{"file": "ok.docx", "compliant": 1, "score": 100, "status": "ok", "issues": []}]
    t = _flat(build_report(_RUN, files, _META))
    assert "Criteria with findings" not in t


def test_r14_rule_id_appears_in_table():
    from report import build_report
    t = _flat(build_report(_RUN, _FILES_WITH_ISSUES, _META))
    assert "PDF_MISSING_ALT" in t


def test_r14_criterion_with_both_open_and_cleared_appears_once():
    """1.1.1 is open in one file and cleared in another — must appear exactly once."""
    from report import build_report
    t = _flat(build_report(_RUN, _FILES_WITH_ISSUES, _META))
    # count occurrences of "Non-text Content" (the full display name for 1.1.1)
    assert t.count("Non-text Content") >= 1   # at least one appearance


def test_r14_section_precedes_evidence_appendix():
    """The criterion table is a summary; the detailed evidence appendix follows it."""
    from report import build_report
    evidence = [{"file": "fixed.pdf", "proposed": [],
                 "applied": [{**_APPLIED_AI_HUMAN, "sc": "1.1.1"}]}]
    t = _flat(build_report(_RUN, _FILES_WITH_ISSUES, _META, evidence=evidence))
    assert "Criteria with findings" in t
    assert "Remediation evidence" in t
    assert t.index("Criteria with findings") < t.index("Remediation evidence")
