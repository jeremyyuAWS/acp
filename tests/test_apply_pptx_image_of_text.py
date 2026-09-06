"""Tests for apply_pptx_image_of_text — the write-back for pptx 1.4.5 / 1.4.9."""
from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import apply_pptx_image_of_text as _mod  # noqa: E402

# Minimal 8-byte "PNG" content — the applier never decodes image data.
_FAKE_PNG = b"\x89PNG\r\n\x1a\n"

_RELS_HEADER = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
)
_RELS_FOOTER = "</Relationships>"


def _rel(rid: str, target: str) -> str:
    return (
        f'<Relationship Id="{rid}"'
        ' Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"'
        f' Target="{target}"/>'
    )


def _slide_rels_xml(*rels: tuple[str, str]) -> str:
    """Build a slide .rels document from (rId, target) pairs."""
    return _RELS_HEADER + "".join(_rel(r, t) for r, t in rels) + _RELS_FOOTER


def _pic_xml(rid: str, descr: str = "") -> str:
    descr_attr = f' descr="{descr}"' if descr else ""
    return (
        '<p:pic'
        ' xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
        ' xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
        ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<p:nvPicPr>'
        f'<p:cNvPr id="4" name="Picture 3"{descr_attr}/>'
        "<p:cNvPicPr/><p:nvPr/>"
        "</p:nvPicPr>"
        f'<p:blipFill><a:blip r:embed="{rid}"/>'
        "<a:stretch><a:fillRect/></a:stretch></p:blipFill>"
        "<p:spPr/>"
        "</p:pic>"
    )


def _slide_xml(*pics: str) -> str:
    body = "".join(pics)
    return (
        '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
        ' xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
        ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<p:cSld><p:spTree><p:grpSpPr/>{body}</p:spTree></p:cSld>"
        "</p:sld>"
    )


