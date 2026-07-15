"""Per-shape geometry for the bounding-box overlay (ADR 0018 Slice 2).

Given a document + a finding's `part#rId` locator, return the offending shape's rectangle as
NORMALIZED page fractions `{page, x, y, w, h}` — each in [0,1], fraction of page width/height —
the primitive the frontend overlays on the large page preview (`render.render_page_png`).

Honesty first (ADR 0016): a box drawn in the wrong place is worse than none. So this returns a
rectangle ONLY when it can be read as a real, unambiguous transform straight from the file:

  * pptx — a top-level `<p:pic>` with an explicit `<a:xfrm>` (off + ext), normalized by the slide
    size, page = its 1-based position in the presentation's `sldIdLst` (the order LibreOffice
    renders, so the box lands on the right page). A picture nested in a group, or one that inherits
    its layout placeholder's transform (no own `<a:xfrm>`), returns None — we do not compose or
    guess a rectangle.
  * docx / xlsx / pdf — no attributable shape rectangle yet (inline-flow / cell-anchored /
    tagged-figure geometry is a later slice), so None. The card falls back to the plain large
    preview, exactly as before.

Pure and dependency-light (zipfile + ElementTree from the stdlib): bytes in, dict|None out — no DB,
no network, never raises. Mirrors render.py so it unit-tests against a corpus deck directly.
"""
from __future__ import annotations

import re
import zipfile
from xml.etree import ElementTree as ET

_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_RELS = "http://schemas.openxmlformats.org/package/2006/relationships"

_PPTX_SLIDE = re.compile(r"^ppt/slides/slide\d+\.xml$")

# xlsx spreadsheet-drawing geometry. The anchor elements live in the spreadsheetDrawing namespace
# whether the file prefixes them (`<xdr:from>`, Excel) or uses the default namespace (`<from>`, many
# generators) — ElementTree matches by URI, so one set of tags covers both flavours.
_SS = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
_SML = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_XLSX_DRAWING = re.compile(r"^xl/drawings/drawing\d+\.xml$")
_XLSX_SHEET_RELS = re.compile(r"^xl/worksheets/_rels/sheet\d+\.xml\.rels$")
_EMU_PER_PX = 9525          # 96 dpi: 914400 EMU/inch ÷ 96
_MDW = 7                    # max-digit-width px of the default font (Calibri 11) — Excel's width unit


def shape_bbox(data: bytes, ext: str, locator: str | None) -> dict | None:
    """Normalized `{page, x, y, w, h}` for the shape a `part_name#rId` locator names, or None.

    Never raises: any parse/lookup failure — bad locator, missing shape, grouped/inherited
    transform, unsupported format — degrades to None (no box), per ADR 0016/0018."""
    try:
        e = (ext or "").lower()
        if not data or not locator or "#" not in locator:
            return None
        part_name, rid = locator.rsplit("#", 1)
        with zipfile.ZipFile(_io(data)) as z:
            names = set(z.namelist())
            if part_name not in names:
                return None
            if e == ".pptx" and _PPTX_SLIDE.match(part_name):
                return _pptx_shape_bbox(z, names, part_name, rid)
            if e == ".xlsx" and _XLSX_DRAWING.match(part_name):
                return _xlsx_shape_bbox(z, names, part_name, rid)
            return None
    except Exception:
        return None


def _pptx_shape_bbox(z, names, part_name, rid):
    slide_xml = z.read(part_name)
    rect = _pic_rect_by_embed(slide_xml, rid)
    if rect is None:
        return None
    sw, sh = _slide_size(z, names)
    if not sw or not sh:
        return None
    page = _slide_page_number(z, names, part_name)
    if page is None:
        return None
    off_x, off_y, cx, cy = rect
    box = {"page": page, "x": _clip(off_x / sw), "y": _clip(off_y / sh),
           "w": _clip(cx / sw), "h": _clip(cy / sh)}
    # A degenerate rectangle (zero area, or normalized to nothing) is not a usable box.
    if box["w"] <= 0.0 or box["h"] <= 0.0:
        return None
    return box


