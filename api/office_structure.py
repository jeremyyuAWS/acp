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

import io
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

# 1.3.1 / 2.4.6 — a paragraph visually styled as a heading (bold and/or a font clearly
# larger than body text) but left in a body style, so assistive tech can't navigate to it.
# The predicate is SHARED with the remediator (api/remediate_office.py imports it) so the
# fix promotes exactly what this flags and the re-scan verifiably clears. Deliberately
# conservative — gated on a clearly-larger font (≥14pt), since the fix auto-applies and a
# false positive would restyle real body text as a heading.
PSEUDO_HEADING_MIN_HALF_PT = 28       # 14pt (half-points); body text is ~22 (11pt)
_PSEUDO_HEADING_MAX_WORDS = 12
_HEADING_ANY = re.compile(r'<w:pStyle\s+w:val="Heading\d"')
_W_SZ = re.compile(r'<w:sz\s+w:val="(\d+)"')
_W_BOLD = re.compile(r'<w:b(?:\s*/>|\s+w:val="(?:1|true|on)"\s*/>)')
_HAS_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)


def looks_like_pseudo_heading(text: str, *, bold: bool, max_half_pt: int,
                              styled_heading: bool) -> bool:
    """True when a paragraph reads as a heading but is not styled as one. Shared by the
    detector below and the remediator's promoter so detection and fix stay in lock-step."""
    if styled_heading:
        return False
    t = (text or "").strip()
    if not t or not _HAS_LETTER.search(t) or len(t.split()) > _PSEUDO_HEADING_MAX_WORDS:
        return False
    if max_half_pt >= PSEUDO_HEADING_MIN_HALF_PT:
        return True
    # a slightly-smaller but bold-and-short line is still heading-like
    return bool(bold and max_half_pt >= PSEUDO_HEADING_MIN_HALF_PT - 2)

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


def _review_finding(rule_id: str, wcag: str, detail: str) -> dict:
    """A Review-Recommended finding (ADR 0023): advisory, evidence-carrying, and
    NON-blocking. Severity "REVIEW" has a zero penalty weight in the rubric, so it
    never lowers the score or blocks certification — it flags a concrete risk a human
    must adjudicate, never claims a pass, and offers no ACP fix (ADR 0016)."""
    return {"ruleId": rule_id, "wcag": wcag, "severity": "REVIEW", "advisory": True, "detail": detail}


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


# Floating text that a screen reader reads at its anchor, not its visual position (1.3.2).
_TXBX_CONTENT = re.compile(r"<w:txbxContent>(.*?)</w:txbxContent>", re.S)   # DrawingML / VML text box body
_FRAMEPR = re.compile(r"<w:framePr\b")                                       # positioned (floating) text frame

# xlsx structure labels + hyperlinks (2.4.4 / 2.4.6).
_XLSX_HL = re.compile(r"<hyperlink\b[^>]*>")
_HL_DISPLAY = re.compile(r'display="([^"]*)"')
_WB_SHEET = re.compile(r'<sheet\b[^>]*\bname="([^"]*)"')
_TBL_COL = re.compile(r'<tableColumn\b[^>]*\bname="([^"]*)"')
_DEFAULT_SHEET = re.compile(r"^Sheet\d+$")
_DEFAULT_COL = re.compile(r"^Column\d+$")

_VAGUE_LINK_TEXT = frozenset({
    "click here", "here", "click", "read more", "more", "learn more", "this", "this link",
    "link", "go", "details", "view", "download", "open", "see more", "more info", "info",
    "continue", "read",
})


def _is_vague_link_text(text: str) -> bool:
    """Link text that fails 2.4.4 in isolation: empty, a generic filler phrase, or a raw URL
    used as its own label."""
    t = (text or "").strip().lower()
    if not t or t in _VAGUE_LINK_TEXT:
        return True
    return bool(re.match(r"^(https?://|www\.)", t))


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
                    f = _finding("DOCX_HEADING_SKIP", "2.4.6 Headings and Labels", "MODERATE")
                    # Carry the actual levels so the review card can show the before/after outline
                    # (H{prev} → H{level}, should be H{prev} → H{prev+1}) — real, not illustrative.
                    f["detail"] = f"Heading level jumps from H{prev_level} to H{level} (should step to H{prev_level + 1})"
                    findings.append(f)
                    break
                prev_level = level

            # 1.3.1 — a paragraph visually styled as a heading (large/bold) but left in a
            # body style, so it isn't in the heading outline AT navigates by. One per doc.
            for p in _PARA.findall(doc):
                text = "".join(_WT.findall(p)).strip()
                szs = [int(s) for s in _W_SZ.findall(p)]
                if looks_like_pseudo_heading(
                        text, bold=bool(_W_BOLD.search(p)),
                        max_half_pt=max(szs) if szs else 0,
                        styled_heading=bool(_HEADING_ANY.search(p))):
                    findings.append(_finding("DOCX_PSEUDO_HEADING", "1.3.1 Info and Relationships", "MODERATE"))
                    break

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

            # 1.3.2 — floating text (DrawingML / VML text boxes, positioned frames) is read by
            # assistive tech at its anchor point, which need not match the visual order. Fires
            # only when the document actually contains text-bearing floating objects (conservative,
            # so an ordinary linear document never trips it).
            floating = sum(
                1 for inner in _TXBX_CONTENT.findall(doc) if "".join(_WT.findall(inner)).strip()
            ) + len(_FRAMEPR.findall(doc))
            if floating:
                f = _finding("DOCX_READING_ORDER_RISK", "1.3.2 Meaningful Sequence", "MODERATE")
                f["detail"] = (f"{floating} floating text box(es)/frame(s) — a screen reader may read "
                               "them out of the visual reading order")
                findings.append(f)
    except Exception:
        pass
    return findings


