"""Server-side Office remediation (ADR 0005 step 4 — docx/pptx/xlsx).

The vendored DigitalA11y .NET engine flags Office accessibility issues but is
scan-only — there's no Office remediator to wrap. So this implements the
DETERMINISTIC Office fixes directly, in pure stdlib (no new dependency):

  * document language  → dc:language in docProps/core.xml  (the exact thing the
                         .NET DocumentLanguageRule reads: PackageProperties.Language)
  * document title     → dc:title    in docProps/core.xml  (DocumentTitleRule reads
                         PackageProperties.Title)
  * image alt text     → descr= on wp:docPr / p:cNvPr / xdr:cNvPr (what the
                         .NET AltTextRule reads) — derived ONLY from faithful
                         in-document sources: the author's own Alt-Text *Title*
                         field, an adjacent "Figure N:" caption paragraph (docx),
                         or a meaningful shape name. Images with no faithful
                         source are left untouched and reported as deferred —
                         writing invented alt text is worse than none.

OOXML files are zip archives of XML; the OPC core-properties part is identical
across docx/pptx/xlsx, so one code path covers all three. Anything needing
content judgement beyond the faithful-source rule above (reading order,
contrast, alt for context-free images) is NOT touched here and routes to human
review — same contract as the HTML/PDF remediators.
"""
from __future__ import annotations
import os
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

_CORE = "docProps/core.xml"
_CUSTOM = "docProps/custom.xml"
_FMTID = "{D5CDD505-2E9C-101B-9397-08002B2CF9AE}"  # standard OPC custom-properties GUID
TOOL = "Mova.io ACP"
# CalVer build version (v2026.M.D.N) — the same value /healthz and the UI report, so a
# remediated file's provenance stamp matches the deployed build. ACP_BUILD_VERSION is
# baked onto the image by deploy.sh; fall back to the legacy ACP_VERSION, then 'dev'.
VERSION = os.environ.get("ACP_BUILD_VERSION") or os.environ.get("ACP_VERSION") or "dev"


def _xesc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _stamp_provenance(entries: dict, applied: list[str]) -> None:
    """Write a remediation provenance stamp into docProps/custom.xml — shows in the
    'Custom' tab of the file's Properties: who/what fixed it, the standard, the date,
    and the fixes applied. Creates the part (+ content-type + relationship) if absent,
    or appends to an existing custom-properties part."""
    props = [
        ("Remediated By", TOOL),
        ("ACP Version", VERSION),
        ("Remediation Date", datetime.now(timezone.utc).strftime("%Y-%m-%d")),
        ("WCAG Target", "WCAG 2.1 AA"),
        ("Fixes Applied", "; ".join(applied)[:255]),
    ]
    if _CUSTOM in entries:  # append, continuing the pid sequence; part already declared
        xml = entries[_CUSTOM].decode("utf-8", "replace")
        pids = [int(m) for m in re.findall(r'pid="(\d+)"', xml)]
        start = (max(pids) + 1) if pids else 2
        frag = "".join(
            f'<property fmtid="{_FMTID}" pid="{start + i}" name="{_xesc(n)}">'
            f'<vt:lpwstr>{_xesc(v)}</vt:lpwstr></property>'
            for i, (n, v) in enumerate(props))
        entries[_CUSTOM] = xml.replace("</Properties>", frag + "</Properties>").encode("utf-8")
        return
    body = "".join(
        f'<property fmtid="{_FMTID}" pid="{2 + i}" name="{_xesc(n)}">'
        f'<vt:lpwstr>{_xesc(v)}</vt:lpwstr></property>'
        for i, (n, v) in enumerate(props))
    entries[_CUSTOM] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'
        '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/custom-properties" '
        'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
        + body + '</Properties>').encode("utf-8")
    ct = "[Content_Types].xml"
    if ct in entries and "docProps/custom.xml" not in entries[ct].decode("utf-8", "replace"):
        ov = ('<Override PartName="/docProps/custom.xml" '
              'ContentType="application/vnd.openxmlformats-officedocument.custom-properties+xml"/>')
        entries[ct] = entries[ct].decode("utf-8").replace("</Types>", ov + "</Types>").encode("utf-8")
    rels = "_rels/.rels"
    if rels in entries and "custom-properties" not in entries[rels].decode("utf-8", "replace"):
        rel = ('<Relationship Id="rIdACPprov" '
               'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/custom-properties" '
               'Target="docProps/custom.xml"/>')
        entries[rels] = entries[rels].decode("utf-8").replace("</Relationships>", rel + "</Relationships>").encode("utf-8")
