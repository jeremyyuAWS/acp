"""Replace a pptx image-of-text with a real text box (WCAG 1.4.5 Images of Text).

Named `api/apply_` by convention, not by accident: gen_progress_log.RULE_PATHS treats that
prefix as "this is an applier", so a write-back module named anything else escapes the
Matrix-Note guard entirely — the under-match its own comment warns is unrecoverable, since the
trailer is a per-commit fact no later commit can supply.

This is the GENUINE 1.4.5 remediation, as opposed to `apply_pptx_image_of_text`, which writes
the OCR transcript into the picture's `descr`. That is a 1.1.1 improvement and was never a
1.4.5 fix: 1.4.5 asks for real text INSTEAD of a picture of text, so while the raster is still
in the package the criterion still fails. #1665 downgraded the descr lane to HUMAN for exactly
that reason.

WHAT CLEARING 1.4.5 ACTUALLY REQUIRES, measured rather than assumed. `ocr._ooxml_images` walks
the ZIP NAMELIST for `ppt/media/*` raster entries — it never opens a slide, a relationship or a
shape tree. So deleting the `<p:pic>` element does NOT clear the finding: the media part is
still in the package, tesseract still reads it, and the re-scan re-fires. Removing the `<p:pic>`
AND the media part clears it. Both were measured on a real deck before this module was written;
`tests/test_remediation_verified_pptx_image_of_text.py::test_removing_only_the_picture_does_not_clear_it`
pins the trap so a future refactor cannot quietly reintroduce it.

So one approved locator means all of:
  1. every `<p:pic>` that shows that image becomes a `<p:sp>` text box at the same position and
     size, carrying the approved text;
  2. the image `<Relationship>` is dropped from each of those slides' .rels;
  3. the media part itself is dropped from the zip.

WHEN THIS REFUSES, and refusing is the point — an approved value that cannot be written honestly
must come back as `unresolved` so `_apply_one_value_kind` withholds credit rather than
publishing a half-change:

  * the image is referenced by anything that is not a slide (a layout, a master, notes). Deleting
    it would strike it from every slide built on that layout, which is not the reviewer's call
    and is not what they approved.
  * a `<p:pic>` showing it sits inside a `<p:grpSp>`. Its position is relative to the group's
    own transform, so a text box placed at those coordinates lands somewhere else.
  * a `<p:pic>` showing it carries no `<a:xfrm>` of its own (inherited geometry). There is no
    honest box to draw — `geometry.py` returns None in the same situation rather than guessing.

WHAT THIS CLAIMS: the words are now real text a screen reader announces, selectable and
resizable, and the raster is gone. NOT that the slide looks the same. Replacing a picture with
its transcript is a visual change, which is exactly why the lane is ASSISTED and a human
approves each one.
"""
from __future__ import annotations

import io
import posixpath
import re
import zipfile

# Mirror the filter in ocr._ooxml_images so locator indices stay in sync. If these ever diverge,
# "image 3" means a different picture to the detector and to this writer.
_MEDIA_RE = re.compile(r"^ppt/media/", re.I)
_RASTER = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp")

_IMAGE_LOC = re.compile(r"^image\s+(\d+)$", re.IGNORECASE)
_SLIDE_RE = re.compile(r"^ppt/slides/slide\d+\.xml$", re.I)

_PIC_RE = re.compile(r"<p:pic\b[^>]*>.*?</p:pic>", re.DOTALL)
_GRPSP_RE = re.compile(r"<p:grpSp\b[^>]*>.*?</p:grpSp>", re.DOTALL)
_EMBED_RE = re.compile(r'<a:blip\b[^>]*\br:embed="([^"]+)"')
_OFF_RE = re.compile(r'<a:off\b[^>]*\bx="(-?\d+)"[^>]*\by="(-?\d+)"')
_EXT_RE = re.compile(r'<a:ext\b[^>]*\bcx="(\d+)"[^>]*\bcy="(\d+)"')
_CNVPR_ID_RE = re.compile(r'<p:cNvPr\b[^>]*\bid="(\d+)"')

_REL_RE = re.compile(r'<Relationship\b[^>]*\bId="([^"]+)"[^>]*\bTarget="([^"]+)"', re.I)
# One whole Relationship element, matched by its Id so only the image's own entry is removed.
_REL_ELEM = r'<Relationship\b[^>]*\bId="{rid}"[^>]*?/>'


def _xesc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;"))