def xlsx_structure_checks(path: Path) -> list[dict]:
    """2.4.4 Link Purpose (In Context) — cell hyperlinks whose display text is vague, empty or a
    raw URL. 2.4.6 Headings and Labels — uninformative structure labels (multiple default 'SheetN'
    tabs, or default 'ColumnN' table headers). Detection only; both route to human remediation."""
    findings: list[dict] = []
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            # 2.4.4 — judge only links that carry an explicit display text; a link with no display
            # attribute takes its label from the cell value (not resolved here), so skipping it
            # avoids false positives.
            vague = 0
            for n in names:
                if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n):
                    xml = _read(zf, n) or ""
                    for tag in _XLSX_HL.findall(xml):
                        m = _HL_DISPLAY.search(tag)
                        if m and _is_vague_link_text(m.group(1)):
                            vague += 1
            if vague:
                f = _finding("XLSX_LINK_PURPOSE_VAGUE", "2.4.4 Link Purpose (In Context)", "MODERATE")
                f["detail"] = (f"{vague} hyperlink(s) with unclear text (e.g. “click here” or a raw URL) — "
                               "a screen-reader user cannot tell where the link goes")
                findings.append(f)

            # 2.4.6 — uninformative labels. A lone default 'Sheet1' is normal, so require either
            # several default sheet tabs or a default table-column header before flagging.
            wb = _read(zf, "xl/workbook.xml") or ""
            default_sheets = [nm for nm in _WB_SHEET.findall(wb) if _DEFAULT_SHEET.match(nm.strip())]
            default_cols: list[str] = []
            for n in names:
                if re.fullmatch(r"xl/tables/table\d+\.xml", n):
                    default_cols += [c for c in _TBL_COL.findall(_read(zf, n) or "")
                                     if _DEFAULT_COL.match(c.strip())]
            if len(default_sheets) >= 2 or default_cols:
                f = _finding("XLSX_DEFAULT_LABELS", "2.4.6 Headings and Labels", "MODERATE")
                bits = []
                if len(default_sheets) >= 2:
                    bits.append(f"{len(default_sheets)} default sheet tabs ({', '.join(default_sheets[:3])})")
                if default_cols:
                    bits.append(f"{len(default_cols)} default table column label(s) (e.g. “{default_cols[0]}”)")
                f["detail"] = "Uninformative labels: " + "; ".join(bits)
                findings.append(f)
    except Exception:
        return []
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
_WPS_SPPR = re.compile(r"<wps:spPr\b.*?</wps:spPr>", re.S)   # docx DrawingML shape props
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


def min_contrast_recolor(fg_hex: str, bg_hex: str, target: float = 4.5) -> str:
    """The smallest perceptual change to `fg_hex` that reaches `target` contrast on `bg_hex`.

    A contrast fix that flattens every failing colour to pure black or white is compliant but
    destroys the design — a brand's muted-blue heading should not become #000000. Instead this
    keeps the text colour's HUE and SATURATION and moves only its LIGHTNESS, toward whichever
    extreme the background allows (darker on a light bg, lighter on a dark one), stopping at the
    first lightness that clears the ratio. So the recoloured text is the SAME colour, only as dark
    (or light) as it must be — the brand survives the fix.

    Returns an upper-case #RRGGBB (no '#'). Idempotent: a colour that already passes is returned
    unchanged. The extreme (black/white) is the guaranteed fallback — for any background, one of
    the two always clears 4.5:1 — so this never fails to reach `target`. The returned hex is what
    gets written, and it is what the ratio is measured against, so the fix is real post-rounding.
    """
    import colorsys
    fg = fg_hex.lstrip("#").upper()
    bg = bg_hex.lstrip("#")
    if len(fg) != 6 or len(bg) != 6:
        return fg
    if _contrast_ratio(bg, fg) >= target:
        return fg
    r, g, b = (int(fg[i:i + 2], 16) / 255 for i in (0, 2, 4))
    h, l0, s = colorsys.rgb_to_hls(r, g, b)
    # Darken toward black when the background favours it (dark text on light paper); else lighten.
    darken = _contrast_ratio(bg, "000000") >= _contrast_ratio(bg, "FFFFFF")
    best = "000000" if darken else "FFFFFF"           # guaranteed to clear target
    lo, hi = (0.0, l0) if darken else (l0, 1.0)        # search lightness between origin and extreme
    for _ in range(24):
        mid = (lo + hi) / 2
        rr, gg, bb = colorsys.hls_to_rgb(h, mid, s)
        cand = f"{round(rr * 255):02X}{round(gg * 255):02X}{round(bb * 255):02X}"
        if _contrast_ratio(bg, cand) >= target:
            best = cand
            # Passing — preserve more of the original by nudging lightness back toward it.
            if darken:
                lo = mid
            else:
                hi = mid
        else:
            if darken:
                hi = mid
            else:
                lo = mid
    return best


def pptx_contrast_checks(path: Path) -> list[dict]:
    """1.4.3 / 1.4.6 Contrast for pptx — explicit run colour on an explicit shape
    solid fill only (see the narrow-scope note above).

    Thresholds are the WCAG *large-text* ratios (AA 3:1, AAA 4.5:1). Font size
    isn't reliably knowable per run (it's often inherited from the placeholder),
    so flagging only below the large-text bar guarantees every finding is a real
    failure at *any* size — a genuine result over an over-eager one."""
    worst = None          # (ratio, text_hex, bg_hex) of the lowest-contrast run seen
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
                        if ratio < 4.5 and (worst is None or ratio < worst[0]):
                            worst = (ratio, col_m.group(1), fill_m.group(1))
    except Exception:
        return []
    if worst is None:
        return []
    ratio, text_hex, bg_hex = worst
    detail = f"Text #{text_hex} on #{bg_hex} is {ratio:.1f}:1 (needs 4.5:1)"
    findings: list[dict] = []
    if ratio < 3.0:
        f = _finding("PPTX_LOW_CONTRAST_AA", "1.4.3 Contrast (Minimum)", "SERIOUS")
        f["detail"] = detail
        findings.append(f)
    f = _finding("PPTX_LOW_CONTRAST_AAA", "1.4.6 Contrast (Enhanced)", "MODERATE")
    f["detail"] = detail
    findings.append(f)
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


# ── ADR 0025 Tier A — PDF structural measurements from pdfplumber char metrics (no render) ──
_MAX_PAGES_SPACING = 20        # cap the pages we measure line spacing on
_MIN_LINES_FOR_SPACING = 4     # need a few lines before judging line pitch
_TIGHT_LINE_PITCH = 1.15       # pitch below this × font size = cramped (single-spacing is ~1.2×)


def pdf_text_spacing_checks(path: Path) -> list[dict]:
    """1.4.12 Text Spacing (Review) for PDF (ADR 0025 Tier A). A flattened PDF can't honour a
    reader's line-spacing override, so genuinely TIGHT line pitch is a fixed legibility risk.
    Measures the line pitch (baseline-to-baseline) as a multiple of the font size from pdfplumber
    char positions and flags the tightest page below _TIGHT_LINE_PITCH — a real measured value, or
    nothing (ADR 0016): abstains when there aren't enough lines to judge. Advisory, never a pass.
    Never raises."""
    import statistics
    worst = None      # (ratio, pitch_pt, font_pt)
    try:
        import pdfplumber
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages[:_MAX_PAGES_SPACING]:
                tops: dict[int, list[float]] = {}
                for ch in page.chars[:_MAX_CHARS_PER_PAGE]:
                    try:
                        top = round(float(ch["top"]))
                        size = float(ch.get("size") or 0)
                    except (TypeError, ValueError, KeyError):
                        continue
                    if size > 0:
                        tops.setdefault(top, []).append(size)
                lines = sorted(tops)
                if len(lines) < _MIN_LINES_FOR_SPACING:
                    continue
                font = statistics.median(s for sizes in tops.values() for s in sizes)
                if font <= 0:
                    continue
                # consecutive baseline gaps that look like line pitch — exclude paragraph breaks and
                # column jumps (anything beyond 3× the font is a gap between blocks, not a line).
                gaps = [b - a for a, b in zip(lines, lines[1:]) if 0 < (b - a) <= 3 * font]
                if len(gaps) < _MIN_LINES_FOR_SPACING - 1:
                    continue
                ratio = statistics.median(gaps) / font
                if ratio < _TIGHT_LINE_PITCH and (worst is None or ratio < worst[0]):
                    worst = (ratio, statistics.median(gaps), font)
    except Exception:
        return []
    if worst is None:
        return []
    ratio = worst[0]
    return [_review_finding(
        "PDF_TIGHT_LINE_SPACING", "1.4.12 Text Spacing",
        f"text lines are set at {ratio:.2f}× the font size — tight, and a flattened PDF can't honour "
        "a reader's request for looser (1.5×) line spacing; verify the text stays legible")]


