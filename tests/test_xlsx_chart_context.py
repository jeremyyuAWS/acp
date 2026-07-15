"""Keyless chart alt drafted from the sheet's own data table (no vision model).

When an xlsx chart has no alt and vision is unavailable, the numbers it plots are in the cells next
to it. chart_alt_draft composes an approvable draft from the nearest data table — grounded in the
document's real values, offered as a proposal the reviewer confirms against the visible chart.
"""
import io
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
import xlsx_chart_context as xcc  # noqa: E402

_M = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_PKG = "http://schemas.openxmlformats.org/package/2006/relationships"


def _sst(*strings):
    si = "".join(f"<si><t>{s}</t></si>" for s in strings)
    return f'<?xml version="1.0"?><sst xmlns="{_M}">{si}</sst>'


def _sheet(rows):
    body = ""
    for r, cells in rows:                              # cells: list of (ref, value, is_str_idx|None)
        cs = ""
        for ref, val, sidx in cells:
            if sidx is not None:
                cs += f'<c r="{ref}" t="s"><v>{sidx}</v></c>'
            else:
                cs += f'<c r="{ref}"><v>{val}</v></c>'
        body += f'<row r="{r}">{cs}</row>'
    return f'<?xml version="1.0"?><worksheet xmlns="{_M}"><sheetData>{body}</sheetData></worksheet>'


def _sheet_rels(drawing="drawing1.xml"):
    return (f'<?xml version="1.0"?><Relationships xmlns="{_PKG}">'
            f'<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
            f'relationships/drawing" Target="/xl/drawings/{drawing}"/></Relationships>')


def _anchor(col, row, rid, name):
    return (f'<oneCellAnchor><from><col>{col}</col><colOff>0</colOff>'
            f'<row>{row}</row><rowOff>0</rowOff></from><ext cx="6286500" cy="4000500"/>'
            f'<pic><nvPicPr><cNvPr id="{rid[-1]}" name="{name}"/><cNvPicPr/></nvPicPr>'
            f'<blipFill><a:blip xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
            f'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
            f'r:embed="{rid}"/></blipFill></pic></oneCellAnchor>')


def _drawing(*anchors):
    return ('<?xml version="1.0"?><wsDr xmlns="http://schemas.openxmlformats.org/drawingml/2006/'
            'spreadsheetDrawing">' + "".join(anchors) + '</wsDr>')


def _xlsx(sst, sheet, drawing) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types/>')
        z.writestr("xl/sharedStrings.xml", sst)
        z.writestr("xl/worksheets/sheet1.xml", sheet)
        z.writestr("xl/worksheets/_rels/sheet1.xml.rels", _sheet_rels())
        z.writestr("xl/drawings/drawing1.xml", drawing)
    return buf.getvalue()


def test_drafts_from_the_adjacent_data_table():
    sst = _sst("Region", "Revenue", "North", "South", "East", "West")
    sheet = _sheet([
        (1, [("A1", None, 0), ("B1", None, 1)]),
        (2, [("A2", None, 2), ("B2", "12.4", None)]),
        (3, [("A3", None, 3), ("B3", "9.8", None)]),
        (4, [("A4", None, 4), ("B4", "15.1", None)]),
        (5, [("A5", None, 5), ("B5", "7.6", None)]),
    ])
    data = _xlsx(sst, sheet, _drawing(_anchor(3, 1, "rId1", "Image 1")))
    draft, source = xcc.chart_alt_draft(data, "xl/drawings/drawing1.xml", "rId1")
    assert draft == "Chart of Revenue by Region: North 12.4, South 9.8, East 15.1, West 7.6."
    assert "data table" in source


def test_two_charts_match_their_nearest_table():
    sst = _sst("Region", "Rev", "North", "South", "Qtr", "Units", "Q1", "Q2")
    sheet = _sheet([
        (1, [("A1", None, 0), ("B1", None, 1)]),                    # Region/Rev header
        (2, [("A2", None, 2), ("B2", "12", None)]),
        (3, [("A3", None, 3), ("B3", "10", None)]),
        (20, [("A20", None, 4), ("B20", None, 5)]),                 # Qtr/Units header (far below)
        (21, [("A21", None, 6), ("B21", "50", None)]),
        (22, [("A22", None, 7), ("B22", "70", None)]),
    ])
    drawing = _drawing(_anchor(3, 1, "rId1", "Image 1"),           # top → Region table
                       _anchor(3, 19, "rId2", "Image 2"))          # bottom → Qtr table
    data = _xlsx(sst, sheet, drawing)
    d1, _ = xcc.chart_alt_draft(data, "xl/drawings/drawing1.xml", "rId1")
    d2, _ = xcc.chart_alt_draft(data, "xl/drawings/drawing1.xml", "rId2")
    assert d1 == "Chart of Rev by Region: North 12, South 10."
    assert d2 == "Chart of Units by Qtr: Q1 50, Q2 70."


def test_no_data_table_or_unknown_rid_returns_none():
    sst = _sst("Just a title")
    sheet = _sheet([(1, [("A1", None, 0)])])                       # a lone label, no table
    data = _xlsx(sst, sheet, _drawing(_anchor(3, 1, "rId1", "Image 1")))
    assert xcc.chart_alt_draft(data, "xl/drawings/drawing1.xml", "rId1") is None
    # a real table but the wrong id
    sst2 = _sst("Region", "Rev", "North", "South")
    sheet2 = _sheet([(1, [("A1", None, 0), ("B1", None, 1)]),
                     (2, [("A2", None, 2), ("B2", "12", None)]),
                     (3, [("A3", None, 3), ("B3", "10", None)])])
    data2 = _xlsx(sst2, sheet2, _drawing(_anchor(3, 1, "rId1", "Image 1")))
    assert xcc.chart_alt_draft(data2, "xl/drawings/drawing1.xml", "rId99") is None
