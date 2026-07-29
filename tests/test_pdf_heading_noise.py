"""What the PDF font-size heading scan must NOT promote to a heading.

`remediate_pdf._extract_pdf_headings` has one signal — bigger than the body text — and on a
realistic document that signal is shared by things that are not sections: a cover-page
wordmark and byline, a headline financial figure, a pull quote, the running header in every
page margin. It matters more here than in the other two consumers: the 2.4.1 bookmark
outline is AUTO-applied (remediation_capability: pdf 2.4.1), and because 2.4.1 only cares
about the text and its order, a junk entry never fails a re-scan and no human ever sees it.

The level derivation is tested here too, on the same fixture, because it is the stated
blocker on ever automating the 2.4.6 heading map: absolute font-size rank let one 44pt
figure take Heading 1 and pushed the real sections down to Heading 6.

Needs only pdfplumber + reportlab — NOT the worker-python PDF engine — so unlike
tests/test_pdf_outline.py these run wherever the wheels are installed.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

pytest.importorskip("pdfplumber")
pytest.importorskip("reportlab")

import proposals as P  # noqa: E402
import remediate_pdf as rp  # noqa: E402

RUNNING_HEADER = "Acme Confidential — Annual Report 2026"
SECTIONS = ["Executive Summary", "Scope", "Findings", "Risk Assessment",
            "Recommendations", "Appendix"]


@pytest.fixture(scope="module")
def noisy_report(tmp_path_factory) -> Path:
    """A report whose non-heading text is all set larger than the body: the cover page
    (wordmark, title, subtitle, byline), a $4.2B pull figure, a pull quote, and a running
    header repeated in the top margin of all seven pages. One real subsection ("Findings by
    region") sits below its section so nesting is observable."""
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    path = tmp_path_factory.mktemp("pdf") / "noisy-report.pdf"
    c = canvas.Canvas(str(path), pagesize=letter)

    def header():
        c.setFont("Helvetica", 13.5)                  # > 1.2x the 11pt body, in the margin
        c.drawString(72, 760, RUNNING_HEADER)

    header()                                          # cover page
    c.setFont("Helvetica-Bold", 28), c.drawString(72, 700, "ACME")
    c.setFont("Helvetica-Bold", 30), c.drawString(72, 640, "Annual Accessibility Report")
    c.setFont("Helvetica", 22), c.drawString(72, 600, "Fiscal Year 2026")
    c.setFont("Helvetica", 15), c.drawString(72, 560, "By Jane Doe, Chief Accessibility Officer")
    c.setFont("Helvetica", 11)
    for i in range(4):
        c.drawString(72, 480 - i * 16, "Body prose anchoring the modal body size on the cover.")
    c.showPage()

    for n, section in enumerate(SECTIONS):
        header()
        c.setFont("Helvetica-Bold", 18), c.drawString(72, 700, section)
        c.setFont("Helvetica", 11)
        for i in range(6):
            c.drawString(72, 660 - i * 16, f"Ordinary body paragraph {i} of {section}.")
        if n == 0:
            c.setFont("Helvetica-Bold", 44), c.drawString(72, 500, "$4.2B")
        if n == 1:
            c.setFont("Helvetica-Oblique", 20)
            c.drawString(72, 500, "“We grew faster than the market.”")
        if n == 2:
            c.setFont("Helvetica-Bold", 15), c.drawString(72, 500, "Findings by region")
            c.setFont("Helvetica", 11)
            for i in range(3):
                c.drawString(72, 470 - i * 16, "Regional body prose in the modal body size.")
        c.showPage()
    c.save()
    return path


def _titles(path: Path) -> list[str]:
    return [t for t, _page, _size in rp._extract_pdf_headings(str(path))]


def test_real_sections_are_still_extracted_in_order(noisy_report):
    titles = _titles(noisy_report)
    assert [t for t in titles if t in SECTIONS] == SECTIONS
    assert "Annual Accessibility Report" in titles          # the document title heads it
    assert "Findings by region" in titles                   # a real subsection survives


def test_headline_figure_is_not_a_heading(noisy_report):
    # "$4.2B" set at 44pt was the single worst entry: largest text in the document, so it
    # became bookmark #1 AND Heading 1 for the structure map.
    assert "$4.2B" not in _titles(noisy_report)


def test_pull_quote_is_not_a_heading(noisy_report):
    assert not any(t.startswith("“") for t in _titles(noisy_report))


def test_cover_wordmark_and_byline_are_not_headings(noisy_report):
    titles = _titles(noisy_report)
    assert "ACME" not in titles
    assert not any(t.startswith("By Jane Doe") for t in titles)


def test_running_header_is_not_a_heading(noisy_report):
    # Dedupe-by-text already hid the repetition; the first occurrence still became the
    # outline's opening bookmark, on every long PDF with a running header.
    assert RUNNING_HEADER not in _titles(noisy_report)


def test_levels_are_monotonic_with_sections_at_one_depth(noisy_report):
    heads = rp._extract_pdf_headings(str(noisy_report))
    levels = P.heading_level_sequence(size for _t, _p, size in heads)
    by_title = dict(zip([t for t, _p, _s in heads], levels))
    assert levels[0] == 1                                   # first entry is always Heading 1
    assert all(b - a <= 1 for a, b in zip(levels, levels[1:]))   # never skips a level
    assert len({by_title[s] for s in SECTIONS}) == 1         # peer sections share one depth
    assert by_title["Findings by region"] == by_title["Findings"] + 1


def test_auto_applied_outline_carries_no_furniture(noisy_report, tmp_path):
    """The end the noise actually reaches: bookmarks written into the file, unattended."""
    pikepdf = pytest.importorskip("pikepdf")
    out = tmp_path / "outlined.pdf"
    with pikepdf.open(str(noisy_report)) as pdf:
        assert rp._generate_pdf_outline(pdf, str(noisy_report))
        pdf.save(str(out))
    with pikepdf.open(str(out)) as pdf, pdf.open_outline() as outline:
        titles = [item.title for item in outline.root]
    assert [t for t in titles if t in SECTIONS] == SECTIONS
    assert "$4.2B" not in titles and RUNNING_HEADER not in titles and "ACME" not in titles
    assert not any(t.startswith("“") or t.startswith("By Jane") for t in titles)


# ── The furniture predicate, case by case ─────────────────────────────────────

@pytest.mark.parametrize("text", [
    "$4.2B", "4.2", "$4.2 billion", "12,345", "2026", "3.1%", "-17", "€890M", "42 ",
    "“We grew faster than the market.”", '"Quoted claim."', "‘A quiet year.’",
    "ACME", "FY26", "III",
    "By Jane Doe, Chief Accessibility Officer", "Prepared by Deloitte LLP", "Authors: R. Patel",
])
def test_furniture_is_rejected(text):
    assert rp._looks_like_heading_furniture(text), text


@pytest.mark.parametrize("text", [
    # Each of these is a heading a looser filter would have eaten.
    "Executive Summary", "Findings by region", "Appendix A", "3. Recommendations",
    "Section 3", "Q4 performance", "Bypass Blocks", "By the Numbers", "By The Numbers",
    "By Region", "2026 in review", "Risk", "WCAG conformance", "$ and cents",
    "“Reasonable adjustments” explained",
    # The short-all-caps rule must not reach a script that has no case: in Chinese or
    # Japanese every string equals its own upper-case, and "概要" (Summary) is a section.
    "概要", "はじめに", "요약",
])
def test_real_headings_are_kept(text):
    assert not rp._looks_like_heading_furniture(text), text


def test_furniture_check_tolerates_empty_text():
    assert not rp._looks_like_heading_furniture("")


def test_repeated_body_text_is_not_treated_as_a_running_header(tmp_path):
    """The frequency half of the running-header rule is guarded by margin position: a
    per-page section heading that differs only by number ("Step 1", "Step 2", …) normalises
    to one running key, and dropping those would empty the outline of a procedure document."""
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    path = tmp_path / "procedure.pdf"
    c = canvas.Canvas(str(path), pagesize=letter)
    for n in range(1, 7):
        c.setFont("Helvetica-Bold", 18), c.drawString(72, 640, f"Step {n}")   # body band
        c.setFont("Helvetica", 11)
        c.drawString(72, 600, "Instructions for this step in the ordinary body size.")
        c.showPage()
    c.save()
    assert _titles(path) == [f"Step {n}" for n in range(1, 7)]


def test_uniform_font_pdf_still_yields_nothing(tmp_path):
    # The filters must not be the reason a document has no headings — a scanned/uniform PDF
    # yields nothing for the same reason as before, so 2.4.1 stays an open finding.
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    path = tmp_path / "uniform.pdf"
    c = canvas.Canvas(str(path), pagesize=letter)
    for _ in range(6):
        c.setFont("Helvetica", 11)
        for i in range(8):
            c.drawString(72, 700 - i * 16, "Every line on every page is the same body text.")
        c.showPage()
    c.save()
    assert rp._extract_pdf_headings(str(path)) == []