def _pdf_is_chromatic(color) -> bool:
    """True if a pdfplumber colour carries a HUE (not gray/black) — i.e. colour used to convey
    meaning. A single float is grayscale; RGB is chromatic when its channels spread; CMYK is
    chromatic when any of C/M/Y is present (K is just darkness)."""
    try:
        if color is None or isinstance(color, (int, float)):
            return False
        vals = [float(v) for v in color]
        if len(vals) == 3:
            return (max(vals) - min(vals)) > 0.15
        if len(vals) == 4:
            return max(vals[:3]) > 0.15
    except (TypeError, ValueError):
        return False
    return False


def _pdf_link_has_underline(page, link: dict) -> bool:
    """A drawn horizontal line / thin rect spanning most of the link's width near its bottom edge —
    a second (non-colour) cue that the run is a link."""
    lx0, lx1, lbottom = link["x0"], link["x1"], link["bottom"]
    lw = lx1 - lx0
    if lw <= 0:
        return False

    def spans(x0, x1) -> bool:
        return (min(x1, lx1) - max(x0, lx0)) >= 0.6 * lw

    for ln in getattr(page, "lines", []) or []:
        if abs(ln["top"] - ln["bottom"]) <= 1.5 and abs(ln["bottom"] - lbottom) <= 4 and spans(ln["x0"], ln["x1"]):
            return True
    for r in getattr(page, "rects", []) or []:
        if (r.get("height") or 99) <= 2.5 and abs(r["bottom"] - lbottom) <= 4 and spans(r["x0"], r["x1"]):
            return True
    return False


def pdf_use_of_color_checks(path: Path) -> list[dict]:
    """1.4.1 Use of Color (Review) for PDF (ADR 0025 Tier A) — a hyperlink distinguished ONLY by a
    chromatic text colour, with no underline, relies on colour alone to signal it is a link.
    Conservative: needs a real chromatic colour in the link's text AND no drawn underline; anything
    it can't read (no annotation, no chars, ambiguous) is skipped (ADR 0016). Advisory, never a
    pass. Never raises."""
    colour_only = 0
    try:
        import pdfplumber
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages[:_MAX_PAGES_SPACING]:
                links = getattr(page, "hyperlinks", []) or []
                if not links:
                    continue
                chars = page.chars
                for link in links:
                    try:
                        lx0, lx1, ltop, lbot = link["x0"], link["x1"], link["top"], link["bottom"]
                    except (KeyError, TypeError):
                        continue
                    inside = [c for c in chars
                              if c["x0"] >= lx0 - 1 and c["x1"] <= lx1 + 1
                              and c["top"] >= ltop - 1 and c["bottom"] <= lbot + 1]
                    if not inside:
                        continue
                    if not any(_pdf_is_chromatic(c.get("non_stroking_color")) for c in inside):
                        continue                     # not colour-distinguished → not a 1.4.1 signal
                    if _pdf_link_has_underline(page, link):
                        continue                     # has a second, non-colour cue → fine
                    colour_only += 1
                if colour_only:
                    break                            # one finding per file is enough
    except Exception:
        return []
    if not colour_only:
        return []
    return [_review_finding(
        "PDF_COLOUR_ONLY_LINK", "1.4.1 Use of Color",
        "a link is set apart only by its text colour, with no underline — colour alone can't be the "
        "only way to tell a link from surrounding text; verify it's distinguishable without colour")]


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


_PDF_HEADING_TAGS = {"/H", "/H1", "/H2", "/H3", "/H4", "/H5", "/H6", "/Title"}


def pdf_headings_labels_check(path: Path) -> list[dict]:
    """2.4.6 Headings and Labels — a TAGGED PDF (has a structure tree) that contains no heading
    structure elements at all: assistive tech then has no headings to navigate by. Untagged PDFs
    are handled by 1.3.1/2.4.1, so this fires only when tagging exists but omits headings, and
    only past a page floor (a one-pager legitimately needs none)."""
    try:
        import pikepdf
        with pikepdf.open(str(path)) as pdf:
            if len(pdf.pages) < _MIN_PAGES_FOR_OUTLINE:
                return []
            st = pdf.Root.get("/StructTreeRoot")
            if st is None:
                return []          # untagged → not this check's concern
            stack = [st.get("/K")]
            budget = 5000
            while stack and budget > 0:
                budget -= 1
                node = stack.pop()
                if node is None:
                    continue
                try:
                    if isinstance(node, pikepdf.Array):
                        stack.extend(list(node))
                        continue
                    s = node.get("/S")
                    if s is not None and str(s) in _PDF_HEADING_TAGS:
                        return []   # a heading exists → pass
                    k = node.get("/K")
                    if k is not None:
                        stack.append(k)
                except Exception:
                    continue
    except Exception:
        return []
    return [_finding("PDF_NO_HEADINGS", "2.4.6 Headings and Labels", "MODERATE")]


def pdf_link_purpose_check(path: Path) -> list[dict]:
    """2.4.4 Link Purpose (In Context) — a link annotation whose visible text is the raw URL: the
    URL string of a /Link's /URI action appears verbatim in the page text. A bare URL is not a
    meaningful link label. Conservative — the URL must literally appear as text, so a link with
    descriptive text is never flagged."""
    try:
        import pikepdf
        uris: list[str] = []
        with pikepdf.open(str(path)) as pdf:
            for page in pdf.pages:
                for annot in (page.get("/Annots") or []):
                    try:
                        if str(annot.get("/Subtype")) != "/Link":
                            continue
                        action = annot.get("/A")
                        uri = action.get("/URI") if action is not None else None
                        if uri:
                            uris.append(str(uri))
                    except Exception:
                        continue
        if not uris:
            return []
        wanted = {u for u in uris if u} | {re.sub(r"^https?://", "", u) for u in uris if u}
        import pdfplumber
        text = ""
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages[:20]:
                text += (page.extract_text() or "") + " "
                if len(text) > 20000:
                    break
        if any(u and u in text for u in wanted):
            return [_finding("PDF_LINK_RAW_URL", "2.4.4 Link Purpose (In Context)", "MODERATE")]
    except Exception:
        return []
    return []


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
            worst = None      # (true_ratio, font6, fill6) of the lowest-contrast flagged cell
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
                    # Track the worst pairing by the TRUE WCAG ratio (for the review card's colour
                    # swatch) — detection above is unchanged; this only records the colours+ratio.
                    if diff < 0.5:
                        f6, b6 = colors[0][-6:], colors[1][-6:]
                        r = _contrast_ratio(f6, b6)
                        if worst is None or r < worst[0]:
                            worst = (r, f6, b6)
                if seen_aa and seen_aaa:
                    break
    except Exception:
        return []
    # Attach the fg/bg + measured ratio in the same shape pptx uses, so the card renders the swatch.
    # Only when the true ratio agrees the cell fails the finding's bar — never a contradictory detail.
    def _detail(needs: float) -> str | None:
        if worst and worst[0] < needs:
            return f"Text #{worst[1].upper()} on #{worst[2].upper()} is {worst[0]:.1f}:1 (needs {needs:g}:1)"
        return None
    if seen_aa:
        f = _finding("XLSX_LOW_CONTRAST_AA", "1.4.3 Contrast (Minimum)", "SERIOUS")
        d = _detail(4.5)
        if d:
            f["detail"] = d
        findings.append(f)
    if seen_aaa:
        f = _finding("XLSX_LOW_CONTRAST_AAA", "1.4.6 Contrast (Enhanced)", "MODERATE")
        d = _detail(7.0)
        if d:
            f["detail"] = d
        findings.append(f)
    return findings


