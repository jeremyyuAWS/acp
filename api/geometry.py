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


def shape_bbox(data: bytes, ext: str, locator: str | None) -> dict | None:
    """Normalized `{page, x, y, w, h}` for the shape a `part_name#rId` locator names, or None.

    Never raises: any parse/lookup failure — bad locator, missing shape, grouped/inherited
    transform, unsupported format — degrades to None (no box), per ADR 0016/0018."""
    try:
        e = (ext or "").lower()
        if e != ".pptx" or not data or not locator or "#" not in locator:
            return None
        part_name, rid = locator.rsplit("#", 1)
        if not _PPTX_SLIDE.match(part_name):
            return None
        with zipfile.ZipFile(_io(data)) as z:
            names = set(z.namelist())
            if part_name not in names:
                return None
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
            box = {
                "page": page,
                "x": _clip(off_x / sw),
                "y": _clip(off_y / sh),
                "w": _clip(cx / sw),
                "h": _clip(cy / sh),
            }
            # A degenerate rectangle (zero area, or normalized to nothing) is not a usable box.
            if box["w"] <= 0.0 or box["h"] <= 0.0:
                return None
            return box
    except Exception:
        return None


def _io(data: bytes):
    import io
    return io.BytesIO(data)


def _clip(v: float) -> float:
    return 0.0 if v < 0 else (1.0 if v > 1 else round(v, 5))


def _pic_rect_by_embed(slide_xml: bytes, rid: str) -> tuple[int, int, int, int] | None:
    """(off.x, off.y, ext.cx, ext.cy) in EMU for the TOP-LEVEL `<p:pic>` whose blip embeds `rid`.

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
        if blip is None:
            continue
        embed = blip.get(f"{{{_R}}}embed")
        if embed != rid:
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
