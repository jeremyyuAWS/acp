"""Regression for the deterministic PDF document-title fix (WCAG 2.4.2).

remediate_pdf sets a filename-derived /Title when a PDF has none (the analyser's
pdf.document-title rule passes iff /Title is non-empty). Metadata is written with pypdf
because pikepdf's docinfo writes persist nondeterministically once libxml2 is loaded in a
long-lived worker process. Self-skips when pikepdf / pypdf / reportlab, or the partner PDF
engine, are unavailable.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

pikepdf = pytest.importorskip("pikepdf")
pytest.importorskip("pypdf")
pytest.importorskip("reportlab")
from pypdf import PdfReader  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
import remediate_pdf as RP  # noqa: E402

# remediate_pdf() imports the partner PDF engine, a separate repo located via scanner.WP /
# $ACP_PDF_ENGINE and absent on a clean CI agent. Skip there rather than hard-fail.
from conftest import requires_pdf_engine  # noqa: E402

pytestmark = requires_pdf_engine


def _title(pdf_path: Path) -> str:
    # Read /Title via pypdf: pikepdf's docinfo reads are nondeterministic once libxml2 is
    # loaded in-process (the same reason we WRITE metadata with pypdf).
    return str((PdfReader(str(pdf_path)).metadata or {}).get("/Title") or "").strip()


def _titleless_pdf(path: Path) -> None:
    raw = path.with_name("raw.pdf")
    c = canvas.Canvas(str(raw))
    c.drawString(72, 720, "Body text of the document.")
    c.showPage()
    c.save()
    pdf = pikepdf.open(str(raw))
    if "/Title" in pdf.docinfo:          # reportlab injects "untitled"
        del pdf.docinfo["/Title"]
    pdf.save(str(path))
    pdf.close()


def test_pdf_title_set_when_missing(tmp_path):
    src = tmp_path / "notitle.pdf"
    _titleless_pdf(src)
    assert not str(pikepdf.open(str(src)).docinfo.get("/Title") or "").strip()

    fixed, applied, _ = RP.remediate_pdf(src)
    assert fixed is not None
    assert _title(Path(fixed)), "remediation must set a non-empty /Title"
    assert any("2.4.2" in a for a in applied)
    # stage-1 pikepdf Root fixes must survive the pypdf metadata pass (Root reads are stable)
    q = pikepdf.open(str(fixed))
    assert str(q.Root.get("/Lang") or "")
    assert "/ViewerPreferences" in q.Root


def test_pdf_existing_title_preserved(tmp_path):
    titled = tmp_path / "titled.pdf"
    c = canvas.Canvas(str(titled))
    c.setTitle("Quarterly Board Report")               # a real title, set at creation
    c.drawString(72, 720, "Body text.")
    c.showPage()
    c.save()

    fixed, applied, _ = RP.remediate_pdf(titled)
    assert fixed is not None
    assert _title(Path(fixed)) == "Quarterly Board Report"   # a real title is never overwritten


def test_scanner_title_correction(tmp_path):
    """scanner._pdf_correct_title drops a false pdf.document-title finding when the PDF
    actually declares a title (pikepdf's docinfo read is unreliable under libxml2), and
    keeps it when the title is genuinely missing."""
    import scanner

    finding = [{"ruleId": "pdf.document-title", "wcag": "SC_2_4_2", "severity": "SERIOUS"}]

    has = tmp_path / "has.pdf"
    c = canvas.Canvas(str(has))
    c.setTitle("Real Title")
    c.drawString(72, 720, "Body.")
    c.showPage()
    c.save()
    assert scanner._pdf_correct_title(has, list(finding)) == []      # title present -> drop

    none = tmp_path / "none.pdf"
    _titleless_pdf(none)
    assert scanner._pdf_correct_title(none, list(finding)) == finding  # no title -> keep
