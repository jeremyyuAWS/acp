"""WCAG 2.4.1 Bypass Blocks — deterministic PDF bookmark-outline remediation.

A long PDF with no outline fires PDF_NO_BOOKMARKS. remediate_pdf now rebuilds the outline
from the document's own headings (font-size heuristic, no AI) when it can do so confidently,
and leaves a heading-less/scanned PDF alone (that stays a human-authoring finding) rather
than fabricating a junk outline that reads as "done".
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import office_structure  # noqa: E402
import remediate_pdf  # noqa: E402

pikepdf = pytest.importorskip("pikepdf")
pytest.importorskip("reportlab")

# remediate_pdf reaches into worker-python's `remediation` package, which is not vendored
# here — without it these fail with ModuleNotFoundError rather than skipping honestly.
from engines import NO_PDF, PDF_OK  # noqa: E402

pytestmark = pytest.mark.skipif(not PDF_OK, reason=NO_PDF)


def _pdf(path: Path, pages: list[tuple[str | None, str]]):
    """Build a PDF; each page is (heading_or_None, body). A heading is 18pt bold, body 11pt."""
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import letter
    c = canvas.Canvas(str(path), pagesize=letter)
    for heading, body in pages:
        y = 720
        if heading:
            c.setFont("Helvetica-Bold", 18)
            c.drawString(72, y, heading)
            y -= 30
        c.setFont("Helvetica", 11)
        for _ in range(5):
            c.drawString(72, y, body)
            y -= 16
        c.showPage()
    c.save()


def _outline_titles(path) -> list[str]:
    with pikepdf.open(str(path)) as p:
        with p.open_outline() as ol:
            return [i.title for i in ol.root]


def test_long_pdf_with_headings_gets_a_bookmark_outline(tmp_path):
    src = tmp_path / "report.pdf"
    heads = ["Executive Summary", "Scope", "Findings", "Risk Assessment", "Recommendations", "Appendix"]
    _pdf(src, [(h, "ordinary body paragraph text below the heading") for h in heads])

    assert office_structure.pdf_bypass_blocks_check(src)          # 2.4.1 fires before
    out, applied, _ = remediate_pdf.remediate_pdf(src, ai_enabled=False)
    assert out is not None
    assert any("2.4.1" in a for a in applied)
    assert not office_structure.pdf_bypass_blocks_check(out)      # cleared on re-scan
    assert _outline_titles(out) == heads                         # the doc's own headings


def test_heading_less_pdf_gets_no_outline(tmp_path):
    # Uniform body font, no larger headings — nothing confident to promote, so no outline is
    # fabricated and 2.4.1 stays open (a human-authoring finding), not falsely cleared.
    src = tmp_path / "uniform.pdf"
    _pdf(src, [(None, "every line on every page is the same eleven point body text") for _ in range(6)])

    assert office_structure.pdf_bypass_blocks_check(src)
    out, applied, _ = remediate_pdf.remediate_pdf(src, ai_enabled=False)
    # remediate_pdf may still apply metadata fixes (title/lang); assert only that NO outline
    # was built and 2.4.1 is not falsely cleared.
    assert not any("2.4.1" in a for a in applied)
    check_path = out if out is not None else src
    assert office_structure.pdf_bypass_blocks_check(check_path)


def test_short_pdf_is_left_alone(tmp_path):
    # Below the page floor the finding never fires, so no outline is added.
    src = tmp_path / "memo.pdf"
    _pdf(src, [("Memo", "short note"), (None, "second page")])
    assert not office_structure.pdf_bypass_blocks_check(src)
    out, applied, _ = remediate_pdf.remediate_pdf(src, ai_enabled=False)
    assert not any("2.4.1" in a for a in applied)


def test_noisy_report_outline_holds_only_sections(tmp_path):
    """Whole-remediation view of tests/test_pdf_heading_noise.py: the entries that reach the
    file are the document's sections, not the cover wordmark, the $4.2B pull figure, the pull
    quote, or the running header — none of which 2.4.1 would have failed on, which is exactly
    why nobody would have caught them (the outline is auto-applied)."""
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    src = tmp_path / "noisy.pdf"
    header = "Acme Confidential — Annual Report 2026"
    sections = ["Executive Summary", "Scope", "Findings", "Recommendations", "Appendix"]
    c = canvas.Canvas(str(src), pagesize=letter)
    c.setFont("Helvetica", 13.5), c.drawString(72, 760, header)
    c.setFont("Helvetica-Bold", 28), c.drawString(72, 700, "ACME")
    c.setFont("Helvetica-Bold", 30), c.drawString(72, 640, "Annual Accessibility Report")
    c.setFont("Helvetica", 11), c.drawString(72, 560, "Cover body prose in the modal size.")
    c.showPage()
    for n, section in enumerate(sections):
        c.setFont("Helvetica", 13.5), c.drawString(72, 760, header)
        c.setFont("Helvetica-Bold", 18), c.drawString(72, 700, section)
        c.setFont("Helvetica", 11)
        for i in range(5):
            c.drawString(72, 660 - i * 16, f"Body paragraph {i} of the {section} section.")
        if n == 0:
            c.setFont("Helvetica-Bold", 44), c.drawString(72, 500, "$4.2B")
        if n == 1:
            c.setFont("Helvetica-Oblique", 20)
            c.drawString(72, 500, "“We grew faster than the market.”")
        c.showPage()
    c.save()

    assert office_structure.pdf_bypass_blocks_check(src)
    out, applied, _ = remediate_pdf.remediate_pdf(src, ai_enabled=False)
    assert out is not None and any("2.4.1" in a for a in applied)
    titles = _outline_titles(out)
    assert [t for t in titles if t in sections] == sections
    assert "$4.2B" not in titles and header not in titles and "ACME" not in titles
    assert not any(t.startswith("“") for t in titles)


def test_extract_headings_finds_larger_text(tmp_path):
    src = tmp_path / "h.pdf"
    _pdf(src, [("Big Heading Here", "small body text"), ("Another Heading", "more body text")])
    heads = remediate_pdf._extract_pdf_headings(str(src))
    titles = [t for t, _page, _size in heads]
    assert "Big Heading Here" in titles and "Another Heading" in titles
    assert "small body text" not in titles     # body is not promoted