def _media_index(zin: zipfile.ZipFile) -> list[str]:
    """Ordered ppt/media raster paths — the same traversal order as ocr._ooxml_images, so the
    Nth entry (1-based) is the image whose locator is 'image N'."""
    return [n for n in zin.namelist()
            if _MEDIA_RE.match(n) and n.lower().endswith(_RASTER)]


def _rels_path(part: str) -> str:
    dir_, name = part.rsplit("/", 1)
    return f"{dir_}/_rels/{name}.rels"


def _rels(zin: zipfile.ZipFile, part: str) -> dict[str, str]:
    """rId -> canonical zip path for `part`'s relationships."""
    try:
        xml = zin.read(_rels_path(part)).decode("utf-8", "replace")
    except KeyError:
        return {}
    dir_ = part.rsplit("/", 1)[0]
    return {m.group(1): posixpath.normpath(posixpath.join(dir_, m.group(2)))
            for m in _REL_RE.finditer(xml)}


def _referencing_parts(zin: zipfile.ZipFile, media: str) -> dict[str, list[str]]:
    """{part -> [rId, ...]} for every part in the package whose .rels points at `media`.

    Every part, not just slides: a layout or master reference is the reason to refuse, so it has
    to be seen. Missing it would delete an image out from under every slide on that layout.
    """
    out: dict[str, list[str]] = {}
    for name in zin.namelist():
        if not name.endswith(".rels"):
            continue
        # 'ppt/slides/_rels/slide1.xml.rels' -> 'ppt/slides/slide1.xml'
        dir_, base = name.rsplit("/_rels/", 1) if "/_rels/" in name else ("", "")
        if not base.endswith(".rels"):
            continue
        owner = f"{dir_}/{base[:-len('.rels')]}"
        rids = [rid for rid, target in _rels(zin, owner).items() if target == media]
        if rids:
            out[owner] = rids
    return out


def _text_box(pic_xml: str, text: str, shape_id: int) -> str | None:
    """A <p:sp> text box occupying the picture's own rectangle, or None if it has none.

    `normAutofit` rather than a chosen font size: the transcript is as long as it is, and a
    renderer shrinking it to fit is honest where a guessed size would silently clip words.
    """
    off, ext = _OFF_RE.search(pic_xml), _EXT_RE.search(pic_xml)
    if not off or not ext:
        return None
    x, y = off.group(1), off.group(2)
    cx, cy = ext.group(1), ext.group(2)
    runs = "".join(
        f'<a:p><a:r><a:rPr lang="en-US" dirty="0"/><a:t>{_xesc(line)}</a:t></a:r></a:p>'
        for line in (text.splitlines() or [text]) if line.strip()
    ) or '<a:p><a:endParaRPr lang="en-US"/></a:p>'
    return (
        f'<p:sp><p:nvSpPr>'
        f'<p:cNvPr id="{shape_id}" name="Text {shape_id}"/>'
        f'<p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>'
        f'<p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
        f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/></p:spPr>'
        f'<p:txBody><a:bodyPr wrap="square" rtlCol="0"><a:normAutofit/></a:bodyPr>'
        f'<a:lstStyle/>{runs}</p:txBody></p:sp>'
    )


def _next_shape_id(xml: str) -> int:
    ids = [int(m) for m in _CNVPR_ID_RE.findall(xml)]
    return (max(ids) + 1) if ids else 2


def _survey_slide(xml: str, rid_map: dict[str, str],
                  wanted: set[str]) -> dict[str, list[bool]]:
    """{media path: [replaceable?, ...]} — one flag per <p:pic> on this slide showing a wanted
    image. An image is only written when EVERY picture of it, on every slide, can be replaced:
    the media part is deleted once, so one picture left behind is a deck referencing a part that
    is no longer there."""
    group_spans = [m.span() for m in _GRPSP_RE.finditer(xml)]
    out: dict[str, list[bool]] = {}
    for m in _PIC_RE.finditer(xml):
        embed = _EMBED_RE.search(m.group(0))
        media = rid_map.get(embed.group(1)) if embed else None
        if not media or media not in wanted:
            continue
        grouped = any(s <= m.start() < e for s, e in group_spans)
        has_box = _text_box(m.group(0), "x", 2) is not None
        out.setdefault(media, []).append(not grouped and has_box)
    return out


