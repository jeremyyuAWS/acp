"""First-party OOXML/PDF structural checks — extends WCAG coverage to formats
the partner engine doesn't reach for these specific SCs, without touching the
partner's DigitalA11y code at all (same posture as ocr.py/textchecks.py: read
the zip/XML/PDF ourselves).

  2.4.6 Headings and Labels — docx heading-level skips (Heading1→Heading3),
        pptx slide title placeholders present but left empty.
  2.4.9 Link Purpose (Link Only) — docx/pptx hyperlinks: identical display text
        pointing at different real destinations (same algorithm as the HTML
        check in scanner.py, ported to OOXML hyperlink+relationship parsing).
  1.4.3 / 1.4.6 Contrast — PDF text color read from the actual content stream
        via pdfplumber's per-character non_stroking_color (RGB 0..1 floats).
  2.4.1 Bypass Blocks — PDF bookmark/outline tree read via pikepdf (already a
        scan dependency); a document of non-trivial length with zero outline
        entries has no way to skip past repeated content, the PDF analog of a
        missing skip-link. Only checked past a page-count floor (see
        _MIN_PAGES_FOR_OUTLINE) — a 2-page memo doesn't need bookmarks.
  3.3.2 Labels or Instructions — docx content-control form fields (checkbox,
        date picker, dropdown, combo box, picture) with no w:alias title set.
        Scoped to those unambiguous input gallery types only — w:sdt also
        wraps plenty of non-form Word content (TOC blocks, citations,
        building-block placeholders) that legitimately has no alias.
  2.4.10 Section Headings — a docx long enough to need section structure (past a
        text-bearing-paragraph floor) that uses no heading styles at all.
  1.4.8 Visual Presentation — blocks of docx body text set to justified (both
        margins), an explicit 1.4.8 failure. Narrow (justified-text only), not
        the SC's full width/spacing/colour surface.
  1.4.3 / 1.4.6 Contrast (xlsx) — cell font vs. fill color, resolved through
        xl/styles.xml's cellXfs -> fonts/fills chain and luma-diffed the same
        heuristic way as the HTML/PDF contrast checks. DELIBERATELY NARROW:
        only <color rgb="..."/> is resolved (direct RGB). theme= and
        indexed= colors, and non-solid pattern fills (stripes/half-tones),
        resolve to "unknown" and the cell is skipped rather than guessed at
        — theme colors are exactly what Excel's built-in header/table styles
        use, and guessing wrong there is the false-positive risk (flagging
        routine formatting) this check exists to avoid. A cell with no
        explicit fill resolves to white with high confidence (Excel's actual
        default), which is different from "unresolvable" — that's a real,
        positive signal, not a guess.

docx/pptx style IDs (Heading1..9, title placeholder type) are locale-invariant
OOXML identifiers — only the *display* name is localized — so no styles.xml
cross-reference is needed to recognize them.

Scope not covered here (deliberately, see docs/TODO.md P1):
pptx embedded-audio autoplay is BLOCKED, not just deferred: distinguishing an
autoplay media node from a click-triggered one requires the exact p:timing
trigger-condition XML, which could not be verified against a real
PowerPoint-generated ground-truth fixture (no PowerPoint/LibreOffice
available in this environment, and Microsoft's own docs don't spell out the
precise autoplay-vs-click structure) — do not implement this from
memory/guesswork. xlsx conditional-formatting (cfRule) overrides are also
out of scope — evaluating those would need a real formula/condition
evaluator against actual cell values, a much larger scope than a static
style read.

Never raises — a parse failure just means no findings for that document.
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

_HEADING_STYLE = re.compile(r'<w:pStyle\s+w:val="Heading(\d)"\s*/>')
_PARA = re.compile(r"<w:p[ >].*?</w:p>", re.S)
# A body with this many text-bearing paragraphs and zero headings is long enough
# that the lack of section structure is a real 2.4.10 problem (a short letter/memo
# below the floor legitimately needs none).
_MIN_PARAS_FOR_HEADINGS = 15
# Justified (both-margin) alignment is an explicit 1.4.8 failure. Require a few
# text-bearing justified paragraphs so a single incidental justified line (e.g. a
# banner) doesn't trip it — the SC is about blocks of body text. "distribute" is
# East-Asian full-justify, likewise a both-margins failure.
_JC_BOTH = re.compile(r'<w:jc\s+w:val="(?:both|distribute)"\s*/>')
_MIN_JUSTIFIED_PARAS = 3
# rIds are XML "ID" type, not necessarily numeric — Word/PowerPoint always emit
# pure digits (rId4), but any tool producing valid OOXML can use rIdFoo.
_HYPERLINK = re.compile(r'<w:hyperlink[^>]*r:id="(rId\w+)"[^>]*>(.*?)</w:hyperlink>', re.S)
_WT = re.compile(r"<w:t[^>]*>([^<]*)</w:t>")
_RELATIONSHIP = re.compile(r'<Relationship\s+Id="(rId\w+)"[^>]*Target="([^"]+)"')

# Content control (structured document tag) blocks and their title/label.
# w:sdt wraps a LOT of non-form Word content too (TOC blocks, citations,
# building-block placeholders via w:docPartObj) that legitimately has no
# alias and isn't a labeling gap — only the unambiguous interactive-input
# gallery types below are ever genuinely "a form field a user fills in",
# so those are the only ones checked; w:text/w:richText are excluded since
# Word also uses them for non-input template placeholders.
_SDT = re.compile(r"<w:sdt>(.*?)</w:sdt>", re.S)
_SDT_PR = re.compile(r"<w:sdtPr>(.*?)</w:sdtPr>", re.S)
_SDT_INPUT_TYPE = re.compile(r"<w:(checkbox|date|dropDownList|comboBox|picture)\b")
_SDT_ALIAS = re.compile(r'<w:alias\s+w:val="([^"]*)"')

# "title" = normal slide layouts; "ctrTitle" = the Title Slide layout's centered
# title — both are the slide's title for 2.4.6 purposes. Match the whole <p:ph>
# opening tag regardless of extra attributes (e.g. idx="0") or self-closing vs
# paired form — a strict `type=".."/>` missed those and silently skipped the check.
_PPTX_TITLE_PH = re.compile(r'<p:ph\b(?=[^>]*\btype="(?:ctrTitle|title)")[^>]*>')
_A_RUN = re.compile(r"<a:r>(.*?)</a:r>", re.S)
_A_HLINK = re.compile(r'<a:hlinkClick[^>]*r:id="(rId\w+)"')
_AT = re.compile(r"<a:t\b[^>]*>([^<]*)</a:t>")  # tolerate xml:space="preserve" etc.


def _read(zf: zipfile.ZipFile, name: str) -> str | None:
    try:
        return zf.read(name).decode("utf-8", "replace")
    except KeyError:
        return None


def _relationships(zf: zipfile.ZipFile, rels_path: str) -> dict[str, str]:
    xml = _read(zf, rels_path)
    if not xml:
        return {}
    return dict(_RELATIONSHIP.findall(xml))


def _finding(rule_id: str, wcag: str, severity: str) -> dict:
    return {"ruleId": rule_id, "wcag": wcag, "severity": severity}


def _duplicate_href_findings(links: list[tuple[str, str]], rule_id: str, wcag: str) -> list[dict]:
    """links: [(display_text, href), ...]. 2.4.9 fails when identical display
    TEXT points at different destinations. Flag links whose *text* is ambiguous —
    NOT other links that merely share one of those URLs (a distinctly-labelled
    link pointing at the same target as an ambiguous pair is fine, and flagging
    it was a false positive found in review)."""
    groups: dict[str, set[str]] = {}
    for text, href in links:
        key = text.strip().lower()
        if not key or not href:
            continue
        groups.setdefault(key, set()).add(href)
    ambiguous_texts = {k for k, hrefs in groups.items() if len(hrefs) > 1}
    return [_finding(rule_id, wcag, "MODERATE") for text, href in links
            if href and text.strip().lower() in ambiguous_texts]


def docx_checks(path: Path) -> list[dict]:
    findings: list[dict] = []
    try:
        with zipfile.ZipFile(path) as zf:
            doc = _read(zf, "word/document.xml")
            if not doc:
                return []

            # 2.4.6 — heading level skips (e.g. Heading1 → Heading3)
            prev_level = 0
            for m in _HEADING_STYLE.finditer(doc):
                level = int(m.group(1))
                if prev_level > 0 and level > prev_level + 1:
                    findings.append(_finding("DOCX_HEADING_SKIP", "2.4.6 Headings and Labels", "MODERATE"))
                    break
                prev_level = level

            # 2.4.9 — hyperlink display text reused for a different destination
            rels = _relationships(zf, "word/_rels/document.xml.rels")
            links = []
            for rid, inner in _HYPERLINK.findall(doc):
                text = "".join(_WT.findall(inner))
                href = rels.get(rid)
                if href:
                    links.append((text, href))
            findings += _duplicate_href_findings(links, "DOCX_LINK_PURPOSE_AMBIGUOUS", "2.4.9 Link Purpose (Link Only)")

            # 3.3.2 — interactive content-control form fields (checkbox, date
            # picker, dropdown, combo box, picture) with no alias/title set.
            for sdt_inner in _SDT.findall(doc):
                pr_m = _SDT_PR.search(sdt_inner)
                if not pr_m or not _SDT_INPUT_TYPE.search(pr_m.group(1)):
                    continue
                alias_m = _SDT_ALIAS.search(pr_m.group(1))
                if not alias_m or not alias_m.group(1).strip():
                    findings.append(_finding("DOCX_FORM_FIELD_NO_LABEL", "3.3.2 Labels or Instructions", "SERIOUS"))

            # 2.4.10 — a document long enough to need section structure that uses
            # no heading styles at all. A short letter/memo legitimately has none,
            # so this only fires past a text-bearing-paragraph floor.
            if not _HEADING_STYLE.search(doc):
                text_paras = sum(
                    1 for p in _PARA.findall(doc) if "".join(_WT.findall(p)).strip()
                )
                if text_paras >= _MIN_PARAS_FOR_HEADINGS:
                    findings.append(_finding("DOCX_NO_SECTION_HEADINGS", "2.4.10 Section Headings", "MODERATE"))

            # 1.4.8 — blocks of body text set justified (both margins). Narrow but
            # unambiguous: justified alignment is one of the SC's explicit failures.
            justified = sum(
                1 for p in _PARA.findall(doc)
                if _JC_BOTH.search(p) and "".join(_WT.findall(p)).strip()
            )
            if justified >= _MIN_JUSTIFIED_PARAS:
                findings.append(_finding("DOCX_JUSTIFIED_TEXT", "1.4.8 Visual Presentation", "MODERATE"))
    except Exception:
        pass
    return findings


def pptx_checks(path: Path) -> list[dict]:
    findings: list[dict] = []
    try:
        with zipfile.ZipFile(path) as zf:
            slide_names = sorted(
                n for n in zf.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)
            )
            all_links: list[tuple[str, str]] = []
            for slide_name in slide_names:
                xml = _read(zf, slide_name)
                if not xml:
                    continue

                # 2.4.6 — a title placeholder exists on this slide's layout but
                # was left empty (blank-layout slides with no title slot at all
                # are a legitimate design choice, not flagged).
                title_ph = _PPTX_TITLE_PH.search(xml)
                if title_ph:
                    # Text of the shape containing the title placeholder — a
                    # reasonable approximation is: does *any* <a:t> appear after
                    # the placeholder marker, before the next shape?
                    after = xml[title_ph.end():]
                    shape_text = after.split("</p:sp>", 1)[0]
                    if not _AT.search(shape_text) or not "".join(_AT.findall(shape_text)).strip():
                        findings.append(_finding("PPTX_TITLE_EMPTY", "2.4.6 Headings and Labels", "MODERATE"))

                # 2.4.9 — hyperlink display text reused for a different destination.
                # hlinkClick lives inside <a:rPr>, which precedes the run's own
                # <a:t> text — the link and its text share a <a:r>...</a:r> run,
                # so extract both from within the same run rather than scanning
                # for "nearest preceding text" (which finds the WRONG run's text).
                slide_num = re.search(r"slide(\d+)\.xml", slide_name).group(1)
                rels = _relationships(zf, f"ppt/slides/_rels/slide{slide_num}.xml.rels")
                for run_inner in _A_RUN.findall(xml):
                    m = _A_HLINK.search(run_inner)
                    if not m:
                        continue
                    href = rels.get(m.group(1))
                    if not href:
                        continue
                    text = "".join(_AT.findall(run_inner))
                    all_links.append((text, href))
            findings += _duplicate_href_findings(all_links, "PPTX_LINK_PURPOSE_AMBIGUOUS", "2.4.9 Link Purpose (Link Only)")
    except Exception:
        pass
    return findings


# ── 1.4.3 / 1.4.6 pptx contrast ───────────────────────────────────────────────
# Deliberately narrow, mirroring xlsx_contrast_checks: only a text run whose
# colour is an EXPLICIT <a:srgbClr>, sitting inside a shape whose fill is ALSO an
# explicit <a:srgbClr> solid fill, is measured. Theme colours, gradient/picture
# fills, and text on the slide/layout/master background (a shape with no fill of
# its own) are skipped — not guessed. Estimating luma against an unknown inherited
# background would invent findings, which is worse than a conservative miss. The
# luma-difference thresholds are the same approximation as xlsx (not a true WCAG
# contrast ratio); one AA + one AAA finding per file at most.
_PPTX_SP = re.compile(r"<p:sp>.*?</p:sp>", re.S)
_PPTX_SPPR = re.compile(r"<p:spPr\b.*?</p:spPr>", re.S)
_A_LN_BLOCK = re.compile(r"<a:ln\b.*?</a:ln>", re.S)
_SOLID_SRGB = re.compile(r'<a:solidFill>\s*<a:srgbClr val="([0-9A-Fa-f]{6})"')


def _wcag_luminance(hex6: str) -> float:
    """WCAG 2.x relative luminance of an #RRGGBB colour (sRGB-linearised)."""
    def _lin(c: int) -> float:
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return (0.2126 * _lin(int(hex6[0:2], 16))
            + 0.7152 * _lin(int(hex6[2:4], 16))
            + 0.0722 * _lin(int(hex6[4:6], 16)))


