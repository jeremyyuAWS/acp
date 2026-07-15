"""Per-shape geometry for the bounding-box overlay (ADR 0018 Slice 2).

Hermetic: builds a minimal .pptx in memory (raw OPC zip, no python-pptx dependency) with pictures
placed at KNOWN EMU offsets, then asserts geometry.shape_bbox normalizes them to the expected
fractions and page — the ADR's "a box's centre lands in the expected quadrant" verification, made
exact. No corpus file, no external binary.
"""
import io
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import geometry  # noqa: E402

# A 12192000 × 6858000 EMU canvas (16:9), the pptx default.
_W, _H = 12192000, 6858000

_CT = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="xml" ContentType="application/xml"/>
<Default Extension="png" ContentType="image/png"/>
<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>
<Override PartName="/ppt/slides/slide1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>
<Override PartName="/ppt/slides/slide2.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>
</Types>"""

_PRES = f"""<?xml version="1.0"?>
<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<p:sldIdLst><p:sldId id="256" r:id="rIdA"/><p:sldId id="257" r:id="rIdB"/></p:sldIdLst>
<p:sldSz cx="{_W}" cy="{_H}"/></p:presentation>"""

# Note the deliberate mismatch: sldIdLst order is slide1 then slide2, but the render page for a
# slide is its POSITION in that list — which this fixture keeps aligned (slide1→1, slide2→2).
_PRES_RELS = """<?xml version="1.0"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rIdA" Type="x" Target="slides/slide1.xml"/>
<Relationship Id="rIdB" Type="x" Target="slides/slide2.xml"/></Relationships>"""


def _slide(pics):
    """pics: list of (rid, off_x, off_y, cx, cy) or (rid, None, ...) for an xfrm-less pic."""
    body = ""
    for rid, ox, oy, cx, cy in pics:
        xfrm = "" if ox is None else (
            f'<p:spPr><a:xfrm><a:off x="{ox}" y="{oy}"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm></p:spPr>')
        body += (f'<p:pic><p:blipFill><a:blip r:embed="{rid}"/></p:blipFill>{xfrm}</p:pic>')
    return (f'<?xml version="1.0"?>'
            f'<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
            f' xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
            f' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f'<p:cSld><p:spTree>{body}</p:spTree></p:cSld></p:sld>')


def _grouped_slide(rid, ox, oy, cx, cy):
    """A pic nested inside a group — its transform is group-relative, so geometry must refuse it."""
    return (f'<?xml version="1.0"?>'
            f'<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
            f' xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
            f' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f'<p:cSld><p:spTree><p:grpSp><p:pic><p:blipFill><a:blip r:embed="{rid}"/></p:blipFill>'
            f'<p:spPr><a:xfrm><a:off x="{ox}" y="{oy}"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm></p:spPr>'
            f'</p:pic></p:grpSp></p:spTree></p:cSld></p:sld>')


def _pptx(slide1_xml, slide2_xml):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", _CT)
        z.writestr("ppt/presentation.xml", _PRES)
        z.writestr("ppt/_rels/presentation.xml.rels", _PRES_RELS)
        z.writestr("ppt/slides/slide1.xml", slide1_xml)
        z.writestr("ppt/slides/slide2.xml", slide2_xml)
    return buf.getvalue()


def test_top_level_pic_normalizes_to_known_fractions():
    # A picture at (¼ W, ⅛ H) sized (½ W, ¼ H) → x=.25 y=.125 w=.5 h=.25.
    s1 = _slide([("rId2", _W // 4, _H // 8, _W // 2, _H // 4)])
    data = _pptx(s1, _slide([]))
    box = geometry.shape_bbox(data, ".pptx", "ppt/slides/slide1.xml#rId2")
    assert box is not None
    assert box["page"] == 1
    assert abs(box["x"] - 0.25) < 1e-4
    assert abs(box["y"] - 0.125) < 1e-4
    assert abs(box["w"] - 0.5) < 1e-4
    assert abs(box["h"] - 0.25) < 1e-4


def test_page_is_presentation_order_and_second_slide_resolves():
    s2 = _slide([("rId9", _W // 2, _H // 2, _W // 4, _H // 4)])
    data = _pptx(_slide([]), s2)
    box = geometry.shape_bbox(data, ".pptx", "ppt/slides/slide2.xml#rId9")
    assert box is not None and box["page"] == 2
    assert abs(box["x"] - 0.5) < 1e-4 and abs(box["y"] - 0.5) < 1e-4


def test_multiple_pics_match_the_right_embed():
    # Two side-by-side pics on one slide; the locator's rId must pick the correct rectangle.
    s1 = _slide([("rId2", 0, 0, _W // 2, _H),
                 ("rId3", _W // 2, 0, _W // 2, _H)])
    data = _pptx(s1, _slide([]))
    left = geometry.shape_bbox(data, ".pptx", "ppt/slides/slide1.xml#rId2")
    right = geometry.shape_bbox(data, ".pptx", "ppt/slides/slide1.xml#rId3")
    assert abs(left["x"] - 0.0) < 1e-4 and abs(right["x"] - 0.5) < 1e-4


def test_honest_absences_return_none():
    s1 = _slide([("rId2", _W // 4, _H // 8, _W // 2, _H // 4)])
    data = _pptx(s1, _slide([]))
    # Unknown rId, wrong part, non-pptx, garbage, empty, missing locator.
    assert geometry.shape_bbox(data, ".pptx", "ppt/slides/slide1.xml#rId999") is None
    assert geometry.shape_bbox(data, ".pptx", "ppt/slides/slide9.xml#rId2") is None
    assert geometry.shape_bbox(data, ".docx", "x#rId2") is None
    assert geometry.shape_bbox(b"not a zip", ".pptx", "a#rId2") is None
    assert geometry.shape_bbox(b"", ".pptx", "a#rId2") is None
    assert geometry.shape_bbox(data, ".pptx", None) is None
    assert geometry.shape_bbox(data, ".pptx", "no-hash") is None


def test_xfrm_less_and_grouped_pics_refuse_a_box():
    # A pic that inherits its placeholder geometry (no <a:xfrm>) → no box, not a guess.
    inherited = _slide([("rId2", None, None, None, None)])
    d1 = _pptx(inherited, _slide([]))
    assert geometry.shape_bbox(d1, ".pptx", "ppt/slides/slide1.xml#rId2") is None
    # A pic inside a group has a group-relative transform we won't compose → no box.
    d2 = _pptx(_grouped_slide("rId2", 0, 0, _W // 2, _H // 2), _slide([]))
    assert geometry.shape_bbox(d2, ".pptx", "ppt/slides/slide1.xml#rId2") is None


def _named_slide(name, rid, ox, oy, cx, cy):
    """A pic carrying a <p:cNvPr name> — the decorative / faithful-name proposal locator style."""
    return (f'<?xml version="1.0"?>'
            f'<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
            f' xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
            f' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f'<p:cSld><p:spTree>'
            f'<p:pic><p:nvPicPr><p:cNvPr id="4" name="{name}"/></p:nvPicPr>'
            f'<p:blipFill><a:blip r:embed="{rid}"/></p:blipFill>'
            f'<p:spPr><a:xfrm><a:off x="{ox}" y="{oy}"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm></p:spPr>'
            f'</p:pic></p:spTree></p:cSld></p:sld>')


def test_shape_name_fragment_resolves_like_an_rid():
    # remediate_office's decorative / faithful-name proposals locate by SHAPE NAME
    # ("slideN.xml#Picture 61"), not by rId. Both fragment styles must resolve — matching only
    # the rId left every name-style card with no box and no page (found live on a real deck).
    data = _pptx(_named_slide("Picture 61", "rId9", _W // 4, _H // 4, _W // 2, _H // 2),
                 _slide([]))
    by_name = geometry.shape_bbox(data, ".pptx", "ppt/slides/slide1.xml#Picture 61")
    by_rid = geometry.shape_bbox(data, ".pptx", "ppt/slides/slide1.xml#rId9")
    assert by_name == by_rid
    assert by_name and by_name["page"] == 1
    assert abs(by_name["x"] - 0.25) < 0.01 and abs(by_name["w"] - 0.5) < 0.01
    # An unknown name is still an honest None, never a guessed box.
    assert geometry.shape_bbox(data, ".pptx", "ppt/slides/slide1.xml#No Such Shape") is None


# ── ADR 0024 Tier B: text-shape (<p:sp>) geometry for the 1.4.3-hybrid run ─────────
def _text_slide(sp_id, name, ox, oy, cx, cy, grouped=False, xfrm=True):
    """A slide with a top-level text box (<p:sp> + txBody) — the shape a 1.4.3-hybrid finding
    names. `grouped` nests it in a <p:grpSp>; `xfrm=False` drops its own transform."""
    x = (f'<a:xfrm><a:off x="{ox}" y="{oy}"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>' if xfrm else "")
    sp = (f'<p:sp><p:nvSpPr><p:cNvPr id="{sp_id}" name="{name}"/></p:nvSpPr>'
          f'<p:spPr>{x}<a:blipFill/></p:spPr>'
          f'<p:txBody><a:p><a:r><a:t>Over the image</a:t></a:r></a:p></p:txBody></p:sp>')
    inner = f'<p:grpSp>{sp}</p:grpSp>' if grouped else sp
    return (f'<?xml version="1.0"?>'
            f'<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
            f' xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
            f' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f'<p:cSld><p:spTree>{inner}</p:spTree></p:cSld></p:sld>')


def test_text_shape_resolves_by_name_and_id():
    # The hybrid locator names a TEXT box by cNvPr name ("#Title 1") or id ("#7"); both resolve.
    data = _pptx(_text_slide(7, "Title 1", _W // 4, _H // 8, _W // 2, _H // 4), _slide([]))
    by_name = geometry.shape_bbox(data, ".pptx", "ppt/slides/slide1.xml#Title 1")
    by_id = geometry.shape_bbox(data, ".pptx", "ppt/slides/slide1.xml#7")
    assert by_name == by_id
    assert by_name and by_name["page"] == 1
    assert abs(by_name["x"] - 0.25) < 1e-4 and abs(by_name["y"] - 0.125) < 1e-4
    assert abs(by_name["w"] - 0.5) < 1e-4 and abs(by_name["h"] - 0.25) < 1e-4


def test_text_shape_grouped_or_xfrm_less_refuses_a_box():
    # Same honesty rule as pictures: a grouped or transform-inheriting text box gets no box.
    grouped = _pptx(_text_slide(7, "Title 1", 0, 0, _W // 2, _H // 2, grouped=True), _slide([]))
    assert geometry.shape_bbox(grouped, ".pptx", "ppt/slides/slide1.xml#Title 1") is None
    inherited = _pptx(_text_slide(7, "Title 1", 0, 0, 0, 0, xfrm=False), _slide([]))
    assert geometry.shape_bbox(inherited, ".pptx", "ppt/slides/slide1.xml#Title 1") is None