def _io(data: bytes):
    import io
    return io.BytesIO(data)


def _clip(v: float) -> float:
    return 0.0 if v < 0 else (1.0 if v > 1 else round(v, 5))


def _pic_rect_by_embed(slide_xml: bytes, rid: str) -> tuple[int, int, int, int] | None:
    """(off.x, off.y, ext.cx, ext.cy) in EMU for the TOP-LEVEL `<p:pic>` the locator fragment
    names — matched by its blip's r:embed (`#rId3`, the vision/evidence path) OR by its
    `<p:cNvPr>` shape name (`#Picture 61`, the decorative / faithful-name proposal path).
    remediate_office emits both fragment styles; matching only the rId left every name-style
    card with no bounding box and no page attribution.

    Only pictures that are direct children of the slide's shape tree are considered — a picture
    inside a `<p:grpSp>` has a group-relative transform we would have to compose, so it returns
    None rather than a wrong box. A picture without its own `<a:xfrm>` (inherited placeholder
    geometry) likewise returns None."""
    root = ET.fromstring(slide_xml)
    sp_tree = root.find(f"{{{_P}}}cSld/{{{_P}}}spTree")
    if sp_tree is None:
        return None
    for pic in sp_tree.findall(f"{{{_P}}}pic"):        # direct children only — no descendants
        blip = pic.find(f"{{{_P}}}blipFill/{{{_A}}}blip")
        embed = blip.get(f"{{{_R}}}embed") if blip is not None else None
        cnv = pic.find(f"{{{_P}}}nvPicPr/{{{_P}}}cNvPr")
        name = (cnv.get("name") or "").strip() if cnv is not None else None
        if rid != embed and (not name or rid != name):
            continue
        xfrm = pic.find(f"{{{_P}}}spPr/{{{_A}}}xfrm")
        if xfrm is None:
            return None
        off = xfrm.find(f"{{{_A}}}off")
        extt = xfrm.find(f"{{{_A}}}ext")
        if off is None or extt is None:
            return None
        try:
            return (int(off.get("x")), int(off.get("y")),
                    int(extt.get("cx")), int(extt.get("cy")))
        except (TypeError, ValueError):
            return None
    return None


def _slide_size(z: zipfile.ZipFile, names: set[str]) -> tuple[int, int]:
    """Slide canvas size (cx, cy) in EMU from presentation.xml `<p:sldSz>`; (0,0) if unreadable."""
    if "ppt/presentation.xml" not in names:
        return (0, 0)
    root = ET.fromstring(z.read("ppt/presentation.xml"))
    sz = root.find(f"{{{_P}}}sldSz")
    if sz is None:
        return (0, 0)
    try:
        return (int(sz.get("cx")), int(sz.get("cy")))
    except (TypeError, ValueError):
        return (0, 0)


def _slide_page_number(z: zipfile.ZipFile, names: set[str], part_name: str) -> int | None:
    """1-based render page for a slide part, = its position in presentation.xml `<p:sldIdLst>`.

    Resolves each `<p:sldId r:id>` through ppt/_rels/presentation.xml.rels to its slideN.xml target
    so the page matches the presentation ORDER LibreOffice renders — not the file-name number, which
    can differ. Falls back to None (no page → no box) if the relationship graph can't be read."""
    if "ppt/presentation.xml" not in names or "ppt/_rels/presentation.xml.rels" not in names:
        return None
    rels = {}
    rroot = ET.fromstring(z.read("ppt/_rels/presentation.xml.rels"))
    for rel in rroot.findall(f"{{{_RELS}}}Relationship"):
        rid, tgt = rel.get("Id"), rel.get("Target")
        if not rid or not tgt:
            continue
        tgt = tgt.split("/")[-1]                        # "slides/slide3.xml" | "../slides/slide3.xml"
        rels[rid] = f"ppt/slides/{tgt}"
    proot = ET.fromstring(z.read("ppt/presentation.xml"))
    lst = proot.find(f"{{{_P}}}sldIdLst")
    if lst is None:
        return None
    order = []
    for sld in lst.findall(f"{{{_P}}}sldId"):
        rid = sld.get(f"{{{_R}}}id")
        order.append(rels.get(rid))
    if part_name in order:
        return order.index(part_name) + 1
    return None