def _contrast_ratio(hex_a: str, hex_b: str) -> float:
    """True WCAG contrast ratio (1..21) — not a luma-difference proxy."""
    la, lb = _wcag_luminance(hex_a), _wcag_luminance(hex_b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def pptx_contrast_checks(path: Path) -> list[dict]:
    """1.4.3 / 1.4.6 Contrast for pptx — explicit run colour on an explicit shape
    solid fill only (see the narrow-scope note above).

    Thresholds are the WCAG *large-text* ratios (AA 3:1, AAA 4.5:1). Font size
    isn't reliably knowable per run (it's often inherited from the placeholder),
    so flagging only below the large-text bar guarantees every finding is a real
    failure at *any* size — a genuine result over an over-eager one."""
    seen_aa = seen_aaa = False
    try:
        with zipfile.ZipFile(path) as zf:
            for slide_name in sorted(n for n in zf.namelist()
                                     if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)):
                xml = _read(zf, slide_name)
                if not xml:
                    continue
                for sp in _PPTX_SP.findall(xml):
                    sppr_m = _PPTX_SPPR.search(sp)
                    if not sppr_m:
                        continue
                    # The shape's own fill — strip the <a:ln> border block first so a
                    # coloured outline is never mistaken for the background fill.
                    fill_m = _SOLID_SRGB.search(_A_LN_BLOCK.sub("", sppr_m.group(0)))
                    if not fill_m:
                        continue
                    for run in _A_RUN.findall(sp):
                        col_m = _SOLID_SRGB.search(run)      # the run's own text colour
                        if not col_m or not "".join(_AT.findall(run)).strip():
                            continue
                        ratio = _contrast_ratio(fill_m.group(1), col_m.group(1))
                        if ratio < 4.5:
                            seen_aaa = True
                        if ratio < 3.0:
                            seen_aa = True
                if seen_aa and seen_aaa:
                    break
    except Exception:
        return []
    findings: list[dict] = []
    if seen_aa:
        findings.append(_finding("PPTX_LOW_CONTRAST_AA", "1.4.3 Contrast (Minimum)", "SERIOUS"))
    if seen_aaa:
        findings.append(_finding("PPTX_LOW_CONTRAST_AAA", "1.4.6 Contrast (Enhanced)", "MODERATE"))
    return findings


