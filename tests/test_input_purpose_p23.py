"""P-23: 1.3.5 Identify Input Purpose — PDF and DOCX detectors.

PDF: AcroForm fields whose /T (name) or /TU (tooltip) matches the WCAG personal-data
vocabulary are flagged as PDF_INPUT_NO_PURPOSE (PDF provides no autocomplete mechanism).

DOCX: Content controls of interactive types whose w:alias title matches the vocabulary
are flagged as DOCX_INPUT_NO_PURPOSE (OOXML provides no autocomplete mechanism).

Both detectors are HEURISTIC — vocabulary matching is approximate. A personal-data field
that is named generically is not caught; an organisational field named like a personal
one may be a false positive. Tests cover the true-positive and true-negative shapes.
"""
from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

from formats.docx.detectors.input_purpose import detect as docx_detect  # noqa: E402

# PDF tests require pikepdf — skip individually rather than module-level so DOCX tests always run.
try:
    import pikepdf as _pikepdf
    _HAS_PIKEPDF = True
except ImportError:
    _HAS_PIKEPDF = False

needs_pikepdf = pytest.mark.skipif(not _HAS_PIKEPDF, reason="pikepdf not installed")


# ── PDF fixture builders ───────────────────────────────────────────────────────────────

def _pdf_with_field(tmp: Path, name: str, tooltip: str | None = None) -> Path:
    """PDF with a single AcroForm text field using the given /T name (and optional /TU tooltip)."""
    import pikepdf
    p = tmp / f"pdf_{name[:12].replace(' ', '_')}.pdf"
    pdf = pikepdf.Pdf.new()
    page = pikepdf.Dictionary(
        Type=pikepdf.Name("/Page"),
        MediaBox=pikepdf.Array([0, 0, 612, 792]),
    )
    page_ref = pdf.make_indirect(page)
    pdf.pages.append(pikepdf.Page(page_ref))

    kw = dict(
        Type=pikepdf.Name("/Annot"),
        Subtype=pikepdf.Name("/Widget"),
        FT=pikepdf.Name("/Tx"),
        T=pikepdf.String(name),
        Rect=pikepdf.Array([pikepdf.Real(x) for x in [72, 700, 200, 720]]),
    )
    if tooltip is not None:
        kw["TU"] = pikepdf.String(tooltip)
    widget = pdf.make_indirect(pikepdf.Dictionary(**kw))
    page_ref["/Annots"] = pikepdf.Array([widget])
    pdf.Root["/AcroForm"] = pdf.make_indirect(pikepdf.Dictionary(
        Fields=pikepdf.Array([widget])
    ))
    pdf.save(str(p))
    return p


def _pdf_no_fields(tmp: Path) -> Path:
    import pikepdf
    p = tmp / "nofields.pdf"
    pdf = pikepdf.Pdf.new()
    page = pikepdf.Dictionary(Type=pikepdf.Name("/Page"), MediaBox=pikepdf.Array([0, 0, 612, 792]))
    pdf.pages.append(pikepdf.Page(pdf.make_indirect(page)))
    pdf.save(str(p))
    return p


# ── DOCX fixture builders ──────────────────────────────────────────────────────────────

_DOCX_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>{body}</w:body>
</w:document>"""

_SDT_BLOCK = """\
<w:sdt>
  <w:sdtPr>
    <w:alias w:val="{alias}"/>
    <w:date/>
  </w:sdtPr>
  <w:sdtContent><w:p/></w:sdtContent>
