"""Write reviewer-approved alt text into pptx images-of-text (WCAG 1.4.5 / 1.4.9).

api/proposals.propose_images_of_text drafts OCR'd text for embedded raster images that
contain readable prose, keyed by locator:

    locator = 'image N'    e.g. 'image 1'   (1-based, zip namelist order)

This is the write-back: approved text is set as the picture's descriptive alt text on
the <p:cNvPr descr="..."> attribute of the matching <p:pic> element in each slide.

The enumeration order mirrors ocr._ooxml_images exactly: walk z.namelist(), keep entries
under ppt/media/ whose extension is a raster format. The Nth such entry (1-based) is the
image whose locator is 'image N'. Within a slide, pictures are matched by resolving the
r:embed rId through the slide's .rels file to that same media path.
"""
from __future__ import annotations

import io
import posixpath
import re
import zipfile

# Mirror the filter in ocr._ooxml_images so locator indices stay in sync.
_MEDIA_RE = re.compile(r"^ppt/media/", re.I)
_RASTER = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp")

_IMAGE_LOC = re.compile(r"^image\s+(\d+)$", re.IGNORECASE)

# A <p:pic> block in slide XML (greedy across the full element).
_PIC_RE = re.compile(r"<p:pic\b[^>]*>.*?</p:pic>", re.DOTALL)

# The blip's r:embed attribute, identifying which media file this picture references.
_EMBED_RE = re.compile(r"<a:blip\b[^>]*\br:embed=\"([^\"]+)\"")

# The non-visual properties element that carries the alt-text descr attribute.
_CNVPR_RE = re.compile(r"(<p:cNvPr\b(?:[^>]*?))(\s*/?>)")

# One Relationship entry in a .rels file.
_REL_RE = re.compile(
    r'<Relationship\b[^>]*\bId="([^"]+)"[^>]*\bTarget="([^"]+)"',
    re.IGNORECASE,
)


def _xesc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;")
             .replace(">", "&gt;").replace('"', "&quot;"))


def _media_index(zin: zipfile.ZipFile) -> list[str]:
    """Ordered list of ppt/media raster paths — same traversal order as ocr._ooxml_images."""
    return [
        n for n in zin.namelist()
        if _MEDIA_RE.match(n) and n.lower().endswith(_RASTER)
    ]


def _slide_rels(zin: zipfile.ZipFile, slide_path: str) -> dict[str, str]:
    """rId -> canonical zip path (e.g. 'ppt/media/image1.png') for this slide."""
    dir_, name = slide_path.rsplit("/", 1)
    rels_path = f"{dir_}/_rels/{name}.rels"
    try:
        xml = zin.read(rels_path).decode("utf-8", "replace")
    except KeyError:
        return {}
    out: dict[str, str] = {}
    for m in _REL_RE.finditer(xml):
        rid, target = m.group(1), m.group(2)
        # Target is relative to the slide directory; resolve to a canonical zip path.
        canonical = posixpath.normpath(posixpath.join(dir_, target))
        out[rid] = canonical
    return out


def _patch_pics(
    xml: str,
    rid_map: dict[str, str],
    canonical_to_info: dict[str, tuple[str, str]],
) -> tuple[str, list[dict]]:
    """Set descr on every <p:pic> whose media resolves to a key in canonical_to_info."""
    applied: list[dict] = []

    def _replace_pic(pm: re.Match) -> str:
        pic = pm.group(0)
        em = _EMBED_RE.search(pic)
        if not em:
            return pic
        canonical = rid_map.get(em.group(1))
        if canonical not in canonical_to_info:
            return pic
        locator, text = canonical_to_info[canonical]

        old_m = re.search(r'<p:cNvPr\b[^>]*\bdescr="([^"]*)"', pic)
        old_val = old_m.group(1) if old_m else "(none)"

        def _patch_cnvpr(cm: re.Match) -> str:
            attrs = re.sub(r'\s+descr="[^"]*"', "", cm.group(1))
            return f'{attrs} descr="{_xesc(text)}"{cm.group(2)}'

        new_pic = _CNVPR_RE.sub(_patch_cnvpr, pic, count=1)
        if new_pic != pic:
            applied.append({
                "locator": locator,
                "before": old_val,
                "after": text,
                "_canonical": canonical,
            })
        return new_pic

    return _PIC_RE.sub(_replace_pic, xml), applied


def apply_pptx_image_of_text(
    data: bytes, values: dict[str, str]
) -> tuple[bytes, list[dict], list[str]]:
    """Set alt text (descr) on image-of-text pictures in a pptx file.

    `values` maps 'image N' locators to approved OCR text strings.
    Returns (fixed_bytes, applied, unresolved).
    applied entries: {locator, before, after}.
    unresolved: locators not matched to any <p:pic> in the document.
    """
    if not values:
        return data, [], []

    with zipfile.ZipFile(io.BytesIO(data)) as zin:
        media_idx = _media_index(zin)

    canonical_to_info: dict[str, tuple[str, str]] = {}
    unresolved: list[str] = []
    for locator, text in values.items():
        m = _IMAGE_LOC.match(locator.strip())
        if not m:
            unresolved.append(locator)
            continue
        n = int(m.group(1)) - 1
        if n < 0 or n >= len(media_idx):
            unresolved.append(locator)
            continue
        canonical_to_info[media_idx[n]] = (locator, text)

    if not canonical_to_info:
        return data, [], unresolved

    applied: list[dict] = []
    out_buf = io.BytesIO()
    written_canonicals: set[str] = set()

    with zipfile.ZipFile(io.BytesIO(data), "r") as zin, \
         zipfile.ZipFile(out_buf, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            content = zin.read(info.filename)
            if re.fullmatch(r"ppt/slides/slide\d+\.xml", info.filename):
                rid_map = _slide_rels(zin, info.filename)
                xml = content.decode("utf-8", "replace")
                new_xml, slide_applied = _patch_pics(xml, rid_map, canonical_to_info)
                if slide_applied:
                    content = new_xml.encode("utf-8")
                    for a in slide_applied:
                        written_canonicals.add(a.pop("_canonical"))
                    applied.extend(slide_applied)
            zout.writestr(info, content)

    for canonical, (locator, _) in canonical_to_info.items():
        if canonical not in written_canonicals:
            unresolved.append(locator)

    return out_buf.getvalue(), applied, unresolved