# 4.5:1 (AA) / 7:1 (AAA) approximated the same way as scanner.py's HTML contrast
# checks — relative luma of the declared color; not a true APCA/WCAG contrast-
# ratio computation against the actual background, which for a PDF would need
# per-glyph background sampling. Consistent with the existing HTML heuristic.
# Caps to bound pdfplumber work on huge PDFs — but large enough to reach body text
# past a high-contrast heading (the old 40-char slice stopped inside the header and
# missed light-grey body that followed → false negative).
_MAX_CHARS_PER_PAGE = 600
_MAX_CHARS_TOTAL = 4000


def _pdf_luma(color) -> float | None:
    """Relative luma 0..1 from pdfplumber's non_stroking_color, which may be a
    single float (DeviceGray), a 3-tuple (RGB), or a 4-tuple (CMYK). A bare RGB
    slice of a CMYK value silently mis-reads it (light-grey CMYK looked pure
    black → never flagged), and gray singletons were dropped entirely."""
    try:
        if isinstance(color, (int, float)):
            return float(color)
        if not isinstance(color, (tuple, list)) or not color:
            return None
        vals = [float(v) for v in color]
        if len(vals) == 1:
            return vals[0]
        if len(vals) == 3:
            r, g, b = vals
        elif len(vals) == 4:
            c, m, y, k = vals
            r, g, b = (1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k)
        else:
            return None
        return 0.299 * r + 0.587 * g + 0.114 * b
    except (TypeError, ValueError):
        return None


