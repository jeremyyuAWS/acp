"""P-23: 1.3.5 Identify Input Purpose — PDF and DOCX detectors.

PDF: AcroForm terminal fields whose /T or /TU matches the WCAG personal-data vocabulary.
DOCX: interactive content controls whose w:alias (Title) matches the same vocabulary.
Coverage: HEURISTIC, Confidence: LOW for both.

Rule IDs:
  PDF_INPUT_NO_PURPOSE
  DOCX_INPUT_NO_PURPOSE
"""
from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

pikepdf = pytest.importorskip("pikepdf")

from formats.pdf.detectors.input_purpose import detect as pdf_detect          # noqa: E402
from formats.docx.detectors.input_purpose import detect as docx_detect        # noqa: E402


# ── PDF fixture helpers ────────────────────────────────────────────────────────────────

def _text_field(pdf, field_name: str, tooltip: str | None) -> pikepdf.Dictionary:
    kw = dict(
        Type=pikepdf.Name("/Annot"),
        Subtype=pikepdf.Name("/Widget"),
        FT=pikepdf.Name("/Tx"),
        T=pikepdf.String(field_name),
        Rect=pikepdf.Array([pikepdf.Real(x) for x in [72, 700, 200, 720]]),
    )
    if tooltip is not None:
        kw["TU"] = pikepdf.String(tooltip)
    return pdf.make_indirect(pikepdf.Dictionary(**kw))


def _pdf_with_field(tmp: Path, fname: str, field_name: str,
                    tooltip: str | None = None) -> Path:
    p = tmp / fname
    pdf = pikepdf.Pdf.new()
    page = pikepdf.Dictionary(Type=pikepdf.Name("/Page"), MediaBox=pikepdf.Array([0, 0, 612, 792]))
    page_ref = pdf.make_indirect(page)
    pdf.pages.append(pikepdf.Page(page_ref))
    widget = _text_field(pdf, field_name, tooltip)
    page_ref["/Annots"] = pikepdf.Array([widget])
    pdf.Root["/AcroForm"] = pdf.make_indirect(pikepdf.Dictionary(Fields=pikepdf.Array([widget])))
    pdf.save(str(p))
    return p


def _pdf_no_fields(tmp: Path) -> Path:
    p = tmp / "nofields.pdf"
    pdf = pikepdf.Pdf.new()
    page = pikepdf.Dictionary(Type=pikepdf.Name("/Page"), MediaBox=pikepdf.Array([0, 0, 612, 792]))
    pdf.pages.append(pikepdf.Page(pdf.make_indirect(page)))
    pdf.save(str(p))
    return p


# ── DOCX fixture helpers ───────────────────────────────────────────────────────────────

_DOCX_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Override PartName="/word/document.xml"'
    ' ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    '</Types>'
)
_RELS = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"'
    ' Target="word/document.xml"/>'
    '</Relationships>'
)


def _sdt_xml(alias: str, input_type: str = "date") -> str:
    return (
        f'<w:sdt>'
        f'<w:sdtPr>'
        f'<w:alias w:val="{alias}"/>'
        f'<w:{input_type}/>'
        f'</w:sdtPr>'
        f'<w:sdtContent><w:p><w:r><w:t>{alias}</w:t></w:r></w:p></w:sdtContent>'
        f'</w:sdt>'
    )


