"""Tests for apply_xlsx_labels — the write-back for 2.4.6 sheet tab / table column labels."""
from __future__ import annotations

import io
import re
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import apply_xlsx_labels as _mod  # noqa: E402

_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _xlsx(*, sheets: list[tuple[str, str]], tables: dict[str, str] | None = None) -> bytes:
    """Build a minimal xlsx with the given sheets=[(name, rId)] and optional table XML."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        wb = ("<workbook><sheets>"
              + "".join(f'<sheet name="{n}" sheetId="{i+1}" r:id="{rid}"/>'
                        for i, (n, rid) in enumerate(sheets))
              + "</sheets></workbook>")
        z.writestr("xl/workbook.xml", wb)
        rels = (f'<Relationships xmlns="{_R}">'
                + "".join(f'<Relationship Id="{rid}" Type="{_R}/worksheet"'
                          f' Target="worksheets/sheet{i+1}.xml"/>'
                          for i, (_, rid) in enumerate(sheets))
                + "</Relationships>")
        z.writestr("xl/_rels/workbook.xml.rels", rels)
        for i, _ in enumerate(sheets):
            z.writestr(f"xl/worksheets/sheet{i+1}.xml", "<worksheet><sheetData/></worksheet>")
        for part, xml in (tables or {}).items():
            z.writestr(part, xml)
    return buf.getvalue()


def _read_workbook(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return z.read("xl/workbook.xml").decode()


def _read_part(data: bytes, part: str) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return z.read(part).decode()


# ── sheet tab rename ────────────────────────────────────────────────────────────

def test_rename_single_sheet_tab():
    data = _xlsx(sheets=[("Sheet1", "rId1"), ("Sheet2", "rId2")])
    fixed, applied, unresolved = _mod.apply_xlsx_labels(data, {"sheet:Sheet1": "Revenue"})
    wb = _read_workbook(fixed)
    assert 'name="Revenue"' in wb
    assert 'name="Sheet1"' not in wb
    assert 'name="Sheet2"' in wb           # untouched
    assert len(applied) == 1
    assert applied[0] == {"locator": "sheet:Sheet1", "before": "Sheet1", "after": "Revenue"}
    assert unresolved == []


def test_rename_both_default_sheets():
    data = _xlsx(sheets=[("Sheet1", "rId1"), ("Sheet2", "rId2")])
    fixed, applied, unresolved = _mod.apply_xlsx_labels(
        data, {"sheet:Sheet1": "Revenue", "sheet:Sheet2": "Costs"})
    wb = _read_workbook(fixed)
    assert 'name="Revenue"' in wb
    assert 'name="Costs"' in wb
    assert 'name="Sheet1"' not in wb
    assert 'name="Sheet2"' not in wb
    assert len(applied) == 2
    assert unresolved == []


def test_sheet_not_found_goes_to_unresolved():
    data = _xlsx(sheets=[("Revenue", "rId1")])   # already named — not a target
    fixed, applied, unresolved = _mod.apply_xlsx_labels(data, {"sheet:Sheet1": "Revenue"})
    assert applied == []
    assert "sheet:Sheet1" in unresolved


def test_empty_values_returns_original():
    data = _xlsx(sheets=[("Sheet1", "rId1")])
    fixed, applied, unresolved = _mod.apply_xlsx_labels(data, {})
    assert fixed is data
    assert applied == [] and unresolved == []


# ── table column rename ─────────────────────────────────────────────────────────

def _table_xml(display_name: str, cols: list[str]) -> str:
    col_tags = "".join(f'<tableColumn name="{c}"/>' for c in cols)
    return f'<table displayName="{display_name}" ref="A1:B4"><tableColumns>{col_tags}</tableColumns></table>'


def test_rename_table_column():
    tbl = _table_xml("Sales", ["Column1", "Total"])
    data = _xlsx(sheets=[("Data", "rId1")], tables={"xl/tables/table1.xml": tbl})
    fixed, applied, unresolved = _mod.apply_xlsx_labels(
        data, {"table:Sales#col:Column1": "Region"})
    xml = _read_part(fixed, "xl/tables/table1.xml")
    assert 'name="Region"' in xml
    assert 'name="Column1"' not in xml
    assert 'name="Total"' in xml           # untouched
    assert applied[0]["locator"] == "table:Sales#col:Column1"
    assert unresolved == []


def test_wrong_table_name_goes_to_unresolved():
    tbl = _table_xml("Expenses", ["Column1"])
    data = _xlsx(sheets=[("Data", "rId1")], tables={"xl/tables/table1.xml": tbl})
    fixed, applied, unresolved = _mod.apply_xlsx_labels(
        data, {"table:Sales#col:Column1": "Region"})
    assert applied == []
    assert "table:Sales#col:Column1" in unresolved


def test_sheet_and_table_in_one_call():
    tbl = _table_xml("Sales", ["Column1"])
    data = _xlsx(sheets=[("Sheet1", "rId1"), ("Sheet2", "rId2")],
                 tables={"xl/tables/table1.xml": tbl})
    fixed, applied, unresolved = _mod.apply_xlsx_labels(
        data,
        {"sheet:Sheet1": "Revenue", "sheet:Sheet2": "Costs", "table:Sales#col:Column1": "Region"})
    wb = _read_workbook(fixed)
    assert 'name="Revenue"' in wb
    assert 'name="Costs"' in wb
    txml = _read_part(fixed, "xl/tables/table1.xml")
    assert 'name="Region"' in txml
    assert len(applied) == 3
    assert unresolved == []


def test_xml_special_chars_escaped_in_name():
    data = _xlsx(sheets=[("Sheet1", "rId1")])
    fixed, applied, _ = _mod.apply_xlsx_labels(data, {"sheet:Sheet1": 'R&D "Results"'})
    wb = _read_workbook(fixed)
    assert 'name="R&amp;D &quot;Results&quot;"' in wb
    assert applied[0]["after"] == 'R&D "Results"'


def test_corrupt_input_returns_original():
    bad = b"not a zip"
    fixed, applied, unresolved = _mod.apply_xlsx_labels(bad, {"sheet:Sheet1": "X"})
    assert fixed is bad
    assert applied == []
    assert "sheet:Sheet1" in unresolved
