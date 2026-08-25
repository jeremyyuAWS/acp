"""The conformance report is a PDF we hand a customer as audit evidence. Hold it to the
standard it certifies other people's documents against — using the same engine.

Asserting the catalog keys by hand would pin the mechanism (`/Lang` is set) rather than the
property (a screen reader is told the language). So these tests run ACP's OWN vendored PDF
rules over a freshly built report: if the rules tighten, the report is held to the new bar
without anyone remembering to update this file.

Two of the three findings our engine raised against the report on 2026-08-04 are closed here:

    pdf.document-language   SC_3_1_1  SERIOUS     no catalog /Lang
    pdf.display-doc-title   SC_2_4_2  MODERATE    ViewerPreferences DisplayDocTitle unset

The third — `pdf.tagged` (SC_1_3_1, CRITICAL: no structure tree) — is NOT closed, and
test_untagged_is_still_the_open_finding below pins it as a known, deliberate gap rather than
letting it read as an oversight. ReportLab 4.5.1 emits no marked content at all (verified: no
BDC/EMC in the content stream), so there are no MCIDs for a structure tree to reference; and
auto-tagging an untagged PDF is `ASSISTED` in our own product (remediation_capability.py — a
heading map a human confirms), so the report cannot honestly claim what we do not sell.
Delete that test when the renderer can tag.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

from engines import NO_PDF, PDF_ENGINE, PDF_OK  # noqa: E402

pytestmark = pytest.mark.skipif(not PDF_OK, reason=NO_PDF)


def _report_bytes() -> bytes:
    """A report through the real build_report path — not a hand-rolled ReportLab doc, or the
    test would pass while the shipped renderer regressed."""
    import report
    files = [
        {"file": "a.pdf", "status": "done", "compliant": 1, "score": 90,
         "skipped_rules": 0, "issues": []},
        {"file": "b.docx", "status": "done", "compliant": 0, "score": 55, "skipped_rules": 0,
         "issues": [{"wcag": "SC_1_1_1", "severity": "CRITICAL"},
                    {"wcag": "SC_2_4_2", "severity": "SERIOUS"}]},
    ]
    run = {"id": "selfcheck", "completed_at": "2026-08-04T00:00:00", "avg_score": 72,
           "files": 2, "certifiable": 1, "uncertain": 0, "error": 0}
    return report.build_report(run, files,
                               {"target": "WCAG 2.1 Level AA", "version": "3", "hash": "abc"})


def _rule_findings(tmp_path, rule_cls_name: str) -> list:
    """Run one vendored rule over a freshly built report and return its findings."""
    sys.path.insert(0, str(PDF_ENGINE))
    import importlib

    import pdfplumber
    import pikepdf

    out = tmp_path / "report.pdf"
    out.write_bytes(_report_bytes())

    module = {
        "DocumentLanguageRule": "analysers.rules.pdf.document_language",
        "DisplayTitleRule": "analysers.rules.pdf.display_title",
        "DocumentTitleRule": "analysers.rules.pdf.document_title",
        "TaggedPdfRule": "analysers.rules.pdf.tagged_pdf",
    }[rule_cls_name]
    rule = getattr(importlib.import_module(module), rule_cls_name)()

    with pikepdf.open(out) as pdf, pdfplumber.open(out) as plumber:
        return rule.check(pdf, plumber)


def test_report_declares_its_language(tmp_path):
    """WCAG 3.1.1. Without /Lang a screen reader announces the certification document in
    whatever language the user's locale guesses at."""
    assert _rule_findings(tmp_path, "DocumentLanguageRule") == []


def test_report_asks_viewers_to_show_its_title(tmp_path):
    """WCAG 2.4.2, the half that was missing. docinfo /Title was always set, but with
    DisplayDocTitle unset a viewer announces the FILENAME — 'acp-report-<uuid>.pdf' — as the
    title of the document. Both halves or neither."""
    assert _rule_findings(tmp_path, "DisplayTitleRule") == []


def test_report_still_carries_its_title(tmp_path):
    """The half that already worked. Pinned so a future change to the ViewerPreferences write
    cannot quietly cost us the docinfo title it sits beside."""
    assert _rule_findings(tmp_path, "DocumentTitleRule") == []


def test_report_now_tagged(tmp_path):
    """The renderer post-processes with pikepdf to inject MarkInfo + StructTreeRoot.
    TaggedPdfRule must find no findings. If this fails, _tag_pdf() in report.py regressed.

    Note: pdf.missing-alt-text and pdf.table-headers may now find issues in the report's
    charts (undescribed vector drawings) — track those as a follow-on to P3.2."""
    assert _rule_findings(tmp_path, "TaggedPdfRule") == []
