"""P-21: link-purpose coverage gaps — PDF vague phrases + xlsx cell-value labels.

Two extensions to the existing 2.4.4 detectors:

  1. PDF vague phrases — pdfplumber bounding-box crop extracts the visible link text and
     runs it through the same _VAGUE_LINK_TEXT predicate used for docx/pptx/xlsx.  Previously
     only raw URLs appearing verbatim in page text were caught.

  2. xlsx cell-value labels — when a <hyperlink> tag has no display= attribute the visible
     label comes from the cell value.  Previously those links were silently skipped.
"""
from __future__ import annotations

import re
import sys
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

reportlab = pytest.importorskip("reportlab")

import office_structure as off  # noqa: E402


# ─── PDF helpers ──────────────────────────────────────────────────────────────

def _pdf_with_link(tmp: Path, name: str, label: str, url: str) -> Path:
    """One-page PDF: `label` drawn as text, a /Link annotation over it pointing at `url`."""
    from reportlab.pdfgen import canvas as rl_canvas
    p = tmp / name
    c = rl_canvas.Canvas(str(p))
    c.setFont("Helvetica", 12)
    c.drawString(72, 700, label)
    c.linkURL(url, (72, 695, 72 + 6 * len(label), 715), relative=0)
    c.save()
    return p


# ─── PDF tests ────────────────────────────────────────────────────────────────

def test_pdf_vague_phrase_link_is_flagged(tmp_path):
    pytest.importorskip("pdfplumber")
    p = _pdf_with_link(tmp_path, "vague.pdf", "click here", "https://example.com/report")
    results = off.pdf_link_purpose_check(p)
    scs = {r.get("wcag", "") for r in results}
    assert "2.4.4 Link Purpose (In Context)" in scs, (
        "vague link text 'click here' in PDF was not detected")
    rule_ids = {r.get("ruleId", "") for r in results}
    assert "PDF_LINK_PURPOSE_VAGUE" in rule_ids


def test_pdf_vague_phrase_detail_names_the_example(tmp_path):
    pytest.importorskip("pdfplumber")
    p = _pdf_with_link(tmp_path, "vague2.pdf", "read more", "https://example.com/details")
    results = off.pdf_link_purpose_check(p)
    vague = [r for r in results if r.get("ruleId") == "PDF_LINK_PURPOSE_VAGUE"]
    assert vague, "PDF_LINK_PURPOSE_VAGUE finding missing"
    assert "read more" in vague[0].get("detail", "").lower()


def test_pdf_raw_url_link_still_flagged(tmp_path):
    pytest.importorskip("pdfplumber")
    url = "https://example.org/annual-report-2026"
    p = _pdf_with_link(tmp_path, "rawurl.pdf", url, url)
    results = off.pdf_link_purpose_check(p)
    rule_ids = {r.get("ruleId", "") for r in results}
    assert "PDF_LINK_RAW_URL" in rule_ids, "existing raw-URL detection regressed"


def test_pdf_descriptive_link_not_flagged(tmp_path):
    pytest.importorskip("pdfplumber")
    p = _pdf_with_link(
        tmp_path, "good.pdf", "Read the 2026 annual report",
        "https://example.org/annual-report-2026")
    results = off.pdf_link_purpose_check(p)
    assert results == [], f"descriptive link text was wrongly flagged: {results}"


def test_pdf_both_rule_ids_are_explain_only_no_proposer():
    src = (ROOT / "api" / "remediate_pdf.py").read_text()
    assert "PDF_LINK_PURPOSE_VAGUE" not in src, (
        "PDF_LINK_PURPOSE_VAGUE must not appear in remediate_pdf.py — "
        "link text is drawn in glyph operators and cannot be patched by a writer")


# ─── xlsx helpers ─────────────────────────────────────────────────────────────

def _xlsx(sheets: dict[str, tuple[list[str], list[tuple[str, str, str | None]]]],
          tmp: Path, name: str = "test.xlsx") -> Path:
    """Minimal xlsx: sheets = {sheet_name: (shared_strings, rows)}.
    rows = list of (cell_ref, cell_type, value) tuples — cell_type is '' / 's' / 'str'.
    Hyperlinks are added separately via the _add_hyperlinks kwarg pattern — see helpers below.
    """
    raise NotImplementedError("use _xlsx_with_hyperlink directly")


