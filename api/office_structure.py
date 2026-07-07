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

docx/pptx style IDs (Heading1..9, title placeholder type) are locale-invariant
OOXML identifiers — only the *display* name is localized — so no styles.xml
cross-reference is needed to recognize them.

Scope not covered here (deliberately, see docs/TODO.md P1):
xlsx contrast/color-only needs style-index + conditional-formatting resolution
to avoid false-flagging routine formatting. pptx embedded-audio autoplay is
BLOCKED, not just deferred: distinguishing an autoplay media node from a
click-triggered one requires the exact p:timing trigger-condition XML, which
could not be verified against a real PowerPoint-generated ground-truth fixture
(no PowerPoint/LibreOffice available in this environment, and Microsoft's own
docs don't spell out the precise autoplay-vs-click structure) — do not
implement this from memory/guesswork.

Never raises — a parse failure just means no findings for that document.
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

_HEADING_STYLE = re.compile(r'<w:pStyle w:val="Heading(\d)"/>')
_PARA = re.compile(r"<w:p[ >].*?</w:p>", re.S)
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
# title — both are the slide's title for 2.4.6 purposes.
_PPTX_TITLE_PH = re.compile(r'<p:ph type="(?:ctrTitle|title)"\s*/>')
_A_RUN = re.compile(r"<a:r>(.*?)</a:r>", re.S)
_A_HLINK = re.compile(r'<a:hlinkClick[^>]*r:id="(rId\w+)"')
_AT = re.compile(r"<a:t>([^<]*)</a:t>")


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
    """links: [(display_text, href), ...]. Same algorithm as scanner.py's HTML
    2.4.9 check — identical text pointing at different real destinations fails
    'text alone', even though nothing here is analogous to 2.4.4's context credit."""
    groups: dict[str, set[str]] = {}
    for text, href in links:
        key = text.strip().lower()
        if not key or not href:
            continue
        groups.setdefault(key, set()).add(href)
    bad_hrefs = {h for hrefs in groups.values() if len(hrefs) > 1 for h in hrefs}
    return [_finding(rule_id, wcag, "MODERATE") for text, href in links if href in bad_hrefs]


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


# 4.5:1 (AA) / 7:1 (AAA) approximated the same way as scanner.py's HTML contrast
# checks — relative luma of the declared color; not a true APCA/WCAG contrast-
# ratio computation against the actual background, which for a PDF would need
# per-glyph background sampling. Consistent with the existing HTML heuristic.
_MIN_CHARS_PER_PAGE = 40  # bound pdfplumber work on huge PDFs


def _pdf_luma(rgb) -> float | None:
    if not isinstance(rgb, (tuple, list)) or len(rgb) < 3:
        return None
    r, g, b = rgb[0], rgb[1], rgb[2]
    return 0.299 * r + 0.587 * g + 0.114 * b


def pdf_contrast_checks(path: Path) -> list[dict]:
    findings: list[dict] = []
    seen_aa = seen_aaa = False
    try:
        import pdfplumber
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages:
                for ch in page.chars[:_MIN_CHARS_PER_PAGE]:
                    luma = _pdf_luma(ch.get("non_stroking_color"))
                    if luma is None:
                        continue
                    if luma > 0.45:
                        seen_aaa = True
                    if luma > 0.62:
                        seen_aa = True
                if seen_aa and seen_aaa:
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


def checks_for(path: Path, ext: str) -> list[dict]:
    """Dispatch by extension; returns [] for formats with no structural check yet."""
    ext = ext.lower()
    if ext == ".docx":
        return docx_checks(path)
    if ext == ".pptx":
        return pptx_checks(path)
    if ext == ".pdf":
        return pdf_contrast_checks(path) + pdf_bypass_blocks_check(path)
    return []