_CP = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
_DC = "http://purl.org/dc/elements/1.1/"
_NS = {
    "cp": _CP, "dc": _DC,
    "dcterms": "http://purl.org/dc/terms/",
    "dcmitype": "http://purl.org/dc/dcmitype/",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
}


# ── Image alt text (DOCX/PPTX/XLSX-ALT-001, WCAG 1.1.1) ───────────────────────
# The .NET AltTextRule reads descr= on wp:docPr (docx), p:cNvPr (pptx pictures)
# and xdr:cNvPr (xlsx drawings). Fixes are string-surgical — descr is injected
# into the exact original tag text so every other byte of the part is preserved
# (OOXML consumers are picky about re-serialization).
_GENERIC_NAME = re.compile(
    r"^\s*(picture|image|graphic|grafik|imagen|chart|diagramm|shape|object|content placeholder)\s*\d*\s*$",
    re.I)
_CAPTION_LEAD = re.compile(r"^\s*((figure|fig\.?|table|chart|diagram|abb\.?)\s*\d*[:.\s—-]\s*)", re.I)
# descr values that are effectively no alt at all: empty, a bare filename
# ("image.png"), or a generic auto-name — the .NET AltTextRule flags these too.
_JUNK_DESCR = re.compile(
    r"^\s*(?:img|image|picture|photo|graphic|grafik)?[\s_-]*\d*\s*"
    r"(?:\.(?:png|jpe?g|gif|bmp|svg|tiff?|emf|wmf))?\s*$", re.I)
_ATTR = lambda attrs, name: (re.search(rf'\b{name}="([^"]*)"', attrs) or [None, ""])[1]