def pdf_contrast_checks(path: Path) -> list[dict]:
    findings: list[dict] = []
    seen_aa = seen_aaa = False
    total = 0
    try:
        import pdfplumber
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages:
                for ch in page.chars[:_MAX_CHARS_PER_PAGE]:
                    total += 1
                    luma = _pdf_luma(ch.get("non_stroking_color"))
                    if luma is None:
                        continue
                    if luma > 0.45:
                        seen_aaa = True
                    if luma > 0.62:
                        seen_aa = True
                if (seen_aa and seen_aaa) or total >= _MAX_CHARS_TOTAL:
                    break
    except Exception:
        return []
    if seen_aa:
        findings.append(_finding("PDF_LOW_CONTRAST_AA", "1.4.3 Contrast (Minimum)", "SERIOUS"))
    if seen_aaa:
        findings.append(_finding("PDF_LOW_CONTRAST_AAA", "1.4.6 Contrast (Enhanced)", "MODERATE"))
    return findings


# A short memo/letter has no real "bypass repeated blocks" problem — bookmarks
# only start pulling their weight once a reader would otherwise have to scroll
# past several pages of unrelated content to find a section. Matches common
# PDF/UA guidance (Adobe's own authoring recommendation) of ~9+ pages; we use
# a lower, more conservative floor since ACP's corpus skews toward multi-page
# legal documents (affidavits, contracts, briefs) where navigation matters
# earlier than in a typical office memo.
_MIN_PAGES_FOR_OUTLINE = 5


