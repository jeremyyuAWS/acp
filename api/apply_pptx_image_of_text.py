"""PARTLY RETIRED: the RESOLVER below is live, the WRITER is not.

#1715 gave the pptx 1.4.5 lane a writer that clears the criterion: apply_pptx_image_replacement
swaps the picture for a real text box and DELETES the image. Setting descr, which is what
`apply_pptx_image_of_text` below does, leaves the raster in ppt/media where ocr._ooxml_images
reads it straight out of the zip — so the finding re-fires and the verify gate refuses the
credit, which is why #1665 had already downgraded that lane to HUMAN. That function is correct
at what it does; what it does is not a 1.4.5 fix, and nothing calls it. See
tests/test_apply_pptx_image_of_text_retired.py, which holds it that way.

WHAT IS LIVE: `resolve_media_locators`. ADR 0055 (describe-instead-of-replace) routes a
reviewer's description of an image they chose to KEEP through the proven 1.1.1 alt lane, and the
only thing standing between the two is a locator shape — the 1.4.5 proposer mints 'image N', a
media index, and apply_alt cannot read it at all. This module already had the resolution that
translation needs (_media_index + _slide_rels: media index -> canonical media path -> the rId a
slide references it by), which is the whole reason #1724 kept the file rather than deleting it.

So the revival is deliberately PARTIAL. `_patch_pics` — the half that sets descr — stays dead,
because apply_alt_text already writes alt text, resolves both locator shapes, and has a
round-trip fixture behind it. Two writers for one job is how they drift.

Write reviewer-approved alt text into pptx images-of-text (WCAG 1.4.5 / 1.4.9).

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


def is_media_index_locator(locator) -> bool:
    """True for the 'image N' shape this module's enumeration mints.

    LIVE. Exported so a caller can ask "does anything here need translating" without recompiling
    the pattern — handlers uses it to decide whether the alt lane runs the expansion at all, and
    a second copy of this regex somewhere else is how the recogniser and the translator start
    disagreeing about which locators are media indices.
    """
    return bool(_IMAGE_LOC.match(str(locator or "").strip()))


def resolve_media_locators(data: bytes, locators) -> dict[str, list[str]]:
    """{'image N': ['ppt/slides/slideK.xml#rIdM', …]} — the ADR 0055 locator translation.

    LIVE (unlike the writer below). It turns a locator only this module can read into ones the
    proven 1.1.1 alt lane can: apply_alt.resolve_target matches an `r:embed` fragment to the
    alt-bearing element of the picture that embeds it, exactly as it matches a shape name.

    The chain is the one _media_index and _slide_rels already implemented for the writer:

        'image N'  ->  the Nth ppt/media raster in zip-namelist order   (mirrors ocr._ooxml_images)
                   ->  EVERY (slide, rId) pair that references that media part

    ONE LOCATOR, MANY PLACEMENTS — which is why this returns a list and not a string, and the
    reason was measured rather than reasoned about. 'image N' names the MEDIA PART, not a
    picture: a logo or a diagram dropped on three slides is one entry in ocr._ooxml_images and
    one review card. Describing only the first placement leaves the other two carrying whatever
    descr they had (typically the source filename, which the detector reads as junk), so 1.1.1
    would still fail on re-scan, the verify gate would withhold the credit, and the reviewer's
    approved description would never be marked applied. A first draft of this function returned
    one target and had exactly that hole.

    This mirrors the 1.4.5 replacement lane, which replaces every placement or none because the
    media part is deleted once. Same fact about the locator scheme, same all-or-nothing shape.

    A locator is OMITTED rather than mapped to anything when it cannot be resolved — malformed,
    an index past the end of the media list, or a media part no slide references (a layout's or
    master's image, which apply_alt would not reach either). Silence is the honest answer: the
    caller keeps the original, apply_alt reports it unresolved, and _apply_one_value_kind
    withholds the credit. Guessing a different image would write a reviewer's description onto a
    picture they never saw.

    Slides are visited in zip-namelist order, and each slide's own rels in file order, so the
    list is stable across runs for the same package.
    """
    wanted = [str(l).strip() for l in (locators or ()) if str(l or "").strip()]
    if not wanted:
        return {}

    out: dict[str, list[str]] = {}
    with zipfile.ZipFile(io.BytesIO(data)) as zin:
        media_idx = _media_index(zin)
        # canonical media path -> every 'slidepart#rId' that references it, in zip order.
        refs: dict[str, list[str]] = {}
        for name in zin.namelist():
            if not re.fullmatch(r"ppt/slides/slide\d+\.xml", name):
                continue
            for rid, canonical in _slide_rels(zin, name).items():
                refs.setdefault(canonical, []).append(f"{name}#{rid}")

    for locator in wanted:
        m = _IMAGE_LOC.match(locator)
        if not m:
            continue
        n = int(m.group(1)) - 1
        if n < 0 or n >= len(media_idx):
            continue
        placements = refs.get(media_idx[n])
        if placements:
            out[locator] = list(placements)
    return out


def expand_media_locator_values(data: bytes, values: dict[str, str]) -> dict[str, str]:
    """`values` with every resolvable 'image N' key replaced by its placements' locators.

    The form the alt lane actually wants: one flat {locator: text} map it can hand straight to
    apply_alt_text. Each placement of a media part gets the SAME text, because the reviewer
    described the image and every placement IS that image.

    Keys that are not media-index locators pass through untouched — an ordinary 1.1.1 row's
    'part#name' must not be disturbed — and so does a media-index locator that did not resolve,
    so it reaches apply_alt, is reported unresolved, and shows up in the apply.unresolved log
    under the name the reviewer's card used.
    """
    if not values:
        return {}
    media_keys = [k for k in values if _IMAGE_LOC.match(str(k).strip())]
    if not media_keys:
        return dict(values)
    resolved = resolve_media_locators(data, media_keys)
    out: dict[str, str] = {}
    for locator, text in values.items():
        for target in resolved.get(str(locator).strip(), [locator]):
            out[target] = text
    return out


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