def _xlsx_bytes(
    cell_ref: str,
    cell_value: str,
    cell_type: str,
    shared_strings: list[str],
    hyperlink_display: str | None,
) -> bytes:
    """Return in-memory xlsx bytes with one cell and one hyperlink over it."""
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        # [Content_Types].xml
        zf.writestr("[Content_Types].xml", """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Override PartName="/xl/workbook.xml"
    ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml"
    ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/sharedStrings.xml"
    ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>
</Types>""")
        # _rels/.rels
        zf.writestr("_rels/.rels", """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
    Target="xl/workbook.xml"/>
</Relationships>""")
        # xl/_rels/workbook.xml.rels
        zf.writestr("xl/_rels/workbook.xml.rels", """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"
    Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings"
    Target="sharedStrings.xml"/>
</Relationships>""")
        # xl/workbook.xml
        zf.writestr("xl/workbook.xml", """<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"
    xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"/></sheets>
</workbook>""")
        # xl/sharedStrings.xml
        ss_items = "".join(f"<si><t>{s}</t></si>" for s in shared_strings)
        zf.writestr("xl/sharedStrings.xml",
                    f'<?xml version="1.0" encoding="UTF-8"?>'
                    f'<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                    f'{ss_items}</sst>')
        # xl/worksheets/_rels/sheet1.xml.rels  (hyperlink relationship)
        zf.writestr("xl/worksheets/_rels/sheet1.xml.rels", """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink"
    Target="https://example.com" TargetMode="External"/>
</Relationships>""")
        # xl/worksheets/sheet1.xml
        t_attr = f' t="{cell_type}"' if cell_type else ""
        display_attr = f' display="{hyperlink_display}"' if hyperlink_display is not None else ""
        cell_xml = f'<c r="{cell_ref}"{t_attr}><v>{cell_value}</v></c>'
        hl_xml = f'<hyperlink ref="{cell_ref}" r:id="rId1"{display_attr}/>'
        zf.writestr("xl/worksheets/sheet1.xml",
                    '<?xml version="1.0" encoding="UTF-8"?>'
                    '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
                    ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                    f'<sheetData><row r="1">{cell_xml}</row></sheetData>'
                    f'<hyperlinks>{hl_xml}</hyperlinks>'
                    '</worksheet>')
    buf.seek(0)
    return buf.read()


def _xlsx_file(tmp: Path, cell_ref: str, cell_value: str, cell_type: str,
               shared_strings: list[str], hyperlink_display: str | None,
               name: str = "test.xlsx") -> Path:
    p = tmp / name
    p.write_bytes(_xlsx_bytes(cell_ref, cell_value, cell_type, shared_strings, hyperlink_display))
    return p


# ─── xlsx tests ───────────────────────────────────────────────────────────────

def test_xlsx_explicit_vague_display_still_flagged(tmp_path):
    """Existing behaviour: display='click here' on the hyperlink tag is flagged."""
    p = _xlsx_file(tmp_path, "A1", "0", "", [], hyperlink_display="click here")
    results = off.xlsx_structure_checks(p)
    rule_ids = {r.get("ruleId", "") for r in results}
    assert "XLSX_LINK_PURPOSE_VAGUE" in rule_ids


def test_xlsx_cell_value_vague_no_display_is_flagged(tmp_path):
    """New: no display= attribute — cell value 'click here' (shared string) is the label."""
    p = _xlsx_file(tmp_path, "A1", "0", "s", ["click here"], hyperlink_display=None)
    results = off.xlsx_structure_checks(p)
    rule_ids = {r.get("ruleId", "") for r in results}
    assert "XLSX_LINK_PURPOSE_VAGUE" in rule_ids, (
        "cell-value label 'click here' with no display= was not flagged")


def test_xlsx_cell_value_raw_url_no_display_is_flagged(tmp_path):
    """New: cell value is a raw URL → also vague by _is_vague_link_text."""
    p = _xlsx_file(tmp_path, "B2", "0", "s", ["https://example.com/page"],
                   hyperlink_display=None, name="rawurl.xlsx")
    results = off.xlsx_structure_checks(p)
    rule_ids = {r.get("ruleId", "") for r in results}
    assert "XLSX_LINK_PURPOSE_VAGUE" in rule_ids


def test_xlsx_cell_value_descriptive_no_display_not_flagged(tmp_path):
    """New (negative): descriptive cell value must not be flagged."""
    p = _xlsx_file(tmp_path, "A1", "0", "s", ["Read the 2026 Annual Report"],
                   hyperlink_display=None, name="good.xlsx")
    results = off.xlsx_structure_checks(p)
    rule_ids = {r.get("ruleId", "") for r in results}
    assert "XLSX_LINK_PURPOSE_VAGUE" not in rule_ids


def test_xlsx_numeric_cell_no_display_not_flagged(tmp_path):
    """Numeric cells cannot be link labels — must never produce a false positive."""
    p = _xlsx_file(tmp_path, "A1", "42", "", [], hyperlink_display=None, name="num.xlsx")
    results = off.xlsx_structure_checks(p)
    rule_ids = {r.get("ruleId", "") for r in results}
    assert "XLSX_LINK_PURPOSE_VAGUE" not in rule_ids


def test_xlsx_str_type_cell_no_display_flagged(tmp_path):
    """t='str' (formula string result) cell value also resolved."""
    p = _xlsx_file(tmp_path, "A1", "here", "str", [], hyperlink_display=None, name="str.xlsx")
    results = off.xlsx_structure_checks(p)
    rule_ids = {r.get("ruleId", "") for r in results}
    assert "XLSX_LINK_PURPOSE_VAGUE" in rule_ids