# ── 4.1.2 Name, Role, Value — PDF AcroForm fields lacking an accessible name ─────
# A terminal interactive form field (/FT present: /Tx text, /Btn button/checkbox/radio,
# /Ch choice/combo, /Sig signature) exposes its accessible name to assistive tech via /TU
# (the "tooltip"). A field with no /TU is announced only by its cryptic partial name /T
# (or nothing), so a screen-reader user cannot tell what to enter. One finding per unnamed
# terminal field. Self-gating: no AcroForm, no pikepdf, or a malformed tree yields [] — a
# structural check must never fail a scan. The remediator (`_fix_pdf_form_fields`) clears
# each by writing /TU, and this same walk re-run on the fixed file verifies it.
def _pdf_terminal_fields(node, out, seen):
    """Recursively collect terminal AcroForm fields (those with /FT), following /Kids."""
    try:
        import pikepdf
    except Exception:
        return
    if not isinstance(node, pikepdf.Dictionary):
        return
    oid = id(node)
    if oid in seen:
        return
    seen.add(oid)
    kids = node.get("/Kids")
    if "/FT" in node and not (isinstance(kids, pikepdf.Array) and len(kids)
                              and any("/FT" in k for k in kids if isinstance(k, pikepdf.Dictionary))):
        out.append(node)          # a terminal field (its kids, if any, are widgets, not fields)
    if isinstance(kids, pikepdf.Array):
        for k in kids:
            _pdf_terminal_fields(k, out, seen)


def _pdf_field_unnamed(field) -> bool:
    try:
        tu = field.get("/TU")
        return tu is None or not str(tu).strip()
    except Exception:
        return False


def pdf_form_field_checks(path: Path) -> list[dict]:
    """One 4.1.2 finding per interactive form field with no accessible name (/TU)."""
    try:
        import pikepdf
    except Exception:
        return []
    findings: list[dict] = []
    try:
        with pikepdf.open(str(path)) as pdf:
            root = pdf.Root
            if "/AcroForm" not in root or "/Fields" not in root["/AcroForm"]:
                return []
            fields: list = []
            for f in root["/AcroForm"]["/Fields"]:
                _pdf_terminal_fields(f, fields, set())
            for fld in fields:
                if _pdf_field_unnamed(fld):
                    name = ""
                    try:
                        name = str(fld.get("/T", "")).strip()
                    except Exception:
                        name = ""
                    findings.append({
                        "ruleId": "PDF_FORM_NO_ACCESSIBLE_NAME",
                        "wcag": "4.1.2 Name, Role, Value",
                        "severity": "CRITICAL",
                        "detail": (f"form field “{name}” has no accessible name (/TU)" if name
                                   else "an interactive form field has no accessible name (/TU)"),
                    })
    except Exception:
        return []
    return findings


def checks_for(path: Path, ext: str) -> list[dict]:
    """Dispatch by extension; returns [] for formats with no structural check yet."""
    ext = ext.lower()
    if ext == ".docx":
        return (docx_checks(path) + office_control_review_checks(path, ext)
                + office_color_only_checks(path, ext)
                + office_reflow_checks(path, ext) + office_text_spacing_checks(path, ext)
                + docx_nontext_contrast_checks(path))
    if ext == ".pptx":
        return (pptx_checks(path) + pptx_contrast_checks(path) + pptx_audio_autoplay_checks(path)
                + office_control_review_checks(path, ext)
                + pptx_focus_order_checks(path) + pptx_nontext_contrast_checks(path)
                + office_reflow_checks(path, ext) + office_text_spacing_checks(path, ext)
                + pptx_resize_text_checks(path) + pptx_complex_bg_contrast_checks(path))
    if ext == ".pdf":
        return (pdf_contrast_checks(path) + pdf_bypass_blocks_check(path) + pdf_form_field_checks(path)
                + pdf_headings_labels_check(path) + pdf_link_purpose_check(path)
                + pdf_text_spacing_checks(path) + pdf_use_of_color_checks(path))
    if ext == ".xlsx":
        return (xlsx_contrast_checks(path) + xlsx_structure_checks(path)
                + office_control_review_checks(path, ext) + office_color_only_checks(path, ext))
    return []


# ── 1.4.2 Audio Control — pptx embedded audio set to start automatically ────────
# WCAG 1.4.2 (A): audio that plays automatically for more than 3 seconds needs a
# pause/stop control. A deck can't offer one, so auto-starting embedded audio is the
# finding itself. Deterministic markers in the slide XML: an <a:audioFile> (or wav
# embed) whose timing tree starts it with a zero-delay condition rather than an
# onClick event. Click-started audio is fine and never flagged; duration isn't
# stored in OOXML, so the finding routes to a human (detect-and-route, ADR 0002) —
# never auto-passed, never auto-fixed.
_PPTX_AUDIO = re.compile(r"<a:audioFile\b|<a:wavAudioFile\b")
_AUTOPLAY_COND = re.compile(r'<p:cond[^>]*\bdelay="0"')
_ONCLICK_COND = re.compile(r'<p:cond[^>]*\bevt="onClick"')


def pptx_audio_autoplay_checks(path: Path) -> list[dict]:
    """One 1.4.2 finding per slide whose embedded audio auto-starts. Never raises —
    structural checks must not fail a scan."""
    findings: list[dict] = []
    try:
        with zipfile.ZipFile(path) as zf:
            for slide_name in sorted(
                    n for n in zf.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)):
                xml = _read(zf, slide_name)
                if not xml or not _PPTX_AUDIO.search(xml):
                    continue
                timing = xml.split("<p:timing>", 1)[1] if "<p:timing>" in xml else ""
                # Auto-start = a zero-delay trigger in the timing tree with no onClick
                # gate. No timing tree at all → the media has no start trigger; PowerPoint
                # treats that as click-to-play, so it is not flagged.
                if timing and _AUTOPLAY_COND.search(timing) and not _ONCLICK_COND.search(timing):
                    n = re.search(r"slide(\d+)\.xml", slide_name)
                    findings.append({**_finding(
                        "PPTX_AUDIO_AUTOPLAY", "1.4.2 Audio Control", "SERIOUS"),
                        "detail": f"slide {n.group(1) if n else '?'} embeds audio set to start "
                                  "automatically — audio longer than 3 seconds needs a "
                                  "pause/stop control, which a slide deck cannot provide"})
    except Exception:
        return findings
    return findings