def pdf_bypass_blocks_check(path: Path) -> list[dict]:
    """2.4.1 Bypass Blocks — a PDF's bookmark/outline tree is the direct analog
    of an HTML skip-link: without it, a screen-reader or keyboard user has no
    way to jump past repeated content (headers, boilerplate, TOC) to the
    section they need. Flags documents at/above _MIN_PAGES_FOR_OUTLINE with a
    completely empty outline tree."""
    try:
        import pikepdf
        with pikepdf.open(str(path)) as pdf:
            if len(pdf.pages) < _MIN_PAGES_FOR_OUTLINE:
                return []
            with pdf.open_outline() as outline:
                if outline.root:
                    return []
    except Exception:
        return []
    return [_finding("PDF_NO_BOOKMARKS", "2.4.1 Bypass Blocks", "MODERATE")]


# styles.xml holds several look-alike collections. The real cell formats a cell's
# s="N" indexes live ONLY in <cellXfs>; <cellStyleXfs> (named styles) and the
# <dxfs> differential formats (conditional formatting) share the <xf>/<font>/<fill>
# tag names but must NOT be counted — mixing them shifts every index and resolves
# the wrong colour (both false pos and false neg). So scope each list to its
# container block first, then enumerate within.
_FONTS_CONTAINER = re.compile(r"<fonts\b[^>]*>(.*?)</fonts>", re.S)
_FILLS_CONTAINER = re.compile(r"<fills\b[^>]*>(.*?)</fills>", re.S)
_CELLXFS_CONTAINER = re.compile(r"<cellXfs\b[^>]*>(.*?)</cellXfs>", re.S)
_FONT_BLOCK = re.compile(r"<font>(.*?)</font>", re.S)
_FILL_BLOCK = re.compile(r"<fill>(.*?)</fill>", re.S)
_XF = re.compile(r"<xf\b[^>]*?/>|<xf\b[^>]*?>.*?</xf>", re.S)


def _container(container_re, styles: str) -> str:
    m = container_re.search(styles)
    return m.group(1) if m else ""
_ATTR_INT = lambda name: re.compile(rf'\b{name}="(\d+)"')  # noqa: E731
_FONT_ID, _FILL_ID = _ATTR_INT("fontId"), _ATTR_INT("fillId")
_PATTERN_TYPE = re.compile(r'patternType="([^"]*)"')
_FG_COLOR = re.compile(r"<fgColor\b([^/]*)/>")
_CELL = re.compile(r'<c\b[^>]*\bs="(\d+)"[^>]*(?:/>|>(.*?)</c>)', re.S)