def _strip_tags(xml_chunk: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", xml_chunk)).strip()


def _derive_alt(attrs: str, caption: str | None) -> tuple[str, str] | None:
    """Faithful alt source, in priority order. Returns (alt, source) or None."""
    title = _ATTR(attrs, "title").strip()
    if title:
        return title, "the image's own Alt-Text title"
    if caption:
        cap = _CAPTION_LEAD.sub("", caption).strip()
        if len(cap) >= 4:
            return cap[:250], "the adjacent caption"
    name = _ATTR(attrs, "name").strip()
    if name and not _GENERIC_NAME.match(name):
        return name, "the shape's descriptive name"
    return None


def _inject_descr(xml: str, tag: str, *, pic_only_within: str | None = None,
                  captions: bool = False) -> tuple[str, list[tuple[str, str]], int]:
    """Add descr= to every <tag …> lacking one, when a faithful source exists.

    pic_only_within: restrict to tags inside <pic>…</pic> blocks (pptx/xlsx have
    cNvPr on every shape; only pictures need alt). captions: derive from the next
    paragraph's text when it looks like a caption (docx).
    Returns (new_xml, [(alt, source)…], deferred_count).
    """
    fixed: list[tuple[str, str]] = []
    deferred = 0
    pic_spans = None
    if pic_only_within:
        pic_spans = [m.span() for m in re.finditer(
            rf"<{pic_only_within}[ >].*?</{pic_only_within}>", xml, re.S)]

    out, last = [], 0
    for m in re.finditer(rf"<{tag}\b([^>]*?)(/?)>", xml):
        attrs, selfclose = m.group(1), m.group(2)
        out.append(xml[last:m.start()]); last = m.end()
        keep = m.group(0)
        inside_pic = pic_spans is None or any(a <= m.start() < b for a, b in pic_spans)
        if inside_pic and _JUNK_DESCR.match(_ATTR(attrs, "descr")):
            # decorative? the marker lives in the element's extLst children
            block_end = xml.find(f"</{tag}>", m.end()) if not selfclose else m.end()
            block = xml[m.start():block_end if block_end != -1 else m.end()]
            if 'decorative val="1"' in block or "decorative val='1'" in block:
                out.append(keep); continue
            caption = None
            if captions:
                # text of the paragraph following the one holding this drawing
                p_end = xml.find("</w:p>", m.end())
                if p_end != -1:
                    nxt = re.search(r"<w:p[ >].*?</w:p>", xml[p_end + 6:], re.S)
                    if nxt:
                        cand = _strip_tags(nxt.group(0))
                        if _CAPTION_LEAD.match(cand):
                            caption = cand
            src = _derive_alt(attrs, caption)
            if src is None:
                deferred += 1
                out.append(keep); continue
            alt, origin = src
            new_attrs = re.sub(r'\s*\bdescr="[^"]*"', "", attrs)  # drop the empty/junk descr
            keep = f'<{tag}{new_attrs} descr="{_xesc(alt)}"{selfclose}>'
            fixed.append((alt, origin))
        out.append(keep)
    out.append(xml[last:])
    return "".join(out), fixed, deferred


# part-glob → (tag, pic wrapper or None, captions?)
_ALT_TARGETS = [
    (re.compile(r"^word/(document|header\d*|footer\d*)\.xml$"), "wp:docPr", None, True),
    (re.compile(r"^ppt/slides/slide\d+\.xml$"), "p:cNvPr", "p:pic", False),
    (re.compile(r"^xl/drawings/drawing\d+\.xml$"), "xdr:cNvPr", "xdr:pic", False),
]


def _fix_image_alt(entries: dict) -> tuple[list[str], int]:
    """Inject faithful alt text across all image-bearing parts.
    Returns (applied descriptions, count of images deferred to human review)."""
    applied: list[str] = []
    deferred = 0
    for name in list(entries):
        for pat, tag, wrapper, captions in _ALT_TARGETS:
            if not pat.match(name):
                continue
            try:
                xml = entries[name].decode("utf-8")
            except UnicodeDecodeError:
                continue
            new_xml, fixed, part_deferred = _inject_descr(
                xml, tag, pic_only_within=wrapper, captions=captions)
            deferred += part_deferred
            if fixed:
                entries[name] = new_xml.encode("utf-8")
                for alt, origin in fixed:
                    applied.append(f"Alt text \"{alt[:60]}\" set from {origin} · 1.1.1")
    return applied, deferred


# ── pptx slide-level structural remediation (2.4.2 / 1.4.3 / 1.4.6 / 1.3.2) ────
# These need the slide XML, not just OPC core-properties, and are pptx-only.
# Each was verified against the DigitalA11y engine (re-scan clears the finding):
#   * title   — an off-slide title placeholder (y above the canvas) is read by AT
#               and clears "slide is missing a title" without touching the design.
#   * contrast— an explicit low-contrast run's colour is swapped to black or white,
#               whichever reaches >=4.5:1 on the shape's explicit fill.
#   * reading — spTree children are sorted by visual position (y, then x). This
#               also sets z-order (first-in-document renders lowest); top-left
#               backgrounds (y~=0) sort first, so typical stacking is preserved.
# Only explicit srgbClr colours on explicit solid fills are recoloured — the same
# narrow scope office_structure.pptx_contrast_checks measures, so every recolour
# targets a run the scanner actually flagged. All changes go in the provenance stamp.
_PPTX_TITLE_PH = re.compile(r'<p:ph\b(?=[^>]*\btype="(?:ctrTitle|title)")')
_A_T = re.compile(r"<a:t\b[^>]*>([^<]*)</a:t>")
_A_R = re.compile(r"<a:r>.*?</a:r>", re.S)
_P_SP = re.compile(r"<p:sp>.*?</p:sp>", re.S)


def _pptx_has_title(xml: str) -> bool:
    m = _PPTX_TITLE_PH.search(xml)
    if not m:
        return False
    return bool("".join(_A_T.findall(xml[m.end():].split("</p:sp>", 1)[0])).strip())


_title_seq = [9000]


def _pptx_add_title(xml: str, text: str) -> str:
    _title_seq[0] += 1
    sp = (f'<p:sp><p:nvSpPr><p:cNvPr id="{_title_seq[0]}" name="Title {_title_seq[0]}"/>'
          f'<p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr><p:nvPr><p:ph type="title"/></p:nvPr>'
          f'</p:nvSpPr><p:spPr><a:xfrm><a:off x="457200" y="-1200000"/>'
          f'<a:ext cx="8229600" cy="1000000"/></a:xfrm></p:spPr>'
          f'<p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr lang="en-US"/>'
          f'<a:t>{_xesc(text)}</a:t></a:r></a:p></p:txBody></p:sp>')
    # grpSpPr may be a closing tag (<p:grpSpPr>…</p:grpSpPr>) or self-closing
    # (<p:grpSpPr/>); insert the title placeholder right after it either way. A
    # lambda replacement avoids treating the shape XML as a backreference template.
    return re.sub(r"</p:grpSpPr>|<p:grpSpPr\s*/>", lambda m: m.group(0) + sp, xml, count=1)


def _remediate_pptx_slides(entries: dict) -> list[str]:
    """Mutate ppt/slides/*.xml in place; return the list of applied-fix messages."""
    import office_structure as _osx           # contrast helpers + narrow-scope regexes
    from xml.etree import ElementTree as ET
    P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
    A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
    shape_tags = {P + t for t in ("sp", "pic", "graphicFrame", "grpSp", "cxnSp")}
    slides = sorted((n for n in entries if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                    key=lambda s: int(re.search(r"(\d+)", s).group()))
    n_title = n_recolor = n_reorder = 0

    def recolor_run_in_sp(sp_match) -> str:
        nonlocal n_recolor
        sp = sp_match.group(0)
        sppr = _osx._PPTX_SPPR.search(sp)
        if not sppr:
            return sp
        fill = _osx._SOLID_SRGB.search(_osx._A_LN_BLOCK.sub("", sppr.group(0)))
        if not fill:
            return sp
        bg = fill.group(1)

        def fix_run(rm):
            nonlocal n_recolor
            run = rm.group(0)
            col = _osx._SOLID_SRGB.search(run)
            if not col or _osx._contrast_ratio(bg, col.group(1)) >= 4.5:
                return run
            if not "".join(_A_T.findall(run)).strip():
                return run
            new = "000000" if _osx._contrast_ratio(bg, "000000") >= _osx._contrast_ratio(bg, "FFFFFF") else "FFFFFF"
            n_recolor += 1
            return run.replace(f'srgbClr val="{col.group(1)}"', f'srgbClr val="{new}"', 1)

        return _A_R.sub(fix_run, sp)

    def reorder(data: bytes) -> bytes:
        nonlocal n_reorder
        for pfx, uri in (("p", P[1:-1]), ("a", A[1:-1]),
                         ("r", "http://schemas.openxmlformats.org/officeDocument/2006/relationships")):
            ET.register_namespace(pfx, uri)
        root = ET.fromstring(data)
        tree = root.find(f".//{P}cSld/{P}spTree")
        if tree is None:
            return data
        shapes = [c for c in list(tree) if c.tag in shape_tags]

        def key(el):
            off = el.find(f".//{A}off")
            return (int(off.get("y")), int(off.get("x"))) if off is not None and off.get("y") else (10 ** 12, 0)

        ordered = sorted(shapes, key=key)
        if ordered != shapes:
            n_reorder += 1
            for s in shapes:
                tree.remove(s)
            for s in ordered:
                tree.append(s)
            return ET.tostring(root, encoding="utf-8", xml_declaration=True)
        return data

    for sn in slides:
        xml = entries[sn].decode("utf-8")
        if not _pptx_has_title(xml):
            texts = [t.strip() for t in _A_T.findall(xml) if t.strip()]
            xml = _pptx_add_title(xml, (max(texts, key=len) if texts else "Untitled slide")[:250])
            n_title += 1
        xml = _P_SP.sub(recolor_run_in_sp, xml)
        entries[sn] = reorder(xml.encode("utf-8"))

    applied: list[str] = []
    if n_title:
        applied.append(f"Added a programmatic title to {n_title} slide(s)")
    if n_recolor:
        applied.append(f"Raised colour contrast to ≥4.5:1 on {n_recolor} text run(s)")
    if n_reorder:
        applied.append(f"Set reading order (visual top-to-bottom) on {n_reorder} slide(s)")
    return applied


def remediate_office(path: Path, *, lang: str = "en-US"):
    """Apply deterministic Office accessibility fixes to a copy of the file.

    Returns (fixed_path, applied, skipped). fixed_path is None if nothing applied.
    """
    try:
        with zipfile.ZipFile(path) as zin:
            names = zin.namelist()
            if _CORE not in names:
                return None, [], ["no OPC core-properties part — cannot set language/title"]
            entries = {n: zin.read(n) for n in names}
    except Exception as e:
        return None, [], [f"could not open Office file: {type(e).__name__}"]

    for pfx, uri in _NS.items():
        ET.register_namespace(pfx, uri)
    root = ET.fromstring(entries[_CORE].decode("utf-8"))
    applied: list[str] = []

    def _ensure(tag_uri: str, tag: str, value: str, label: str):
        el = root.find(f"{{{tag_uri}}}{tag}")
        if el is None or not (el.text or "").strip():
            if el is None:
                el = ET.SubElement(root, f"{{{tag_uri}}}{tag}")
            el.text = value
            applied.append(label.format(value=value))

    _ensure(_DC, "language", lang, "Set document language to '{value}'")
    # A meaningful title beats an empty one; derive a readable default from the name.
    title = path.stem.replace("-", " ").replace("_", " ").strip() or "Document"
    _ensure(_DC, "title", title, "Set document title to '{value}'")

    # Image alt text (WCAG 1.1.1) — faithful sources only; the rest defer to review.
    alt_applied, alt_deferred = _fix_image_alt(entries)
    applied.extend(alt_applied)
    skipped: list[str] = []
    if alt_deferred:
        skipped.append(f"{alt_deferred} image(s) lack a faithful alt source — "
                       "needs human alt text (routed to review)")

    # pptx-only structural fixes that need the slide XML (title / contrast / reading order).
    if path.suffix.lower() == ".pptx":
        try:
            applied.extend(_remediate_pptx_slides(entries))
        except Exception:
            skipped.append("slide-level pptx fixes (title/contrast/reading order) could not be applied")

    if not applied:
        return None, [], skipped or ["language and title already set"]

    # Also stamp the STANDARD (visible) core properties: the remediation date as the
    # Modified date + "Last saved by" — so it shows on the General tab, not only Custom.
    _DCTERMS, _XSI = _NS["dcterms"], _NS["xsi"]
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lmb = root.find(f"{{{_CP}}}lastModifiedBy")
    if lmb is None:
        lmb = ET.SubElement(root, f"{{{_CP}}}lastModifiedBy")
    lmb.text = TOOL
    mod = root.find(f"{{{_DCTERMS}}}modified")
    if mod is None:
        mod = ET.SubElement(root, f"{{{_DCTERMS}}}modified")
    mod.set(f"{{{_XSI}}}type", "dcterms:W3CDTF")
    mod.text = ts

    new_core = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'
                + ET.tostring(root, encoding="unicode"))
    entries[_CORE] = new_core.encode("utf-8")

    # Tamper-evident provenance in the Custom-properties tab (who/what/when/standard).
    _stamp_provenance(entries, applied)

    out_path = path.with_name(f"remediated-{path.name}")
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zout:
        for name, data in entries.items():           # preserves archive order
            zout.writestr(name, data)
    return out_path, applied, skipped