# ── 2.1.2 No Keyboard Trap / 4.1.2 Name, Role, Value — interactive controls (Review) ──
# ADR 0023, Phase 1a. A *static* Office document has no interactive controls, so both
# criteria are genuinely N/A. But a document CAN embed interactive controls — ActiveX,
# OLE objects, VBA-driven UserForms, content-control form fields, legacy Word form
# fields, or worksheet form controls — any of which can trap keyboard focus (2.1.2) or
# ship without an accessible name/role (4.1.2). We can't statically prove a trap, nor
# verify every control exposes a name, so this is a REVIEW-RECOMMENDED signal: surface
# the concrete controls we found and route a human to judge conformance. No controls
# found → the criteria stay genuinely N/A for that file (never a fabricated pass).
_AX_PART = re.compile(r"/activeX/activeX\d+\.xml$", re.I)          # ActiveX control part
_OLE_PART = re.compile(r"/embeddings/oleObject\d+\.\w+$", re.I)     # embedded OLE object
_XL_CTRL_PART = re.compile(r"/ctrlProps/ctrlProp\d+\.xml$", re.I)   # xlsx form control
_VBA_PART = re.compile(r"vbaProject\.bin$", re.I)                   # VBA macro project
_FFDATA = re.compile(r"<w:ffData\b")                               # docx legacy form field


def office_interactive_controls(path: Path, ext: str) -> list[dict]:
    """Evidence of interactive controls embedded in an OOXML document.

    Returns a list of ``{"type": str, "count": int}`` entries (one per control kind
    actually found), or ``[]`` when the document is static. Reads the zip's part list
    plus — for docx — ``word/document.xml`` for content-control form fields and legacy
    form fields. Never raises: a control scan must never fail a document scan."""
    ext = (ext or "").lower()
    if ext not in (".docx", ".pptx", ".xlsx"):
        return []
    counts: dict[str, int] = {}
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            ax = sum(1 for n in names if _AX_PART.search(n))
            if ax:
                counts["ActiveX control"] = ax
            ole = sum(1 for n in names if _OLE_PART.search(n))
            if ole:
                counts["embedded OLE object"] = ole
            vba = sum(1 for n in names if _VBA_PART.search(n))
            if vba:
                counts["VBA macro project"] = vba
            if ext == ".xlsx":
                ctrl = sum(1 for n in names if _XL_CTRL_PART.search(n))
                if ctrl:
                    counts["form control"] = ctrl
            if ext == ".docx":
                doc = _read(zf, "word/document.xml") or ""
                # Only genuine INPUT content controls (checkbox/date/dropdown/combo/
                # picture) — the same input-type gate the 3.3.2 detector uses, so
                # non-interactive template placeholders (w:text/w:richText) don't count.
                cc = 0
                for sdt_inner in _SDT.findall(doc):
                    pr_m = _SDT_PR.search(sdt_inner)
                    if pr_m and _SDT_INPUT_TYPE.search(pr_m.group(1)):
                        cc += 1
                if cc:
                    counts["interactive content control"] = cc
                ff = len(_FFDATA.findall(doc))
                if ff:
                    counts["legacy form field"] = ff
    except Exception:
        return []
    return [{"type": k, "count": v} for k, v in counts.items()]


def _controls_phrase(controls: list[dict]) -> str:
    """Human phrase for the evidence list, e.g. '2 ActiveX controls, 1 VBA macro project'."""
    parts = []
    for c in controls:
        n, t = c["count"], c["type"]
        parts.append(f"{n} {t}{'s' if n != 1 else ''}")
    return ", ".join(parts)


def office_control_review_checks(path: Path, ext: str) -> list[dict]:
    """REVIEW findings for 2.1.2 + 4.1.2 when a document embeds interactive controls
    (ADR 0023). Advisory only — carries the concrete control evidence, never a pass,
    never a fix. Emits nothing (→ the criteria stay N/A) for a static document."""
    controls = office_interactive_controls(path, ext)
    if not controls:
        return []
    phrase = _controls_phrase(controls)
    return [
        _review_finding(
            "OFFICE_INTERACTIVE_CONTROL_KEYBOARD", "2.1.2 No Keyboard Trap",
            f"document embeds {phrase} — verify keyboard focus can move away from every "
            "control (no keyboard trap); ACP can't confirm this statically"),
        _review_finding(
            "OFFICE_INTERACTIVE_CONTROL_NAME_ROLE", "4.1.2 Name, Role, Value",
            f"document embeds {phrase} — verify each control exposes an accessible name "
            "and role to assistive technology; ACP can't confirm this statically"),
    ]


# ── 1.4.1 Use of Color (Review, ADR 0023 Phase 1b) ─────────────────────────────
# Colour used as the ONLY way to convey information fails 1.4.1. Two high-precision
# structural signals ACP can surface for a human to confirm:
#   • xlsx conditional formatting that shades cells by value (colorScale, or a rule with a
#     differential-format fill) — status may be encoded by colour alone.
#   • docx hyperlinks whose underline is explicitly removed — a link distinguished from body
#     text by colour only. Both are advisory: whether a non-colour cue also exists is a human call.
_CF_RULE = re.compile(r"<cfRule\b[^>]*>")
_W_U_NONE = re.compile(r'<w:u\b[^>]*w:val="none"')


def office_color_only_checks(path: Path, ext: str) -> list[dict]:
    """REVIEW findings for 1.4.1 when colour appears to carry meaning on its own. Never raises."""
    ext = (ext or "").lower()
    findings: list[dict] = []
    try:
        with zipfile.ZipFile(path) as zf:
            if ext == ".xlsx":
                cf = 0
                for n in zf.namelist():
                    if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n):
                        for tag in _CF_RULE.findall(_read(zf, n) or ""):
                            # colorScale = pure colour gradient; a dxfId rule applies a colour
                            # fill. iconSet pairs colour WITH an icon, so it is NOT colour-only.
                            if 'type="colorScale"' in tag or ('dxfId="' in tag and "iconSet" not in tag):
                                cf += 1
                if cf:
                    findings.append(_review_finding(
                        "XLSX_COLOR_ONLY_STATUS", "1.4.1 Use of Color",
                        f"{cf} conditional-formatting rule(s) shade cells by value — verify the "
                        "status they signal is ALSO conveyed without colour (a label or icon), so "
                        "it isn't lost for colour-blind or screen-reader users"))
            if ext == ".docx":
                doc = _read(zf, "word/document.xml") or ""
                colour_only = sum(1 for _rid, inner in _HYPERLINK.findall(doc) if _W_U_NONE.search(inner))
                if colour_only:
                    findings.append(_review_finding(
                        "DOCX_COLOR_ONLY_LINK", "1.4.1 Use of Color",
                        f"{colour_only} hyperlink(s) have their underline removed — a link set apart "
                        "from body text by colour alone fails for colour-blind users; verify each "
                        "link is identifiable without relying on colour"))
    except Exception:
        return findings
    return findings