def _pptx(
    slides: dict[int, str],
    rels: dict[int, str] | None = None,
    media: dict[str, bytes] | None = None,
) -> bytes:
    """Build a minimal pptx zip."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for num, xml in slides.items():
            z.writestr(f"ppt/slides/slide{num}.xml", xml)
        for num, rxml in (rels or {}).items():
            z.writestr(f"ppt/slides/_rels/slide{num}.xml.rels", rxml)
        for name, data in (media or {}).items():
            z.writestr(name, data)
    return buf.getvalue()


def _descr(data: bytes, slide: int) -> str | None:
    """Extract the first p:cNvPr descr= value from the given slide."""
    import re
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        xml = z.read(f"ppt/slides/slide{slide}.xml").decode()
    m = re.search(r'<p:cNvPr\b[^>]*\bdescr="([^"]*)"', xml)
    return m.group(1) if m else None


# ── basic write-back ───────────────────────────────────────────────────────────

def test_writes_descr_on_matching_picture():
    data = _pptx(
        slides={1: _slide_xml(_pic_xml("rId1"))},
        rels={1: _slide_rels_xml(("rId1", "../media/image1.png"))},
        media={"ppt/media/image1.png": _FAKE_PNG},
    )
    fixed, applied, unresolved = _mod.apply_pptx_image_of_text(data, {"image 1": "Quarterly chart"})
    assert _descr(fixed, 1) == "Quarterly chart"
    assert len(applied) == 1
    assert applied[0]["locator"] == "image 1"
    assert applied[0]["after"] == "Quarterly chart"
    assert unresolved == []


def test_overwrites_existing_descr():
    data = _pptx(
        slides={1: _slide_xml(_pic_xml("rId1", descr="old text"))},
        rels={1: _slide_rels_xml(("rId1", "../media/image1.png"))},
        media={"ppt/media/image1.png": _FAKE_PNG},
    )
    fixed, applied, unresolved = _mod.apply_pptx_image_of_text(data, {"image 1": "new text"})
    assert _descr(fixed, 1) == "new text"
    assert applied[0]["before"] == "old text"
    assert applied[0]["after"] == "new text"
    assert unresolved == []


def test_escapes_xml_special_chars():
    data = _pptx(
        slides={1: _slide_xml(_pic_xml("rId1"))},
        rels={1: _slide_rels_xml(("rId1", "../media/image1.png"))},
        media={"ppt/media/image1.png": _FAKE_PNG},
    )
    text = 'a < b & "c"'
    fixed, applied, unresolved = _mod.apply_pptx_image_of_text(data, {"image 1": text})
    assert applied[0]["after"] == text
    # The raw XML must contain the escaped form
    with zipfile.ZipFile(io.BytesIO(fixed)) as z:
        xml = z.read("ppt/slides/slide1.xml").decode()
    assert 'a &lt; b &amp; &quot;c&quot;' in xml


def test_second_image_in_zip_order():
    # Two media files; "image 2" addresses the second one in namelist order.
    data = _pptx(
        slides={1: _slide_xml(_pic_xml("rId1"), _pic_xml("rId2"))},
        rels={1: _slide_rels_xml(
            ("rId1", "../media/image1.png"),
            ("rId2", "../media/image2.png"),
        )},
        media={
            "ppt/media/image1.png": _FAKE_PNG,
            "ppt/media/image2.png": _FAKE_PNG,
        },
    )
    fixed, applied, unresolved = _mod.apply_pptx_image_of_text(data, {"image 2": "second caption"})
    # Only the second picture gets a descr written; verify slide XML has it
    with zipfile.ZipFile(io.BytesIO(fixed)) as z:
        xml = z.read("ppt/slides/slide1.xml").decode()
    import re
    descrs = re.findall(r'<p:cNvPr\b[^>]*\bdescr="([^"]*)"', xml)
    # second p:cNvPr in slide order should carry the new text
    assert "second caption" in descrs
    assert unresolved == []


# ── unresolved paths ───────────────────────────────────────────────────────────

def test_empty_values_is_noop():
    data = _pptx(
        slides={1: _slide_xml(_pic_xml("rId1"))},
        media={"ppt/media/image1.png": _FAKE_PNG},
    )
    fixed, applied, unresolved = _mod.apply_pptx_image_of_text(data, {})
    assert fixed == data
    assert applied == []
    assert unresolved == []


def test_out_of_range_locator_is_unresolved():
    data = _pptx(
        slides={1: _slide_xml(_pic_xml("rId1"))},
        media={"ppt/media/image1.png": _FAKE_PNG},
    )
    fixed, applied, unresolved = _mod.apply_pptx_image_of_text(data, {"image 99": "text"})
    assert applied == []
    assert "image 99" in unresolved


def test_bad_locator_format_is_unresolved():
    data = _pptx(slides={1: _slide_xml()})
    fixed, applied, unresolved = _mod.apply_pptx_image_of_text(data, {"slide 1": "text"})
    assert applied == []
    assert "slide 1" in unresolved


def test_pic_with_no_rels_entry_is_unresolved():
    # The slide has a pic with rId1 but the .rels file has no entry for it.
    data = _pptx(
        slides={1: _slide_xml(_pic_xml("rId1"))},
        rels={1: _slide_rels_xml()},
        media={"ppt/media/image1.png": _FAKE_PNG},
    )
    fixed, applied, unresolved = _mod.apply_pptx_image_of_text(data, {"image 1": "text"})
    assert applied == []
    assert "image 1" in unresolved


# ── media_index mirrors ocr._ooxml_images ─────────────────────────────────────

def test_non_raster_media_skipped_in_index():
    # A .wmv file in ppt/media should not count in the index.
    data = _pptx(
        slides={1: _slide_xml(_pic_xml("rId1"))},
        rels={1: _slide_rels_xml(("rId1", "../media/image1.png"))},
        media={
            "ppt/media/video1.wmv": b"fakevideo",
            "ppt/media/image1.png": _FAKE_PNG,
        },
    )
    # image1.png is the first raster entry — locator "image 1" should hit it
    fixed, applied, unresolved = _mod.apply_pptx_image_of_text(data, {"image 1": "real image"})
    assert _descr(fixed, 1) == "real image"
    assert unresolved == []
