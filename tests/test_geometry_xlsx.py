"""xlsx chart/image geometry — the box the review card overlays to point at the offending image.

Two charts on the same sheet used to share the same whole-sheet thumbnail, so every finding card
looked identical. shape_bbox now returns a distinct normalized rectangle per image from its cell
anchor (ADR 0018), so each card highlights its OWN chart. Derived only from the file's declared
column widths / row heights + the drawing anchors (ADR 0016: approximate, but the right region).
"""
import io
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
import geometry  # noqa: E402

_SHEET = (
    '<?xml version="1.0"?>'
    '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    '<dimension ref="A1:B24"/><sheetFormatPr baseColWidth="8" defaultRowHeight="15"/>'
    '<cols><col width="22" customWidth="1" min="1" max="1"/>'
    '<col width="16" customWidth="1" min="2" max="2"/></cols><sheetData/></worksheet>'
)
_SHEET_RELS = (
    '<?xml version="1.0"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing" '
    'Target="/xl/drawings/drawing1.xml"/></Relationships>'
)


def _anchor(col, row, rid, name):
    return (
        f'<oneCellAnchor><from><col>{col}</col><colOff>0</colOff>'
        f'<row>{row}</row><rowOff>0</rowOff></from><ext cx="6286500" cy="4000500"/>'
        f'<pic><nvPicPr><cNvPr id="{rid[-1]}" name="{name}" descr="Picture"/><cNvPicPr/></nvPicPr>'
        f'<blipFill><a:blip xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        f'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        f'r:embed="{rid}"/></blipFill></pic></oneCellAnchor>'
    )


def _drawing():
    return (
        '<?xml version="1.0"?>'
        '<wsDr xmlns="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing">'
        + _anchor(3, 2, "rId1", "Image 1") + _anchor(3, 25, "rId2", "Image 2") + '</wsDr>'
    )


def _xlsx() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types/>')
        z.writestr("xl/worksheets/sheet1.xml", _SHEET)
        z.writestr("xl/worksheets/_rels/sheet1.xml.rels", _SHEET_RELS)
        z.writestr("xl/drawings/drawing1.xml", _drawing())
    return buf.getvalue()


def test_each_image_gets_its_own_distinct_box():
    data = _xlsx()
    b1 = geometry.shape_bbox(data, ".xlsx", "xl/drawings/drawing1.xml#rId1")
    b2 = geometry.shape_bbox(data, ".xlsx", "xl/drawings/drawing1.xml#rId2")
    assert b1 and b2
    for b in (b1, b2):
        assert b["page"] == 1
        for k in ("x", "y", "w", "h"):
            assert 0.0 <= b[k] <= 1.0
        assert b["w"] > 0 and b["h"] > 0
    # the charts sit at the same column but different rows → same x, DIFFERENT y (not identical)
    assert b1["x"] == b2["x"]
    assert b2["y"] > b1["y"] + 0.2            # image 2 is clearly lower on the sheet
    # both charts are parked right of the two data columns → left edge well past 0
    assert b1["x"] > 0.2


def test_resolves_by_shape_name_too():
    data = _xlsx()
    by_rid = geometry.shape_bbox(data, ".xlsx", "xl/drawings/drawing1.xml#rId1")
    by_name = geometry.shape_bbox(data, ".xlsx", "xl/drawings/drawing1.xml#Image 1")
    assert by_rid == by_name and by_rid is not None


def test_unknown_locator_and_wrong_format_return_none():
    data = _xlsx()
    assert geometry.shape_bbox(data, ".xlsx", "xl/drawings/drawing1.xml#rId99") is None
    assert geometry.shape_bbox(data, ".docx", "xl/drawings/drawing1.xml#rId1") is None
    assert geometry.shape_bbox(data, ".xlsx", "no-hash-here") is None