def _explicit_rgb(color_attrs: str) -> str | None:
    """Only <color rgb="XXXXXXXX"/> (or <fgColor rgb=.../>) resolves — theme=
    and indexed= colors return None (unresolvable), matching the module-level
    stance: guessing at a theme/indexed color is exactly the false-positive
    risk (flagging routine header/table styling) this check must avoid."""
    m = re.search(r'rgb="([0-9A-Fa-f]{6,8})"', color_attrs)
    return m.group(1)[-6:].upper() if m else None


def _xlsx_font_color(font_xml: str) -> str | None:
    m = re.search(r"<color\b([^/]*)/>", font_xml)
    return _explicit_rgb(m.group(1)) if m else None


def _xlsx_fill_color(fill_xml: str) -> str | None:
    """None = truly unresolvable (skip). '#FFFFFF' (as a real value, not a
    sentinel) for a confidently-white default: absent/none pattern type IS
    Excel's real default background, a positive signal, not a guess. Any
    other pattern type (stripes/half-tones) is unresolvable."""
    pt_m = _PATTERN_TYPE.search(fill_xml)
    pattern_type = pt_m.group(1) if pt_m else ""
    if not pattern_type or pattern_type == "none":
        return "FFFFFF"
    if pattern_type != "solid":
        return None
    fg_m = _FG_COLOR.search(fill_xml)
    return _explicit_rgb(fg_m.group(1)) if fg_m else None


def _hex_luma(hexcolor: str) -> float:
    r, g, b = (int(hexcolor[i:i + 2], 16) for i in (0, 2, 4))
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255


def xlsx_contrast_checks(path: Path) -> list[dict]:
    """1.4.3 / 1.4.6 Contrast — see module docstring for the deliberately
    narrow resolution scope (direct RGB only; theme/indexed/patterned fills
    are skipped, not guessed at)."""
    findings: list[dict] = []
    try:
        with zipfile.ZipFile(path) as zf:
            styles = _read(zf, "xl/styles.xml")
            if not styles:
                return []
            fonts = [_xlsx_font_color(m) for m in _FONT_BLOCK.findall(_container(_FONTS_CONTAINER, styles))]
            fills = [_xlsx_fill_color(m) for m in _FILL_BLOCK.findall(_container(_FILLS_CONTAINER, styles))]

            style_colors: dict[int, tuple[str, str]] = {}
            for i, xf in enumerate(_XF.findall(_container(_CELLXFS_CONTAINER, styles))):
                fid_m, filid_m = _FONT_ID.search(xf), _FILL_ID.search(xf)
                if not fid_m or not filid_m:
                    continue
                font_hex = fonts[int(fid_m.group(1))] if int(fid_m.group(1)) < len(fonts) else None
                fill_hex = fills[int(filid_m.group(1))] if int(filid_m.group(1)) < len(fills) else None
                if font_hex and fill_hex:
                    style_colors[i] = (font_hex, fill_hex)

            seen_aa = seen_aaa = False
            for sheet_name in sorted(n for n in zf.namelist()
                                      if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n)):
                sheet_xml = _read(zf, sheet_name)
                if not sheet_xml:
                    continue
                for style_idx, content in _CELL.findall(sheet_xml):
                    if not content or not content.strip():
                        continue
                    colors = style_colors.get(int(style_idx))
                    if not colors:
                        continue
                    diff = abs(_hex_luma(colors[0]) - _hex_luma(colors[1]))
                    if diff < 0.5:
                        seen_aaa = True
                    if diff < 0.3:
                        seen_aa = True
                if seen_aa and seen_aaa:
                    break
    except Exception:
        return []
    if seen_aa:
        findings.append(_finding("XLSX_LOW_CONTRAST_AA", "1.4.3 Contrast (Minimum)", "SERIOUS"))
    if seen_aaa:
        findings.append(_finding("XLSX_LOW_CONTRAST_AAA", "1.4.6 Contrast (Enhanced)", "MODERATE"))
    return findings


def checks_for(path: Path, ext: str) -> list[dict]:
    """Dispatch by extension; returns [] for formats with no structural check yet."""
    ext = ext.lower()
    if ext == ".docx":
        return docx_checks(path)
    if ext == ".pptx":
        return pptx_checks(path) + pptx_contrast_checks(path)
    if ext == ".pdf":
        return pdf_contrast_checks(path) + pdf_bypass_blocks_check(path)
    if ext == ".xlsx":
        return xlsx_contrast_checks(path)
    return []