def _rewrite_slide(xml: str, rid_map: dict[str, str],
                   text_by_media: dict[str, str]) -> tuple[str, list[str]]:
    """Replace every <p:pic> showing one of `text_by_media` with a text box. Only called for
    images the survey already proved fully replaceable, so nothing is skipped here."""
    replaced: list[str] = []
    next_id = _next_shape_id(xml)
    out, cursor = [], 0
    for m in _PIC_RE.finditer(xml):
        embed = _EMBED_RE.search(m.group(0))
        media = rid_map.get(embed.group(1)) if embed else None
        if not media or media not in text_by_media:
            continue
        sp = _text_box(m.group(0), text_by_media[media], next_id)
        if sp is None:                          # unreachable via the survey; never guess a box
            continue
        next_id += 1
        out.append(xml[cursor:m.start()]); out.append(sp)
        cursor = m.end()
        replaced.append(media)
    out.append(xml[cursor:])
    return "".join(out), replaced


def _strip_rel(xml: str, rid: str) -> str:
    return re.sub(_REL_ELEM.format(rid=re.escape(rid)), "", xml, count=1)


def apply_pptx_image_replacement(
    data: bytes, values: dict[str, str]
) -> tuple[bytes, list[dict], list[str]]:
    """Replace approved images-of-text with text boxes, and delete the images.

    `values` maps 'image N' locators to the approved transcript.
    Returns (fixed_bytes, applied, unresolved) — the write_fn contract _apply_one_value_kind
    expects. applied entries: {locator, before, after}.
    """
    if not values:
        return data, [], []

    unresolved: list[str] = []
    wanted: dict[str, tuple[str, str]] = {}       # media path -> (locator, text)

    with zipfile.ZipFile(io.BytesIO(data)) as zin:
        media = _media_index(zin)
        for locator, text in values.items():
            m = _IMAGE_LOC.match(locator.strip())
            if not m:
                unresolved.append(locator)
                continue
            n = int(m.group(1)) - 1
            if n < 0 or n >= len(media):
                unresolved.append(locator)
                continue
            path = media[n]
            refs = _referencing_parts(zin, path)
            if not refs or any(not _SLIDE_RE.match(p) for p in refs):
                # Unreferenced (nothing to replace) or referenced by a layout/master/notes part,
                # where deleting it would change slides nobody reviewed.
                unresolved.append(locator)
                continue
            wanted[path] = (locator, text)

        if not wanted:
            return data, [], unresolved

        # SURVEY, then rewrite. A locator is written only when every picture of it, on every
        # slide, can be replaced honestly — the media part is deleted once, so one picture left
        # behind would point at a part that is no longer in the package.
        slides = [n for n in zin.namelist() if _SLIDE_RE.match(n)]
        rid_maps = {n: _rels(zin, n) for n in slides}
        seen: dict[str, list[bool]] = {}
        for name in slides:
            xml = zin.read(name).decode("utf-8", "replace")
            for media, flags in _survey_slide(xml, rid_maps[name], set(wanted)).items():
                seen.setdefault(media, []).extend(flags)

        writable = {p for p in wanted if seen.get(p) and all(seen[p])}
        for p, (locator, _) in wanted.items():
            if p not in writable:
                unresolved.append(locator)
        if not writable:
            return data, [], unresolved

        text_by_media = {p: wanted[p][1] for p in writable}
        slides_out: dict[str, str] = {}
        rels_out: dict[str, str] = {}
        for name in slides:
            xml = zin.read(name).decode("utf-8", "replace")
            new_xml, replaced = _rewrite_slide(xml, rid_maps[name], text_by_media)
            if not replaced:
                continue
            slides_out[name] = new_xml
            rels_path = _rels_path(name)
            try:
                rxml = zin.read(rels_path).decode("utf-8", "replace")
            except KeyError:
                continue
            for rid, target in rid_maps[name].items():
                if target in writable:
                    rxml = _strip_rel(rxml, rid)
            rels_out[rels_path] = rxml

        applied = [{"locator": wanted[p][0],
                    "before": "an image with text baked into it — not selectable, not resizable, "
                              "and unreadable to assistive technology",
                    "after": wanted[p][1]}
                   for p in sorted(writable, key=lambda p: wanted[p][0])]

        out_buf = io.BytesIO()
        with zipfile.ZipFile(out_buf, "w", zipfile.ZIP_DEFLATED) as zout:
            for info in zin.infolist():
                name = info.filename
                if name in writable:
                    continue                      # the image itself — this is what clears 1.4.5
                if name in slides_out:
                    zout.writestr(info, slides_out[name].encode("utf-8"))
                elif name in rels_out:
                    zout.writestr(info, rels_out[name].encode("utf-8"))
                else:
                    zout.writestr(info, zin.read(name))

    return out_buf.getvalue(), applied, unresolved
