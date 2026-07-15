"""xlsx 2.4.6 Headings & Labels — AI names default 'SheetN' tabs and 'ColumnN' table columns
from their own content. Naming is drafting; a human approves. Gates mirror the detector
(>= 2 default sheet tabs, or a default table column)."""
from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import proposals  # noqa: E402

_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _xlsx(tmp: Path, *, sheets, shared=None, tables=None) -> Path:
    """sheets: [(name, rId, worksheet_xml)]; tables: {part: xml}."""
    p = tmp / "b.xlsx"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        wb = "<workbook><sheets>" + "".join(
            f'<sheet name="{n}" sheetId="{i+1}" r:id="{rid}"/>' for i, (n, rid, _) in enumerate(sheets)
        ) + "</sheets></workbook>"
        z.writestr("xl/workbook.xml", wb)
        rels = f'<Relationships xmlns="{_R}">' + "".join(
            f'<Relationship Id="{rid}" Type="{_R}/worksheet" Target="worksheets/sheet{i+1}.xml"/>'
            for i, (_, rid, _) in enumerate(sheets)) + "</Relationships>"
        z.writestr("xl/_rels/workbook.xml.rels", rels)
        for i, (_, _, ws) in enumerate(sheets):
            z.writestr(f"xl/worksheets/sheet{i+1}.xml", ws)
        if shared:
            z.writestr("xl/sharedStrings.xml",
                       "<sst>" + "".join(f"<si><t>{s}</t></si>" for s in shared) + "</sst>")
        for part, xml in (tables or {}).items():
            z.writestr(part, xml)
    p.write_bytes(buf.getvalue())
    return p


def _mock_ai(monkeypatch, suggestion="Regional Revenue"):
    import ai
    monkeypatch.setattr(ai, "is_available", lambda: True)
    monkeypatch.setattr(ai, "suggest_fix", lambda *a, **k: {"suggestion": suggestion, "model": "llama3.2"})


def test_two_default_sheets_get_ai_named_from_content(tmp_path, monkeypatch):
    _mock_ai(monkeypatch, "Regional Revenue")
    # shared strings: 0="Region", 1="North", 2="Revenue"
    ws = '<worksheet><sheetData><row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>2</v></c></row>' \
         '<row r="2"><c r="A2" t="s"><v>1</v></c></row></sheetData></worksheet>'
    src = _xlsx(tmp_path, sheets=[("Sheet1", "rId1", ws), ("Sheet2", "rId2", ws)],
               shared=["Region", "North", "Revenue"])
    out = proposals.propose_xlsx_labels(src, ".xlsx")
    assert len(out) == 2                                   # one per default sheet tab
    assert out[0]["proposed_value"] == "Regional Revenue"
    assert out[0]["locator"].startswith("sheet:Sheet")


def test_a_single_default_sheet_is_not_proposed(tmp_path, monkeypatch):
    _mock_ai(monkeypatch)
    ws = '<worksheet><sheetData><row r="1"><c r="A1" t="s"><v>0</v></c></row></sheetData></worksheet>'
    src = _xlsx(tmp_path, sheets=[("Sheet1", "rId1", ws)], shared=["Data"])
    assert proposals.propose_xlsx_labels(src, ".xlsx") == []   # lone Sheet1 is normal (detector gate)


def test_named_sheets_yield_nothing(tmp_path, monkeypatch):
    _mock_ai(monkeypatch)
    ws = '<worksheet><sheetData/></worksheet>'
    src = _xlsx(tmp_path, sheets=[("Revenue", "rId1", ws), ("Costs", "rId2", ws)])
    assert proposals.propose_xlsx_labels(src, ".xlsx") == []


def test_default_table_column_gets_a_proposal(tmp_path, monkeypatch):
    _mock_ai(monkeypatch, "Region")
    ws = '<worksheet><sheetData>' \
         '<row r="2"><c r="A2" t="s"><v>0</v></c></row>' \
         '<row r="3"><c r="A3" t="s"><v>1</v></c></row></sheetData></worksheet>'
    tbl = '<table displayName="Sales" ref="A1:B4"><tableColumns>' \
          '<tableColumn name="Column1"/><tableColumn name="Total"/></tableColumns></table>'
    src = _xlsx(tmp_path, sheets=[("Data", "rId1", ws)], shared=["North", "South"],
                tables={"xl/tables/table1.xml": tbl})
    out = proposals.propose_xlsx_labels(src, ".xlsx")
    assert any(p["locator"] == "table:Sales#col:Column1" for p in out)


def test_ai_off_yields_nothing(tmp_path):
    ws = '<worksheet><sheetData/></worksheet>'
    src = _xlsx(tmp_path, sheets=[("Sheet1", "rId1", ws), ("Sheet2", "rId2", ws)])
    assert proposals.propose_xlsx_labels(src, ".xlsx", ai_enabled=False) == []
