"""Assessment gap-closure: docx 1.3.2 (floating-text reading order) + xlsx 2.4.4 (vague
cell-hyperlink text) + xlsx 2.4.6 (default sheet/table labels). Detection only — these route
to human remediation. Synthetic OOXML parts are enough because office_structure reads the XML
with regexes; a full valid workbook/document is not required."""
from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import office_structure as off  # noqa: E402


def _zip(tmp_path: Path, name: str, parts: dict[str, str]) -> Path:
    p = tmp_path / name
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for path, xml in parts.items():
            zf.writestr(path, xml)
    p.write_bytes(buf.getvalue())
    return p


def _scs(findings: list[dict]) -> set[str]:
    import re
    return {re.match(r"(\d+\.\d+\.\d+)", f["wcag"]).group(1) for f in findings}


# ── docx 1.3.2 — floating text ─────────────────────────────────────────────────
def _docx(tmp_path, body: str) -> Path:
    return _zip(tmp_path, "d.docx", {"word/document.xml":
        f'<?xml version="1.0"?><w:document xmlns:w="w"><w:body>{body}</w:body></w:document>'})


def test_docx_flags_floating_textbox_reading_order(tmp_path):
    body = '<w:p><w:r><w:t>Body text.</w:t></w:r></w:p>' \
           '<w:txbxContent><w:p><w:r><w:t>Floating callout</w:t></w:r></w:p></w:txbxContent>'
    assert "1.3.2" in _scs(off.docx_checks(_docx(tmp_path, body)))


def test_docx_flags_positioned_frame(tmp_path):
    body = '<w:p><w:pPr><w:framePr w:w="2000"/></w:pPr><w:r><w:t>Sidebar</w:t></w:r></w:p>'
    assert "1.3.2" in _scs(off.docx_checks(_docx(tmp_path, body)))


def test_docx_linear_document_is_not_flagged(tmp_path):
    body = "".join(f'<w:p><w:r><w:t>Paragraph {i}.</w:t></w:r></w:p>' for i in range(6))
    assert "1.3.2" not in _scs(off.docx_checks(_docx(tmp_path, body)))


def test_docx_empty_textbox_is_not_flagged(tmp_path):
    body = '<w:p><w:r><w:t>Body.</w:t></w:r></w:p><w:txbxContent><w:p></w:p></w:txbxContent>'
    assert "1.3.2" not in _scs(off.docx_checks(_docx(tmp_path, body)))


# ── xlsx 2.4.4 — vague hyperlink text ──────────────────────────────────────────
def _xlsx(tmp_path, *, sheet="xl/worksheets/sheet1.xml", sheet_xml="<worksheet/>",
          workbook='<workbook><sheets><sheet name="Summary"/></sheets></workbook>',
          extra=None) -> Path:
    parts = {"xl/workbook.xml": workbook, sheet: sheet_xml}
    if extra:
        parts.update(extra)
    return _zip(tmp_path, "b.xlsx", parts)


def test_xlsx_flags_vague_hyperlink_text(tmp_path):
    xml = '<worksheet><hyperlinks><hyperlink ref="A1" display="click here"/></hyperlinks></worksheet>'
    assert "2.4.4" in _scs(off.xlsx_structure_checks(_xlsx(tmp_path, sheet_xml=xml)))


def test_xlsx_flags_raw_url_as_link_text(tmp_path):
    xml = '<worksheet><hyperlink ref="A1" display="https://example.com/very/long/path"/></worksheet>'
    assert "2.4.4" in _scs(off.xlsx_structure_checks(_xlsx(tmp_path, sheet_xml=xml)))


def test_xlsx_descriptive_link_text_is_not_flagged(tmp_path):
    xml = '<worksheet><hyperlink ref="A1" display="Q3 regional revenue report"/></worksheet>'
    assert "2.4.4" not in _scs(off.xlsx_structure_checks(_xlsx(tmp_path, sheet_xml=xml)))


def test_xlsx_hyperlink_without_display_is_skipped(tmp_path):
    xml = '<worksheet><hyperlink ref="A1" r:id="rId1"/></worksheet>'   # label is the cell value
    assert "2.4.4" not in _scs(off.xlsx_structure_checks(_xlsx(tmp_path, sheet_xml=xml)))


# ── xlsx 2.4.6 — default labels ────────────────────────────────────────────────
def test_xlsx_flags_multiple_default_sheet_tabs(tmp_path):
    wb = '<workbook><sheets><sheet name="Sheet1"/><sheet name="Sheet2"/></sheets></workbook>'
    assert "2.4.6" in _scs(off.xlsx_structure_checks(_xlsx(tmp_path, workbook=wb)))


def test_xlsx_flags_default_table_column(tmp_path):
    table = '<table><tableColumns><tableColumn name="Column1"/><tableColumn name="Region"/></tableColumns></table>'
    f = off.xlsx_structure_checks(_xlsx(tmp_path, extra={"xl/tables/table1.xml": table}))
    assert "2.4.6" in _scs(f)


def test_xlsx_single_default_sheet_is_not_flagged(tmp_path):
    wb = '<workbook><sheets><sheet name="Sheet1"/></sheets></workbook>'   # lone Sheet1 is normal
    assert "2.4.6" not in _scs(off.xlsx_structure_checks(_xlsx(tmp_path, workbook=wb)))


def test_xlsx_named_sheets_and_columns_are_not_flagged(tmp_path):
    wb = '<workbook><sheets><sheet name="Revenue"/><sheet name="Costs"/></sheets></workbook>'
    table = '<table><tableColumns><tableColumn name="Region"/><tableColumn name="Total"/></tableColumns></table>'
    f = off.xlsx_structure_checks(_xlsx(tmp_path, workbook=wb, extra={"xl/tables/table1.xml": table}))
    assert "2.4.6" not in _scs(f)


# ── dispatch wiring ────────────────────────────────────────────────────────────
def test_checks_for_xlsx_includes_structure_checks(tmp_path):
    xml = '<worksheet><hyperlink ref="A1" display="here"/></worksheet>'
    wb = '<workbook><sheets><sheet name="Sheet1"/><sheet name="Sheet2"/></sheets></workbook>'
    got = _scs(off.checks_for(_xlsx(tmp_path, sheet_xml=xml, workbook=wb), ".xlsx"))
    assert {"2.4.4", "2.4.6"} <= got