# ── 2.4.3 Focus Order (Review, ADR 0023 Phase 1b) ──────────────────────────────
# A slide's shapes are read and tabbed in document (spTree) order. When a body/content
# placeholder precedes the TITLE placeholder in that order, assistive tech reaches the slide's
# content before its heading — a focus/reading-order anomaly. Advisory: a human confirms the
# intended order (some layouts are legitimately title-last).
def pptx_focus_order_checks(path: Path) -> list[dict]:
    """One REVIEW finding for 2.4.3 per slide whose title placeholder is not the first
    placeholder in document order. Never raises."""
    findings: list[dict] = []
    try:
        with zipfile.ZipFile(path) as zf:
            for slide_name in sorted(n for n in zf.namelist()
                                     if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)):
                xml = _read(zf, slide_name)
                if not xml:
                    continue
                ph_shapes = [sp for sp in _PPTX_SP.findall(xml) if "<p:ph" in sp]
                if len(ph_shapes) < 2:
                    continue
                title_pos = next((k for k, sp in enumerate(ph_shapes) if _PPTX_TITLE_PH.search(sp)), None)
                if title_pos is not None and title_pos > 0:
                    n = re.search(r"slide(\d+)\.xml", slide_name)
                    findings.append(_review_finding(
                        "PPTX_FOCUS_ORDER", "2.4.3 Focus Order",
                        f"on slide {n.group(1) if n else '?'} {title_pos} content placeholder(s) come "
                        "before the title in reading/tab order — verify assistive tech reaches the "
                        "slide's heading before its body content"))
    except Exception:
        return findings
    return findings


# ── 1.4.11 Non-text Contrast (Review, ADR 0023 Phase 1b) ───────────────────────
# A meaningful shape needs ≥3:1 contrast between its boundary and adjacent colour. A shape that
# has an explicit solid outline whose colour is near-identical to its own fill has an effectively
# invisible boundary — a 1.4.11 risk IF the shape conveys meaning (a human confirms it isn't
# purely decorative). Border-vs-fill is fully determined by explicit colours, so no fragile
# slide-background assumption is needed; both are measured with the same WCAG math as 1.4.3.
def pptx_nontext_contrast_checks(path: Path) -> list[dict]:
    """One REVIEW finding for 1.4.11 for the lowest-contrast solid outline-on-fill shape (<3:1).
    Never raises."""
    worst = None      # (ratio, border_hex, fill_hex)
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
                    sppr_xml = sppr_m.group(0)
                    ln_m = _A_LN_BLOCK.search(sppr_xml)
                    if not ln_m:
                        continue
                    border_m = _SOLID_SRGB.search(ln_m.group(0))          # the outline colour
                    fill_m = _SOLID_SRGB.search(_A_LN_BLOCK.sub("", sppr_xml))  # the fill (border stripped)
                    if not border_m or not fill_m:
                        continue
                    ratio = _contrast_ratio(border_m.group(1), fill_m.group(1))
                    if ratio < 3.0 and (worst is None or ratio < worst[0]):
                        worst = (ratio, border_m.group(1), fill_m.group(1))
    except Exception:
        return []
    if worst is None:
        return []
    ratio, border_hex, fill_hex = worst
    return [_review_finding(
        "PPTX_NONTEXT_LOW_CONTRAST", "1.4.11 Non-text Contrast",
        f"a shape outline #{border_hex} on its #{fill_hex} fill is {ratio:.1f}:1 (needs 3:1) — if the "
        "shape conveys meaning, its boundary may be too faint to see; verify it isn't decorative")]


def docx_nontext_contrast_checks(path: Path) -> list[dict]:
    """1.4.11 Non-text Contrast (Review) for docx — the lowest-contrast solid outline-on-fill
    DrawingML shape (<3:1). Word's shapes carry the SAME `<a:ln>` outline + `<a:solidFill>` under
    `<wps:spPr>` as pptx, so this mirrors `pptx_nontext_contrast_checks` on word/document.xml.
    Never raises."""
    worst = None      # (ratio, border_hex, fill_hex)
    try:
        with zipfile.ZipFile(path) as zf:
            xml = _read(zf, "word/document.xml") or ""
            for sppr in _WPS_SPPR.findall(xml):
                ln_m = _A_LN_BLOCK.search(sppr)
                if not ln_m:
                    continue
                border_m = _SOLID_SRGB.search(ln_m.group(0))              # the outline colour
                fill_m = _SOLID_SRGB.search(_A_LN_BLOCK.sub("", sppr))    # the fill (border stripped)
                if not border_m or not fill_m:
                    continue
                ratio = _contrast_ratio(border_m.group(1), fill_m.group(1))
                if ratio < 3.0 and (worst is None or ratio < worst[0]):
                    worst = (ratio, border_m.group(1), fill_m.group(1))
    except Exception:
        return []
    if worst is None:
        return []
    ratio, border_hex, fill_hex = worst
    return [_review_finding(
        "DOCX_NONTEXT_LOW_CONTRAST", "1.4.11 Non-text Contrast",
        f"a shape outline #{border_hex} on its #{fill_hex} fill is {ratio:.1f}:1 (needs 3:1) — if the "
        "shape conveys meaning, its boundary may be too faint to see; verify it isn't decorative")]