def _docx_with_sdt(tmp: Path, fname: str, alias: str, input_type: str = "date") -> Path:
    p = tmp / fname
    doc_xml = (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<w:document {_DOCX_NS}><w:body>{_sdt_xml(alias, input_type)}</w:body></w:document>'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", _CONTENT_TYPES)
        zf.writestr("_rels/.rels", _RELS)
        zf.writestr("word/document.xml", doc_xml)
    p.write_bytes(buf.getvalue())
    return p


def _docx_no_sdt(tmp: Path) -> Path:
    p = tmp / "nosdt.docx"
    doc_xml = (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<w:document {_DOCX_NS}><w:body><w:p><w:r><w:t>Hello</w:t></w:r></w:p></w:body></w:document>'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", _CONTENT_TYPES)
        zf.writestr("_rels/.rels", _RELS)
        zf.writestr("word/document.xml", doc_xml)
    p.write_bytes(buf.getvalue())
    return p


def _docx_sdt_no_input_type(tmp: Path, alias: str) -> Path:
    """SDT with alias but no recognised input-type element → not a form field."""
    p = tmp / "noninteractive.docx"
    doc_xml = (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<w:document {_DOCX_NS}><w:body>'
        f'<w:sdt><w:sdtPr><w:alias w:val="{alias}"/></w:sdtPr>'
        f'<w:sdtContent><w:p/></w:sdtContent></w:sdt>'
        f'</w:body></w:document>'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", _CONTENT_TYPES)
        zf.writestr("_rels/.rels", _RELS)
        zf.writestr("word/document.xml", doc_xml)
    p.write_bytes(buf.getvalue())
    return p


# ── PDF tests ──────────────────────────────────────────────────────────────────────────

def test_pdf_email_field_flagged(tmp_path):
    """/T = 'email' matches personal-data vocabulary → PDF_INPUT_NO_PURPOSE."""
    results = pdf_detect(_pdf_with_field(tmp_path, "email.pdf", "email"))
    assert any(r.get("ruleId") == "PDF_INPUT_NO_PURPOSE" for r in results), results


def test_pdf_name_field_flagged(tmp_path):
    """/T = 'first_name' contains 'name' → flagged."""
    results = pdf_detect(_pdf_with_field(tmp_path, "name.pdf", "first_name"))
    assert any(r.get("ruleId") == "PDF_INPUT_NO_PURPOSE" for r in results), results


def test_pdf_tooltip_preferred_over_t(tmp_path):
    """/TU overrides /T as the finding label; personal-data match on /TU triggers flag."""
    results = pdf_detect(_pdf_with_field(tmp_path, "tu.pdf", "field1", tooltip="email address"))
    assert any(r.get("ruleId") == "PDF_INPUT_NO_PURPOSE" for r in results), results


def test_pdf_unrelated_field_not_flagged(tmp_path):
    """Field name 'invoice_number' does not match vocabulary → no finding."""
    results = pdf_detect(_pdf_with_field(tmp_path, "inv.pdf", "invoice_number"))
    assert results == [], results


def test_pdf_no_fields_returns_empty(tmp_path):
    """PDF with no AcroForm → []."""
    assert pdf_detect(_pdf_no_fields(tmp_path)) == []


def test_pdf_finding_rule_id(tmp_path):
    """Finding ruleId is PDF_INPUT_NO_PURPOSE."""
    results = pdf_detect(_pdf_with_field(tmp_path, "rid.pdf", "phone_number"))
    ids = [r.get("ruleId") for r in results]
    assert "PDF_INPUT_NO_PURPOSE" in ids, ids


def test_pdf_finding_severity_moderate(tmp_path):
    """Finding severity is MODERATE."""
    results = pdf_detect(_pdf_with_field(tmp_path, "sev.pdf", "address"))
    match = [r for r in results if r.get("ruleId") == "PDF_INPUT_NO_PURPOSE"]
    assert match and match[0].get("severity") == "MODERATE", match


def test_pdf_finding_wcag_tag(tmp_path):
    """Finding carries WCAG 1.3.5 tag."""
    results = pdf_detect(_pdf_with_field(tmp_path, "wcag.pdf", "username"))
    match = [r for r in results if r.get("ruleId") == "PDF_INPUT_NO_PURPOSE"]
    assert match and "1.3.5" in match[0].get("wcag", ""), match


def test_pdf_t_only_match_flagged(tmp_path):
    """Vocabulary match on /T alone (no /TU) still triggers a finding."""
    results = pdf_detect(_pdf_with_field(tmp_path, "tonly.pdf", "postal_code"))
    assert any(r.get("ruleId") == "PDF_INPUT_NO_PURPOSE" for r in results), results


# ── DOCX tests ─────────────────────────────────────────────────────────────────────────

def test_docx_email_alias_flagged(tmp_path):
    """w:alias 'email' matches vocabulary → DOCX_INPUT_NO_PURPOSE."""
    results = docx_detect(_docx_with_sdt(tmp_path, "email.docx", "email"))
    assert any(r.get("ruleId") == "DOCX_INPUT_NO_PURPOSE" for r in results), results


def test_docx_unrelated_alias_not_flagged(tmp_path):
    """w:alias 'PO Number' does not match vocabulary → no finding."""
    results = docx_detect(_docx_with_sdt(tmp_path, "po.docx", "PO Number"))
    assert results == [], results


def test_docx_non_interactive_sdt_ignored(tmp_path):
    """SDT without a recognised input-type (date/dropdown/comboBox/checkbox) → no finding even when alias matches."""
    results = docx_detect(_docx_sdt_no_input_type(tmp_path, "email"))
    assert results == [], results


def test_docx_no_sdt_returns_empty(tmp_path):
    """Document with no structured-content-controls → []."""
    assert docx_detect(_docx_no_sdt(tmp_path)) == []


def test_docx_finding_severity_moderate(tmp_path):
    """DOCX finding severity is MODERATE."""
    results = docx_detect(_docx_with_sdt(tmp_path, "sev.docx", "address"))
    match = [r for r in results if r.get("ruleId") == "DOCX_INPUT_NO_PURPOSE"]
    assert match and match[0].get("severity") == "MODERATE", match


def test_docx_finding_wcag_tag(tmp_path):
    """DOCX finding carries WCAG 1.3.5 tag."""
    results = docx_detect(_docx_with_sdt(tmp_path, "wcag.docx", "username", input_type="comboBox"))
    match = [r for r in results if r.get("ruleId") == "DOCX_INPUT_NO_PURPOSE"]
    assert match and "1.3.5" in match[0].get("wcag", ""), match


# ── Registry tests ─────────────────────────────────────────────────────────────────────

def test_registry_1_3_5_pdf_declared():
    """pdf × 1.3.5 is declared in the registry with HEURISTIC coverage."""
    import rule_registry
    from assessment import Coverage
    rule_registry.load()
    cov = rule_registry.coverage_for("1.3.5", "pdf")
    assert cov is Coverage.HEURISTIC, f"1.3.5 × pdf should be HEURISTIC; got {cov}"


def test_registry_1_3_5_docx_declared():
    """docx × 1.3.5 is declared in the registry with HEURISTIC coverage."""
    import rule_registry
    from assessment import Coverage
    rule_registry.load()
    cov = rule_registry.coverage_for("1.3.5", "docx")
    assert cov is Coverage.HEURISTIC, f"1.3.5 × docx should be HEURISTIC; got {cov}"
