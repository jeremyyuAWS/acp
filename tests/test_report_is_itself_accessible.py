"""The conformance report is a PDF we hand a customer as audit evidence. Hold it to the
standard it certifies other people's documents against — using the same engine.

Asserting the catalog keys by hand would pin the mechanism (`/Lang` is set) rather than the
property (a screen reader is told the language). So these tests run ACP's OWN vendored PDF
rules over a freshly built report: if the rules tighten, the report is held to the new bar
without anyone remembering to update this file.

The renderer is now the Chromium-based `build_tagged_report` (report_tagged.py). The three
findings the engine raised against the old reportlab output on 2026-08-04 are all closed here:

    pdf.document-language   SC_3_1_1  SERIOUS     no catalog /Lang
    pdf.display-doc-title   SC_2_4_2  MODERATE    ViewerPreferences DisplayDocTitle unset
    pdf.tagged              SC_1_3_1  CRITICAL     no structure tree

The tagged report also passes pdf.missing-alt-text (all charts and the logo have Alt entries
in the structure tree) and pdf.table-headers (all tables have /TH header cells).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

from engines import NO_PDF, PDF_ENGINE, PDF_OK  # noqa: E402

_CHROMIUM = Path(
    __import__("os").environ.get(
        "ACP_CHROMIUM",
        "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
    )
)
_NO_CHROMIUM = f"Chromium not found at {_CHROMIUM}"
_CHROMIUM_OK = _CHROMIUM.exists()

pytestmark = [
    pytest.mark.skipif(not PDF_OK, reason=NO_PDF),
    pytest.mark.skipif(not _CHROMIUM_OK, reason=_NO_CHROMIUM),
]


def _report_bytes() -> bytes:
    """A report through the real build_tagged_report path — not a hand-rolled document, or the
    test would pass while the shipped renderer regressed."""
    import report_tagged
    files = [
        {"file": "a.pdf", "status": "done", "compliant": 1, "score": 90,
         "skipped_rules": 0, "issues": []},
        {"file": "b.docx", "status": "done", "compliant": 0, "score": 55, "skipped_rules": 0,
         "issues": [{"wcag": "SC_1_1_1", "severity": "CRITICAL"},
                    {"wcag": "SC_2_4_2", "severity": "SERIOUS"}]},
    ]
    run = {"id": "selfcheck", "completed_at": "2026-08-04T00:00:00", "avg_score": 72,
           "files": 2, "certifiable": 1, "uncertain": 0, "error": 0}
    return report_tagged.build_tagged_report(
        run, files, {"target": "WCAG 2.1 Level AA", "version": "3", "hash": "abc"}
    )


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
        "ImageAltTextRule": "analysers.rules.pdf.image_alt_text",
        "TableHeadersRule": "analysers.rules.pdf.table_headers",
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


def test_report_is_tagged(tmp_path):
    """WCAG 1.3.1. The report now has a /StructTreeRoot with /MarkInfo Marked=true, so screen
    readers can navigate it structurally. This test replaces test_untagged_is_still_the_open_finding
    from the reportlab era — that test was a known-gap pin; this one is a passing bar."""
    assert _rule_findings(tmp_path, "TaggedPdfRule") == []


def test_report_images_have_alt_text(tmp_path):
    """WCAG 1.1.1. The logo and all SVG charts are tagged as /Figure elements with /Alt entries,
    so a screen reader can describe them. This check was vacuous before tagging (an untagged PDF
    gives the rule nothing to inspect)."""
    assert _rule_findings(tmp_path, "ImageAltTextRule") == []


def test_report_tables_have_headers(tmp_path):
    """WCAG 1.3.1 (table header aspect). All tables in the report use <th scope="col"> which
    Chromium maps to /TH elements, so screen readers can associate data cells with their headers.
    This check was also vacuous on the untagged reportlab output."""
    assert _rule_findings(tmp_path, "TableHeadersRule") == []
