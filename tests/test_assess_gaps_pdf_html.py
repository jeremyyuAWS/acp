"""Final assessment gap-closure: pdf 2.4.6 (tagged-no-headings) + pdf 2.4.4 (raw-URL link text)
+ html 1.3.2 (CSS visual reorder) + html 1.4.5 (image of text). Detection only — all route to
human remediation. PDFs are built with reportlab + pikepdf so the checks run on real files."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))
import office_structure as off  # noqa: E402
import scanner  # noqa: E402


def _scs(findings: list[dict]) -> set[str]:
    return {re.match(r"(\d+\.\d+\.\d+)", f["wcag"]).group(1) for f in findings}


# ── html 1.3.2 / 1.4.5 ─────────────────────────────────────────────────────────
def _html(tmp_path: Path, body: str) -> set[str]:
    p = tmp_path / "p.html"
    p.write_text(f"<!doctype html><html lang='en'><head><title>T</title></head><body>{body}</body></html>")
    return {i["wcag"].split()[0] for i in scanner._analyse_html(p)["issues"]}


def test_html_flags_flex_order_reorder(tmp_path):
    assert "1.3.2" in _html(tmp_path, '<div style="display:flex"><p style="order:2">a</p><p style="order:1">b</p></div>')


def test_html_flags_reversed_flex_direction(tmp_path):
    assert "1.3.2" in _html(tmp_path, '<div style="display:flex;flex-direction:row-reverse"><a>x</a><a>y</a></div>')


def test_html_linear_content_not_flagged_for_1_3_2(tmp_path):
    assert "1.3.2" not in _html(tmp_path, '<div style="display:flex"><p>a</p><p>b</p></div>')


def test_html_flags_image_of_text_by_filename(tmp_path):
    assert "1.4.5" in _html(tmp_path, '<img src="/img/banner-headline.png" alt="Big Sale">')


def test_html_flags_image_replacement_text_indent(tmp_path):
    assert "1.4.5" in _html(tmp_path, '<h1 style="text-indent:-9999px;background:url(logo.png)">Acme</h1>')


def test_html_ordinary_image_not_flagged_for_1_4_5(tmp_path):
    assert "1.4.5" not in _html(tmp_path, '<img src="/img/team-photo.jpg" alt="Our team at the retreat">')


# ── pdf 2.4.4 / 2.4.6 ──────────────────────────────────────────────────────────
reportlab = pytest.importorskip("reportlab")
import pikepdf  # noqa: E402
from reportlab.pdfgen import canvas as _canvas  # noqa: E402


def _pdf(tmp_path: Path, name: str, pages: int, draw=None) -> Path:
    p = tmp_path / name
    c = _canvas.Canvas(str(p), pagesize=(400, 400))
    for i in range(pages):
        if draw:
            draw(c, i)
        c.showPage()
    c.save()
    return p


def _tag(path: Path, s_name: str | None) -> Path:
    """Give the PDF a StructTreeRoot whose single element has structure type `s_name`
    (None → leave untagged)."""
    with pikepdf.open(str(path), allow_overwriting_input=True) as pdf:
        if s_name is not None:
            elem = pikepdf.Dictionary(Type=pikepdf.Name("/StructElem"), S=pikepdf.Name(s_name))
            pdf.Root.StructTreeRoot = pdf.make_indirect(
                pikepdf.Dictionary(Type=pikepdf.Name("/StructTreeRoot"), K=elem))
        pdf.save(str(path))
    return path


def test_pdf_tagged_without_headings_flags_2_4_6(tmp_path):
    p = _tag(_pdf(tmp_path, "noh.pdf", 5), "/P")           # tagged, only a paragraph element
    assert "2.4.6" in _scs(off.pdf_headings_labels_check(p))


def test_pdf_tagged_with_heading_passes_2_4_6(tmp_path):
    p = _tag(_pdf(tmp_path, "h.pdf", 5), "/H1")
    assert "2.4.6" not in _scs(off.pdf_headings_labels_check(p))


def test_pdf_untagged_is_not_flagged_for_2_4_6(tmp_path):
    p = _tag(_pdf(tmp_path, "untagged.pdf", 5), None)      # no struct tree → 1.3.1/2.4.1's concern
    assert "2.4.6" not in _scs(off.pdf_headings_labels_check(p))


def test_pdf_short_document_is_not_flagged_for_2_4_6(tmp_path):
    p = _tag(_pdf(tmp_path, "short.pdf", 2), "/P")          # below the page floor
    assert "2.4.6" not in _scs(off.pdf_headings_labels_check(p))


def test_pdf_raw_url_link_text_flags_2_4_4(tmp_path):
    url = "https://example.com/annual-report"
    def draw(c, i):
        c.drawString(40, 200, url)                          # the visible text IS the raw URL
        c.linkURL(url, (40, 195, 360, 215))
    assert "2.4.4" in _scs(off.pdf_link_purpose_check(_pdf(tmp_path, "raw.pdf", 1, draw)))


def test_pdf_descriptive_link_text_not_flagged_for_2_4_4(tmp_path):
    def draw(c, i):
        c.drawString(40, 200, "Read the annual report")     # meaningful label, not the URL
        c.linkURL("https://example.com/annual-report", (40, 195, 360, 215))
    assert "2.4.4" not in _scs(off.pdf_link_purpose_check(_pdf(tmp_path, "good.pdf", 1, draw)))