</w:sdt>"""


def _make_docx(tmp: Path, name: str, body_xml: str) -> Path:
    p = tmp / name
    doc_xml = _DOCX_TEMPLATE.format(body=body_xml).encode()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", doc_xml)
        zf.writestr("[Content_Types].xml",
                    '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
    p.write_bytes(buf.getvalue())
    return p


def _docx_with_control(tmp: Path, alias: str) -> Path:
    return _make_docx(tmp, f"ctrl_{alias[:10]}.docx", _SDT_BLOCK.format(alias=alias))


def _docx_no_controls(tmp: Path) -> Path:
    return _make_docx(tmp, "nocontrols.docx", "<w:p><w:r><w:t>Hello</w:t></w:r></w:p>")


# ── PDF tests ─────────────────────────────────────────────────────────────────────────

@needs_pikepdf
def test_pdf_email_field_flagged(tmp_path):
    """Field named 'email' → PDF_INPUT_NO_PURPOSE."""
    from formats.pdf.detectors.input_purpose import detect as pdf_detect
    results = pdf_detect(_pdf_with_field(tmp_path, "email"))
    assert any(r.get("ruleId") == "PDF_INPUT_NO_PURPOSE" for r in results), results


@needs_pikepdf
def test_pdf_first_name_field_flagged(tmp_path):
    """Field named 'first_name' → PDF_INPUT_NO_PURPOSE."""
    from formats.pdf.detectors.input_purpose import detect as pdf_detect
    results = pdf_detect(_pdf_with_field(tmp_path, "first_name"))
    assert any(r.get("ruleId") == "PDF_INPUT_NO_PURPOSE" for r in results), results


@needs_pikepdf
def test_pdf_tooltip_match_flagged(tmp_path):
    """Field with generic /T but personal-data /TU tooltip → PDF_INPUT_NO_PURPOSE."""
    from formats.pdf.detectors.input_purpose import detect as pdf_detect
    results = pdf_detect(_pdf_with_field(tmp_path, "TextField1", tooltip="Phone number"))
    assert any(r.get("ruleId") == "PDF_INPUT_NO_PURPOSE" for r in results), results


@needs_pikepdf
def test_pdf_generic_field_not_flagged(tmp_path):
    """Field named 'notes' (not a personal-data pattern) → no finding."""
    from formats.pdf.detectors.input_purpose import detect as pdf_detect
    results = pdf_detect(_pdf_with_field(tmp_path, "notes"))
    assert results == [], results


@needs_pikepdf
def test_pdf_no_fields_returns_empty(tmp_path):
    """PDF with no AcroForm → []."""
    from formats.pdf.detectors.input_purpose import detect as pdf_detect
    assert pdf_detect(_pdf_no_fields(tmp_path)) == []


@needs_pikepdf
def test_pdf_finding_wcag_tag(tmp_path):
    """Finding carries correct WCAG criterion tag."""
    from formats.pdf.detectors.input_purpose import detect as pdf_detect
    results = pdf_detect(_pdf_with_field(tmp_path, "email"))
    match = [r for r in results if r.get("ruleId") == "PDF_INPUT_NO_PURPOSE"]
    assert match and "1.3.5" in match[0].get("wcag", ""), match


@needs_pikepdf
def test_pdf_address_field_flagged(tmp_path):
    """Field named 'street address' → PDF_INPUT_NO_PURPOSE."""
    from formats.pdf.detectors.input_purpose import detect as pdf_detect
    results = pdf_detect(_pdf_with_field(tmp_path, "street address"))
    assert any(r.get("ruleId") == "PDF_INPUT_NO_PURPOSE" for r in results), results


# ── DOCX tests ────────────────────────────────────────────────────────────────────────

def test_docx_email_control_flagged(tmp_path):
    """Content control aliased 'email' → DOCX_INPUT_NO_PURPOSE."""
    results = docx_detect(_docx_with_control(tmp_path, "email"))
    assert any(r.get("ruleId") == "DOCX_INPUT_NO_PURPOSE" for r in results), results


def test_docx_phone_control_flagged(tmp_path):
    """Content control aliased 'phone' → DOCX_INPUT_NO_PURPOSE."""
    results = docx_detect(_docx_with_control(tmp_path, "phone"))
    assert any(r.get("ruleId") == "DOCX_INPUT_NO_PURPOSE" for r in results), results


def test_docx_generic_control_not_flagged(tmp_path):
    """Content control aliased 'Department' → no finding."""
    results = docx_detect(_docx_with_control(tmp_path, "Department"))
    assert results == [], results


def test_docx_no_controls_returns_empty(tmp_path):
    """DOCX with no content controls → []."""
    assert docx_detect(_docx_no_controls(tmp_path)) == []


def test_docx_finding_wcag_tag(tmp_path):
    """Finding carries correct WCAG criterion tag."""
    results = docx_detect(_docx_with_control(tmp_path, "email"))
    match = [r for r in results if r.get("ruleId") == "DOCX_INPUT_NO_PURPOSE"]
    assert match and "1.3.5" in match[0].get("wcag", ""), match


# ── Registry tests ────────────────────────────────────────────────────────────────────

def test_registry_pdf_1_3_5_declared():
    """pdf × 1.3.5 is now declared in the registry (was —)."""
    import rule_registry
    rule_registry.load()
    assert rule_registry.coverage_for("1.3.5", "pdf") is not None, (
        "1.3.5 × pdf not registered")


def test_registry_docx_1_3_5_declared():
    """docx × 1.3.5 is now declared in the registry (was —)."""
    import rule_registry
    rule_registry.load()
    assert rule_registry.coverage_for("1.3.5", "docx") is not None, (
        "1.3.5 × docx not registered")