# ── xlsx spreadsheet-drawing geometry ─────────────────────────────────────────────
# A spreadsheet chart/image is anchored to CELLS, not an EMU canvas: `<oneCellAnchor>` gives a from
# cell + an EMU extent, `<twoCellAnchor>` a from + to cell. To turn that into the page fractions the
# overlay needs, we reconstruct the pixel geometry the sheet renders at — column widths (Excel's
# character-width unit → px) and row heights (points → px at 96 dpi) — and normalize by the RENDERED
# extent. That extent is the union of the data range (`<dimension>`) AND every drawing, because a
# chart parked to the right of the data (as they usually are) widens what LibreOffice draws well
# past the last data column. Honesty (ADR 0016): derived only from the file's own declared widths —
# approximate to the pixel, but the box lands on the right region and never on the wrong shape.

def _col_to_idx(letters: str) -> int:
    idx = 0
    for ch in letters:
        idx = idx * 26 + (ord(ch) - 64)
    return idx - 1                                     # 0-based


def _worksheet_for_drawing(z, names, drawing_part):
    """The `xl/worksheets/sheetN.xml` whose rels reference this drawing part, or None."""
    dn = drawing_part.split("/")[-1]
    for n in names:
        if not _XLSX_SHEET_RELS.match(n):
            continue
        rroot = ET.fromstring(z.read(n))
        for rel in rroot.findall(f"{{{_RELS}}}Relationship"):
            if (rel.get("Target") or "").split("/")[-1] == dn:
                sheet = n.split("/")[-1][:-5]          # sheetN.xml.rels -> sheetN.xml
                return f"xl/worksheets/{sheet}"
    return None


def _sheet_metrics(z, sheet_part):
    """(col_left_px, row_top_px, (end_col, end_row)) for a worksheet — cumulative pixel offset
    functions built from its declared column widths / row heights, plus the data range's last cell."""
    root = ET.fromstring(z.read(sheet_part))
    fmt = root.find(f"{{{_SML}}}sheetFormatPr")
    base, defrow, defcolw = 8.0, 15.0, None
    if fmt is not None:
        base = float(fmt.get("baseColWidth") or 8)
        defrow = float(fmt.get("defaultRowHeight") or 15)
        if fmt.get("defaultColWidth"):
            defcolw = float(fmt.get("defaultColWidth"))
    w_px = lambda chars: round(chars * _MDW) + 5       # Excel width unit → pixels (approx)
    default_col_px = w_px(defcolw if defcolw is not None else base)
    custom = {}
    cols = root.find(f"{{{_SML}}}cols")
    if cols is not None:
        for c in cols.findall(f"{{{_SML}}}col"):
            try:
                lo, hi, wv = int(c.get("min")), int(c.get("max")), float(c.get("width"))
            except (TypeError, ValueError):
                continue
            for ci in range(lo - 1, hi):
                custom[ci] = w_px(wv)
    default_row_px = round(defrow * 4 / 3)             # points → px at 96 dpi
    rowh = {}
    data = root.find(f"{{{_SML}}}sheetData")
    if data is not None:
        for row in data.findall(f"{{{_SML}}}row"):
            if row.get("ht"):
                try:
                    rowh[int(row.get("r")) - 1] = round(float(row.get("ht")) * 4 / 3)
                except (TypeError, ValueError):
                    pass

    def col_left(col):                                 # px offset of the left edge of column `col`
        return sum(custom.get(ci, default_col_px) for ci in range(col))

    def row_top(row):
        return sum(rowh.get(ri, default_row_px) for ri in range(row))

    end_col, end_row = 1, 1
    dim = root.find(f"{{{_SML}}}dimension")
    if dim is not None and dim.get("ref"):
        m = re.match(r"([A-Z]+)(\d+)", dim.get("ref").split(":")[-1])
        if m:
            end_col, end_row = _col_to_idx(m.group(1)), int(m.group(2)) - 1
    return col_left, row_top, (end_col, end_row)