# ── ADR 0024 Tier A — render-gated criteria, structural proxies (no rendering) ──
# Advisory 🟡 REVIEW signals for the four render-dependent criteria (1.4.4 Resize Text, 1.4.10
# Reflow, 1.4.12 Text Spacing, 1.4.3 hybrid). Each is a cheap, deterministic OOXML fact that a
# criterion is at RENDER-RISK — surfaced for a human to confirm against the rendered page, never
# a certified pass (ADR 0016). Tier B (ADR 0018 render) will later upgrade these with measured
# pixel evidence; these ship first, adding NO rendering to the scan path.
_WIDE_TABLE_COLS = 8                 # a table this wide likely can't reflow to a narrow viewport
_RESIZE_MIN_CHARS = 300              # a fixed-size (no-autofit) box holding this much text may clip at 200%
_MIN_EXACT_SPACING_PARAS = 3         # a few exact-line-height paragraphs before flagging text-spacing risk
_W_TBL = re.compile(r"<w:tbl>(.*?)</w:tbl>", re.S)
_W_GRIDCOL = re.compile(r"<w:gridCol\b")
_W_GRIDCOL_W = re.compile(r'<w:gridCol\b[^>]*\bw:w="(\d+)"')     # docx column width, twips
_A_TBL = re.compile(r"<a:tbl>(.*?)</a:tbl>", re.S)
_A_GRIDCOL = re.compile(r"<a:gridCol\b")
_A_GRIDCOL_W = re.compile(r'<a:gridCol\b[^>]*\bw="(\d+)"')       # pptx column width, EMU
_A_NOAUTOFIT = re.compile(r"<a:noAutofit\b")
_W_LINERULE_EXACT = re.compile(r'<w:spacing\b[^>]*w:lineRule="exact"')
_A_EXACT_LNSPC = re.compile(r"<a:lnSpc>\s*<a:spcPts\b")
# Per-paragraph parsing for the measured 1.4.12 line-height ratio (fixed line height ÷ font size).
_W_PARA = re.compile(r"<w:p\b[^>]*>.*?</w:p>", re.S)      # \b keeps w:p from matching w:pPr
_W_SPACING_TAG = re.compile(r"<w:spacing\b[^>]*?/?>")
_W_LINE_VAL = re.compile(r'\bw:line="(\d+)"')             # twentieths of a point
_W_SZ = re.compile(r'<w:sz\b\s+w:val="(\d+)"')            # half-points (\b excludes w:szCs)
_A_PARA = re.compile(r"<a:p\b[^>]*>.*?</a:p>", re.S)
_A_LNSPC_PTS = re.compile(r'<a:lnSpc>\s*<a:spcPts\b[^>]*\bval="(\d+)"')   # hundredths of a point
_A_RUN_SZ = re.compile(r'<a:(?:rPr|defRPr|endParaRPr)\b[^>]*\bsz="(\d+)"')  # hundredths of a point
_A_BLIPFILL = re.compile(r"<a:blipFill\b")
_A_GRADFILL = re.compile(r"<a:gradFill\b")
_CNVPR_NAME = re.compile(r'<p:cNvPr\b[^>]*\bname="([^"]*)"')
_CNVPR_ID = re.compile(r'<p:cNvPr\b[^>]*\bid="([^"]*)"')


def _widest_table_cols(xml: str, tbl_re, gridcol_re, gridcol_w_re) -> tuple[int, list[int]]:
    """(column count, [column widths]) of the widest (most-columns) table in this part; (0, [])
    if none. The widths list is empty when that table's gridCols don't declare widths."""
    best_cols, best_widths = 0, []
    for inner in tbl_re.findall(xml):
        cols = len(gridcol_re.findall(inner))
        if cols > best_cols:
            best_cols = cols
            best_widths = [int(w) for w in gridcol_w_re.findall(inner)]
    return best_cols, best_widths


def _narrowest_column_fraction(cols: int, widths: list[int]) -> float | None:
    """The narrowest column as a fraction of the total table width (ADR 0024 Tier B.3 / #185
    measured 1.4.10 evidence) — how squeezed the tightest column is, scale-invariant so it holds on
    any screen. Returns None when the widths are absent/incomplete (real measurement or nothing,
    ADR 0016 — never a guessed fraction)."""
    if not widths or len(widths) != cols:
        return None
    total = sum(widths)
    if total <= 0:
        return None
    return min(widths) / total


def office_reflow_checks(path: Path, ext: str) -> list[dict]:
    """1.4.10 Reflow (Review) — a table too wide to reflow to a narrow viewport without 2-D
    scrolling. Wide is a structural fact (grid-column count); whether it actually needs scrolling
    is a rendered/AT judgement, so it is advisory. Never raises."""
    ext = (ext or "").lower()
    findings: list[dict] = []
    try:
        with zipfile.ZipFile(path) as zf:
            cols, widths = 0, []
            if ext == ".docx":
                cols, widths = _widest_table_cols(
                    _read(zf, "word/document.xml") or "", _W_TBL, _W_GRIDCOL, _W_GRIDCOL_W)
            elif ext == ".pptx":
                for n in zf.namelist():
                    if re.fullmatch(r"ppt/slides/slide\d+\.xml", n):
                        c, w = _widest_table_cols(_read(zf, n) or "", _A_TBL, _A_GRIDCOL, _A_GRIDCOL_W)
                        if c > cols:
                            cols, widths = c, w
            if cols >= _WIDE_TABLE_COLS:
                detail = (f"a table is {cols} columns wide — verify it can be read at a narrow (320px) "
                          "width without two-dimensional scrolling; wide fixed tables often can't reflow")
                # #185 measured refinement: the tightest column's share of the table width, projected
                # to a 360px phone. A real number from the file's own gridCol widths (no render).
                frac = _narrowest_column_fraction(cols, widths)
                if frac is not None:
                    detail = (
                        f"a table is {cols} columns wide and its narrowest column is only "
                        f"{round(frac * 100)}% of the table (≈{round(frac * 360)}px when the table "
                        "is fit to a 360px-wide phone) — verify it stays readable without "
                        "two-dimensional scrolling")
                findings.append(_review_finding("OFFICE_WIDE_TABLE_REFLOW", "1.4.10 Reflow", detail))
    except Exception:
        return findings
    return findings


def _min_exact_line_height_ratio(xml: str, fmt: str) -> float | None:
    """Smallest (fixed line height ÷ font size) across paragraphs that use EXACT line spacing, or
    None when no such paragraph declares a font size to compare against (real measurement or
    nothing, ADR 0016). WCAG 1.4.12 asks a reader be able to set line height to 1.5× the font size:
    a fixed line box below that clips the override, and below 1.0× the box is already shorter than
    its own text."""
    ratios: list[float] = []
    if fmt == ".docx":
        for para in _W_PARA.findall(xml):
            sp = _W_SPACING_TAG.search(para)
            if not sp or 'w:lineRule="exact"' not in sp.group(0):
                continue
            m = _W_LINE_VAL.search(sp.group(0))
            szs = [int(s) for s in _W_SZ.findall(para)]
            if not m or not szs:
                continue
            line_pt = int(m.group(1)) / 20.0        # twentieths-pt → pt
            font_pt = max(szs) / 2.0                # half-pt → pt (tallest run drives the need)
            if font_pt > 0:
                ratios.append(line_pt / font_pt)
    else:  # .pptx
        for para in _A_PARA.findall(xml):
            m = _A_LNSPC_PTS.search(para)
            szs = [int(s) for s in _A_RUN_SZ.findall(para)]
            if not m or not szs:
                continue
            line_pt = int(m.group(1)) / 100.0       # hundredths-pt → pt
            font_pt = max(szs) / 100.0
            if font_pt > 0:
                ratios.append(line_pt / font_pt)
    return min(ratios) if ratios else None


def office_text_spacing_checks(path: Path, ext: str) -> list[dict]:
    """1.4.12 Text Spacing (Review) — exact (fixed) line spacing blocks the user's spacing
    override, which can clip text. Exact spacing is a deterministic attribute; whether it clips is
    a rendered outcome, so it is advisory. Never raises."""
    ext = (ext or "").lower()
    findings: list[dict] = []
    try:
        with zipfile.ZipFile(path) as zf:
            n = 0
            ratio = None
            if ext == ".docx":
                xml = _read(zf, "word/document.xml") or ""
                n = len(_W_LINERULE_EXACT.findall(xml))
                ratio = _min_exact_line_height_ratio(xml, ".docx")
            elif ext == ".pptx":
                for name in zf.namelist():
                    if re.fullmatch(r"ppt/slides/slide\d+\.xml", name):
                        xml = _read(zf, name) or ""
                        n += len(_A_EXACT_LNSPC.findall(xml))
                        r = _min_exact_line_height_ratio(xml, ".pptx")
                        if r is not None and (ratio is None or r < ratio):
                            ratio = r
            if n >= _MIN_EXACT_SPACING_PARAS:
                detail = (f"{n} paragraph(s) use exact (fixed) line spacing — a user who increases "
                          "line spacing for readability may see text clip; verify it reflows without loss")
                # #185 measured refinement: the tightest fixed line height as a multiple of the font
                # size, from the file's own values (no render). WCAG Text Spacing needs ≥1.5×.
                if ratio is not None:
                    detail = (
                        f"{n} paragraph(s) use exact (fixed) line spacing and the tightest is only "
                        f"{round(ratio, 2)}× the font size (WCAG Text Spacing needs 1.5×) — "
                        + ("the line box is already shorter than the text, so lines overlap; "
                           if ratio < 1.0 else
                           "a reader who increases line spacing will see text clip; ")
                        + "verify it reflows without loss")
                findings.append(_review_finding("OFFICE_EXACT_LINE_SPACING", "1.4.12 Text Spacing", detail))
    except Exception:
        return findings
    return findings


def resize_text_locators(src) -> list[dict]:
    """Fixed-size (auto-fit OFF) pptx text boxes holding a lot of text (>= _RESIZE_MIN_CHARS) — the
    1.4.4 Resize Text render targets: ``[{"part", "shape"}]`` (`shape` = cNvPr name|id, "" if none).
    `src` is a Path (detector) or bytes (the on-demand verify-resize endpoint). Never raises."""
    out: list[dict] = []
    try:
        opener = zipfile.ZipFile(io.BytesIO(src)) if isinstance(src, (bytes, bytearray)) else zipfile.ZipFile(src)
        with opener as zf:
            for name in sorted(n for n in zf.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)):
                xml = _read(zf, name) or ""
                for sp in _PPTX_SP.findall(xml):
                    if _A_NOAUTOFIT.search(sp) and len("".join(_AT.findall(sp))) >= _RESIZE_MIN_CHARS:
                        nm = _CNVPR_NAME.search(sp)
                        sid = _CNVPR_ID.search(sp)
                        frag = (nm.group(1) if nm else (sid.group(1) if sid else "")).strip()
                        out.append({"part": name, "shape": frag})
    except Exception:
        return out
    return out


def pptx_resize_text_checks(path: Path) -> list[dict]:
    """1.4.4 Resize Text (Review) — a fixed-size text box (auto-fit OFF) holding a lot of text may
    clip when text is enlarged to 200%. no-autofit is deterministic; the clip is a rendered
    outcome, so it is advisory (ADR 0024 Tier B measures it). Never raises."""
    boxes = resize_text_locators(path)
    if not boxes:
        return []
    finding = _review_finding(
        "PPTX_FIXED_TEXT_BOX_RESIZE", "1.4.4 Resize Text",
        f"{len(boxes)} fixed-size text box(es) (auto-fit off) hold a lot of text — verify the "
        "text doesn't clip when enlarged to 200%")
    targets = [b for b in boxes if b["shape"]]     # only render-attributable boxes for Tier B
    if targets:
        finding["locators"] = targets
    return [finding]


def hybrid_contrast_locators(src) -> list[dict]:
    """Every pptx text shape set over a PICTURE or GRADIENT fill (the 1.4.3-hybrid candidates):
    ``[{"part": "ppt/slides/slideN.xml", "shape": <cNvPr name|id, "" if none>, "kind": "picture"|"gradient"}]``.

    `src` is a Path (scan-time detector) OR raw bytes (the on-demand verify-contrast endpoint,
    which re-derives the targets from the source rather than persisting them — no schema change,
    ADR 0024). `shape` is best-effort: a shape with no `<p:cNvPr>` still counts toward the Tier-A
    flag but carries an empty `shape` (Tier B can't render-attribute it — the caller filters those
    out). Never raises: any parse error yields ``[]``."""
    out: list[dict] = []
    try:
        opener = zipfile.ZipFile(io.BytesIO(src)) if isinstance(src, (bytes, bytearray)) else zipfile.ZipFile(src)
        with opener as zf:
            for name in sorted(n for n in zf.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)):
                xml = _read(zf, name) or ""
                for sp in _PPTX_SP.findall(xml):
                    sppr_m = _PPTX_SPPR.search(sp)
                    if not sppr_m or not "".join(_AT.findall(sp)).strip():
                        continue                       # only shapes that actually hold text
                    sppr = sppr_m.group(0)
                    if _A_BLIPFILL.search(sppr):
                        kind = "picture"
                    elif _A_GRADFILL.search(sppr):
                        kind = "gradient"
                    else:
                        continue
                    # Prefer the shape name (geometry matches name or id); "" when neither is
                    # present — still a real Tier-A finding, just not a Tier-B render target.
                    nm = _CNVPR_NAME.search(sp)
                    sid = _CNVPR_ID.search(sp)
                    frag = (nm.group(1) if nm else (sid.group(1) if sid else "")).strip()
                    out.append({"part": name, "shape": frag, "kind": kind})
    except Exception:
        return out
    return out


def pptx_complex_bg_contrast_checks(path: Path) -> list[dict]:
    """1.4.3 Contrast — HYBRID review tier (ADR 0024). The deterministic core certifies text over
    an explicit SOLID fill; this flags text over a PICTURE or GRADIENT fill, whose effective
    background is a rendered pixel field contrast can't be read from colours alone. Advisory —
    Tier B samples the rendered pixels to measure it. Never raises. Rides the existing 1.4.3
    pass/fail lane (a definite solid-contrast FAIL still outranks this REVIEW)."""
    candidates = hybrid_contrast_locators(path)
    if not candidates:
        return []
    over_image = sum(1 for c in candidates if c["kind"] == "picture")
    over_gradient = sum(1 for c in candidates if c["kind"] == "gradient")
    bits = []
    if over_image:
        bits.append(f"{over_image} over a picture")
    if over_gradient:
        bits.append(f"{over_gradient} over a gradient")
    finding = _review_finding(
        "PPTX_TEXT_OVER_COMPLEX_BG", "1.4.3 Contrast (Minimum)",
        f"text sits {' and '.join(bits)} fill — contrast can't be read from declared "
        "colours; verify the text stays legible against the actual background")
    targets = [c for c in candidates if c["shape"]]   # only render-attributable shapes for Tier B
    if targets:
        finding["locators"] = targets
    return [finding]