def _anchor_px_box(anchor, col_left, row_top):
    """(x, y, w, h) in px for one `<oneCellAnchor>`/`<twoCellAnchor>`, or None."""
    frm = anchor.find(f"{{{_SS}}}from")
    if frm is None:
        return None
    try:
        fc = int(frm.findtext(f"{{{_SS}}}col"))
        fco = int(frm.findtext(f"{{{_SS}}}colOff") or 0)
        fr = int(frm.findtext(f"{{{_SS}}}row"))
        fro = int(frm.findtext(f"{{{_SS}}}rowOff") or 0)
    except (TypeError, ValueError):
        return None
    x0 = col_left(fc) + fco / _EMU_PER_PX
    y0 = row_top(fr) + fro / _EMU_PER_PX
    ext = anchor.find(f"{{{_SS}}}ext")
    to = anchor.find(f"{{{_SS}}}to")
    if ext is not None:                                # oneCellAnchor: from + EMU extent
        try:
            w, h = int(ext.get("cx")) / _EMU_PER_PX, int(ext.get("cy")) / _EMU_PER_PX
        except (TypeError, ValueError):
            return None
    elif to is not None:                               # twoCellAnchor: from + to cell
        try:
            tc = int(to.findtext(f"{{{_SS}}}col")); tco = int(to.findtext(f"{{{_SS}}}colOff") or 0)
            tr = int(to.findtext(f"{{{_SS}}}row")); tro = int(to.findtext(f"{{{_SS}}}rowOff") or 0)
        except (TypeError, ValueError):
            return None
        w = (col_left(tc) + tco / _EMU_PER_PX) - x0
        h = (row_top(tr) + tro / _EMU_PER_PX) - y0
    else:
        return None
    if w <= 0 or h <= 0:
        return None
    return (x0, y0, w, h)


def _xlsx_shape_bbox(z, names, part_name, rid):
    sheet = _worksheet_for_drawing(z, names, part_name)
    if sheet is None or sheet not in names:
        return None
    col_left, row_top, (end_col, end_row) = _sheet_metrics(z, sheet)
    droot = ET.fromstring(z.read(part_name))
    boxes, target = [], None
    for anchor in list(droot):
        pic = anchor.find(f"{{{_SS}}}pic")
        if pic is None:                                # graphicFrame (native chart) etc. — skip
            continue
        blip = pic.find(f"{{{_SS}}}blipFill/{{{_A}}}blip")
        embed = blip.get(f"{{{_R}}}embed") if blip is not None else None
        cnv = pic.find(f"{{{_SS}}}nvPicPr/{{{_SS}}}cNvPr")
        name = (cnv.get("name") or "").strip() if cnv is not None else None
        box = _anchor_px_box(anchor, col_left, row_top)
        if box is None:
            continue
        boxes.append(box)
        if rid == embed or (name and rid == name):
            target = box
    if target is None or not boxes:
        return None
    # Rendered extent = union of the data range and every drawing (charts sit past the data cols).
    total_w = float(col_left(end_col + 1))
    total_h = float(row_top(end_row + 1))
    for (x0, y0, w, h) in boxes:
        total_w = max(total_w, x0 + w)
        total_h = max(total_h, y0 + h)
    if total_w <= 0 or total_h <= 0:
        return None
    x0, y0, w, h = target
    box = {"page": 1, "x": _clip(x0 / total_w), "y": _clip(y0 / total_h),
           "w": _clip(w / total_w), "h": _clip(h / total_h)}
    if box["w"] <= 0.0 or box["h"] <= 0.0:
        return None
    return box
