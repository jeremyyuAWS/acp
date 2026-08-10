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
        heuristic way as the HTML/PDF contrast checks. Direct <color rgb="..."/>
        and theme=<N> (resolved against xl/theme/theme1.xml's <a:clrScheme>,
        tint applied per the SpreadsheetML tint formula — see _apply_xlsx_tint)
        both resolve deterministically. indexed= colors (the legacy 56-entry
        palette) and non-solid pattern fills (stripes/half-tones) still resolve
        to "unknown" and the cell is skipped rather than guessed at — that
        remaining population is genuinely ambiguous without also parsing the
        legacy indexed-color table. A cell with no explicit fill resolves to
        white with high confidence (Excel's actual default), which is
        different from "unresolvable" — that's a real, positive signal, not a
        guess.

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
from collections import Counter
from pathlib import Path

# `/?>` so the PAIRED spelling `<w:pStyle w:val="Heading1"></w:pStyle>` matches too. Both are
# valid OOXML; only Word consistently self-closes. A document from another producer had no
# outline at all as far as this pattern was concerned, which silences the heading-skip check,
# the empty-heading check and the 1.3.1 structure pass — none of which would error, all of
# which would report the file as clean. Found by tests/test_docx_producer_dialects.py.
_HEADING_STYLE = re.compile(r'<w:pStyle\s+w:val="Heading(\d)"\s*/?>')
_PARA = re.compile(r"<w:p[ >].*?</w:p>", re.S)
# A body with this many text-bearing paragraphs and zero headings is long enough
# that the lack of section structure is a real 2.4.10 problem (a short letter/memo
# below the floor legitimately needs none).
_MIN_PARAS_FOR_HEADINGS = 15
# Justified (both-margin) alignment is an explicit 1.4.8 failure. Require a few
# text-bearing justified paragraphs so a single incidental justified line (e.g. a
# banner) doesn't trip it — the SC is about blocks of body text. "distribute" is
# East-Asian full-justify, likewise a both-margins failure.
# `/?>` for the same reason as _HEADING_STYLE above: the paired spelling is legal and a
# justified document written that way reported no 1.4.8 finding.
_JC_BOTH = re.compile(r'<w:jc\s+w:val="(?:both|distribute)"\s*/?>')
_MIN_JUSTIFIED_PARAS = 3
# rIds are XML "ID" type, not necessarily numeric — Word/PowerPoint always emit
# pure digits (rId4), but any tool producing valid OOXML can use rIdFoo.
# ANY relationship id, not just Word's "rId7" convention. A relationship id is an opaque
# string in the standard, and the captured value is only ever used as a key into the .rels
# map — so a narrower pattern cannot reject a wrong id, only a correctly-formed one from a
# different producer. That is the exact reasoning apply_alt._R_EMBED already carries, arrived
# at the same way; this pattern kept the tight form and silenced 2.4.4, 2.4.9 and 1.4.1 on
# any document whose producer names ids differently.
_HYPERLINK = re.compile(r'<w:hyperlink[^>]*r:id="([^"]+)"[^>]*>(.*?)</w:hyperlink>', re.S)
_WT = re.compile(r"<w:t[^>]*>([^<]*)</w:t>")
# The secondary story parts a Word document keeps its text in, BESIDES word/document.xml: one
# part per running header and footer, and a single part each for foot- and endnotes. A link's
# purpose fails 2.4.4 wherever it lives, but docx_checks read only the body — so a "click here"
# in a page footer (a common home for one) produced no finding at all. Proven silent, then closed,
# by tests/test_docx_header_footer_parity.py.
_DOCX_STORY_PART = re.compile(r"^word/(?:header\d+|footer\d+|footnotes|endnotes)\.xml$")
# XML attributes are unordered, and .rels writers disagree: Word/PowerPoint emit
# Id first, openpyxl emits it LAST (Type/Target/TargetMode/Id). Grab the whole
# <Relationship ...> tag and read its attributes by name — a fixed Id-then-Target
# pattern silently returned {} for every openpyxl-written workbook.
_RELATIONSHIP = re.compile(r"<Relationship\s[^>]*>")
_REL_ATTR = re.compile(r'\s([\w:]+)="([^"]*)"')

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

# ── Large text that is NOT a heading ──────────────────────────────────────────
# "Bigger and bolder than the body text" is the only signal either heading scan has, and on
# a real document plenty of non-headings are set that way: a cover-page wordmark, a headline
# financial figure, a pull quote, a byline. Promoting one is worse than it sounds, because
# both consumers write WITHOUT review — the docx promoter styles it Heading N
# (remediate_office._remediate_docx_structure) and the PDF outline builder makes it a
# bookmark (remediate_pdf._generate_pdf_outline), and since 2.4.1 needs only text and order,
# nothing downstream ever objects.
#
# Shared by the docx detector, its promoter, and the PDF scan so all three agree about what
# a heading is. That is a correctness requirement, not tidiness: the promoter fixes exactly
# what the detector flags, so if this predicate rejects a paragraph, DOCX_PSEUDO_HEADING
# must not fire on it either — otherwise the fix stops clearing the re-scan and stops being
# credited.
#
# Each filter is deliberately narrow: it must be far likelier to catch furniture than a real
# section, so where a rule could go either way it keeps the line (ADR 0016 — derive, never
# fabricate, and don't discard what the document actually says).
_NUMERIC_HEADING = re.compile(
    r"""^\W*                                # leading bullet/quote/currency punctuation
        [+-]?\s*[$€£¥₹]?\s*                 # sign and/or currency symbol
        \d[\d,.\s]*                         # the figure itself
        \s*(?:%|billion|million|thousand|bn|mm|pts|pt|usd|eur|gbp|[bmkx])?
        \W*$""",
    re.IGNORECASE | re.VERBOSE)
# A heading does not open with a quote mark; a pull quote does, and closes with one (trailing
# sentence punctuation aside). A quote carrying an attribution suffix is a known miss —
# better than a rule loose enough to eat “Reasonable adjustments” as a heading.
_QUOTE_OPEN, _QUOTE_CLOSE = "\"'“„«‘‟", "\"'”»’‟"
# "By Jane Doe, Chief Accessibility Officer" — cover-page furniture. Guarded so a heading
# that merely starts with "by" survives: the next token must read as a name (capitalised)
# and not be a word that opens a real heading ("By the Numbers", "By Region").
_BYLINE = re.compile(
    r"^(?:by|written\s+by|prepared\s+by|photographs?\s+by|authors?)\s*:?\s+(\S+)",
    re.IGNORECASE)
_BYLINE_NOT_A_NAME = {"the", "a", "an", "all", "any", "our", "its", "region", "default",
                      "design", "numbers", "hand", "email", "phone", "law", "type"}
# Known cost, accepted deliberately: this also drops a genuinely short all-caps section
# name ("FAQ", "Q&A"). Nothing in the text tells those apart from a wordmark — same shape,
# same size — so the rule trades a rare missing entry for the common junk one.
_MAX_CAPS_FRAGMENT = 4          # "ACME", "FY26" — a wordmark or label, not a section name


def looks_like_heading_furniture(text: str) -> bool:
    """True when text set like a heading is really page furniture: a bare figure, a pull
    quote, a short all-caps wordmark, a byline. Text-only, so every caller can use it —
    running headers/footers need page geometry and stay with the PDF scan that has it."""
    t = (text or "").strip()
    if not t:
        return False
    if _NUMERIC_HEADING.match(t):                       # "$4.2B", "42", "3.1%", "2026"
        return True
    if t[0] in _QUOTE_OPEN and (t.rstrip(" .,;:!?") or " ")[-1] in _QUOTE_CLOSE:
        return True                                     # “We grew faster than the market.”
    compact = "".join(c for c in t if c.isalnum())
    # `t != t.lower()` keeps the rule to scripts that HAVE case: in an uncased script every
    # string is trivially its own upper-case, and a 2-character CJK heading is no wordmark.
    if t != t.lower() and t == t.upper() and len(compact) <= _MAX_CAPS_FRAGMENT:
        return True                                     # cover-page wordmark / stray label
    byline = _BYLINE.match(t)
    if byline:
        first = byline.group(1).strip(",.;:")
        if first[:1].isupper() and first.lower() not in _BYLINE_NOT_A_NAME:
            return True
    return False


def looks_like_pseudo_heading(text: str, *, bold: bool, max_half_pt: int,
                              styled_heading: bool) -> bool:
    """True when a paragraph reads as a heading but is not styled as one. Shared by the
    detector below and the remediator's promoter so detection and fix stay in lock-step."""
    if styled_heading:
        return False
    t = (text or "").strip()
    if not t or not _HAS_LETTER.search(t) or len(t.split()) > _PSEUDO_HEADING_MAX_WORDS:
        return False
    if looks_like_heading_furniture(t):
        return False                       # large, but a figure/quote/wordmark, not a section
    if max_half_pt >= PSEUDO_HEADING_MIN_HALF_PT:
        return True
    # a slightly-smaller but bold-and-short line is still heading-like
    return bool(bold and max_half_pt >= PSEUDO_HEADING_MIN_HALF_PT - 2)


# ── Is a heading-like paragraph DISTINGUISHED from this document's own body text? ────────────
#
# `looks_like_pseudo_heading` asks "does this read as a heading" against an ABSOLUTE floor of
# 14pt, and its own comment records the assumption underneath: "body text is ~22 (11pt)". That
# assumption is a property of the document, not a fact about documents.
#
# In a large-print document — body set at 14pt or 16pt, which is exactly what a low-vision
# reader is given — EVERY short paragraph clears the floor. The remediator then writes
# w:pStyle unattended on all of them, and a document whose real structure was fine comes back
# with a heading outline built from its body copy. The failure is silent, it is worst on the
# documents most likely to have been accessibility-remediated already, and nothing on screen
# says it happened.
#
# So the promoter asks a second, RELATIVE question before it stamps anything: is this paragraph
# clearly larger than the body text of the document it lives in? Detection is unchanged — a
# flagged paragraph is still flagged — this only decides auto-fix versus review.
STRONG_SIZE_MARGIN_HALF_PT = 4        # ≥ +2pt over this document's body → unambiguous on size
STRONG_BOLD_MARGIN_HALF_PT = 2        # ≥ +1pt over body AND bold → unambiguous


# Each pattern is bounded by its OWN closing tag, and that is not tidiness.
#
# `<w:style … styleId="Normal">.*?<w:sz>` without the `</w:style>` bound runs straight past the
# end of the Normal style and matches the first <w:sz> in whatever style comes next. Measured on
# three real fixtures (python-docx's default template and two Word-authored files): Normal
# carries NO explicit size, and the unbounded pattern returned 28 — the Heading style's 14pt —
# for every one of them. That is the baseline reading the WRONG way, since a too-large baseline
# makes real headings look undistinguished and routes correct auto-fixes to review.
_DOC_DEFAULT_SZ = re.compile(
    r"<w:docDefaults>.*?<w:rPrDefault>(.*?)</w:rPrDefault>", re.S)
_NORMAL_STYLE = re.compile(
    r"<w:style\b[^>]*w:styleId=\"Normal\"[^>]*>(.*?)</w:style>", re.S)
# `\s` after `w:sz` so this never matches `<w:szCs`, the complex-script size.
_SZ = re.compile(r"<w:sz\s+w:val=\"(\d+)\"")


def default_run_half_pt(styles_xml: str | bytes | None) -> int:
    """The size body text is set at when no run says otherwise, from word/styles.xml.

    THIS is the number that makes the baseline honest, and getting it from run sizes alone does
    not work. Word writes an explicit <w:sz> on a run only when it DIFFERS from the style — so a
    document's ordinary prose usually carries no size at all, and the explicit sizes that do
    exist are disproportionately the headings. Sampling those would compute a "body baseline"
    out of the headings and then measure the headings against it, which is both circular and
    biased in the dangerous direction: it makes every heading look un-distinguished.

    docDefaults first, then the Normal style. 0 when neither says.
    """
    if not styles_xml:
        return 0
    xml = styles_xml.decode("utf-8", "replace") if isinstance(styles_xml, bytes) else styles_xml
    for pat in (_DOC_DEFAULT_SZ, _NORMAL_STYLE):
        block = pat.search(xml)
        if not block:
            continue
        sz = _SZ.search(block.group(1))
        if sz:
            try:
                return int(sz.group(1))
            except (TypeError, ValueError):
                pass
    return 0


def body_baseline_half_pt(sizes) -> int:
    """This document's body-text size, in half-points: the most common PARAGRAPH size in it.

    Per paragraph, not per run — one paragraph is one vote. A run-weighted count lets a single
    heavily-split paragraph (Word fragments runs on every formatting or spell-check boundary)
    outvote the rest of the document, and the split has nothing to do with what the text is.

    Ties break to the SMALLER size. Body text is the common, small size and headings are the
    rarer large ones, so on a tie the smaller reading is the one that cannot mistake a heading
    for body — and mistaking a heading for body only costs a missed promotion, while the reverse
    restyles body copy, which is the failure this whole gate exists to stop.

    Returns 0 when there is nothing to count, which callers must read as "no baseline
    available", never as "body is 0pt".
    """
    counts = Counter(int(s) for s in sizes if s)
    if not counts:
        return 0
    top = max(counts.values())
    return min(s for s, c in counts.items() if c == top)


def heading_signal(text: str, *, bold: bool, max_half_pt: int, body_half_pt: int,
                   styled_heading: bool) -> str | None:
    """'strong' | 'weak' | None for one paragraph.

    None     — not heading-like at all, or already styled as a heading.
    'strong' — heading-like AND clearly larger (or bold and larger) than this document's body
               baseline. Deterministic and reproducible, so it is auto-fixed with no approval.
    'weak'   — heading-like by the absolute floor but NOT distinguished from the body around it.
               Ambiguous: it may be a section name in a large-print document, or it may be an
               emphasised sentence. Never stamped; routed to review instead.

    `body_half_pt` of 0 means no baseline could be measured (no explicit run sizes anywhere).
    That is treated as STRONG — i.e. exactly the behaviour before this gate existed — because a
    document with no size information gives this refinement nothing to work with, and silently
    downgrading every promotion to review there would remove a working fix rather than sharpen
    it. The gate narrows what gets stamped only where it has evidence to narrow it.
    """
    if not looks_like_pseudo_heading(text, bold=bold, max_half_pt=max_half_pt,
                                     styled_heading=styled_heading):
        return None
    if not body_half_pt:
        return "strong"
    over = max_half_pt - body_half_pt
    if over >= STRONG_SIZE_MARGIN_HALF_PT:
        return "strong"
    if bold and over >= STRONG_BOLD_MARGIN_HALF_PT:
        return "strong"
    return "weak"

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
_SDT_TAG = re.compile(r'<w:tag\s+w:val="([^"]*)"')

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


def _docx_story_xmls(zf: zipfile.ZipFile) -> list[str]:
    """The XML of every docx part that carries body-like text: word/document.xml plus the running
    header/footer and foot/endnote parts (_DOCX_STORY_PART).

    A judgement about CONTENT — a hyperlink's purpose, a passage's language mark, a form control's
    label — must read all of these, because the same defect in a header is the same defect. Reading
    document.xml alone is a recurring blind spot: it was closed for link purpose (#214), language of
    parts (#226) and use of colour (#227) by walking exactly this set, and this helper is the one
    name for it so those checks cannot drift apart on which parts count. Empty or unreadable parts
    drop out; a docx with no document.xml still yields whatever story parts it has. Never raises."""
    xmls = [_read(zf, "word/document.xml") or ""]
    xmls += [_read(zf, n) or "" for n in zf.namelist() if _DOCX_STORY_PART.match(n)]
    return [x for x in xmls if x]


def _relationships(zf: zipfile.ZipFile, rels_path: str) -> dict[str, str]:
    """{rId -> Target} for a .rels part, independent of attribute order."""
    xml = _read(zf, rels_path)
    if not xml:
        return {}
    rels: dict[str, str] = {}
    for tag in _RELATIONSHIP.findall(xml):
        attrs = dict(_REL_ATTR.findall(tag))
        rid, target = attrs.get("Id"), attrs.get("Target")
        if rid and target:
            rels[rid] = target
    return rels


def _finding(rule_id: str, wcag: str, severity: str) -> dict:
    return {"ruleId": rule_id, "wcag": wcag, "severity": severity}


def _review_finding(rule_id: str, wcag: str, detail: str, evidence: dict | None = None) -> dict:
    """A Review-Recommended finding (ADR 0023): advisory, evidence-carrying, and
    NON-blocking. Severity "REVIEW" has a zero penalty weight in the rubric, so it
    never lowers the score or blocks certification — it flags a concrete risk a human
    must adjudicate, never claims a pass, and offers no ACP fix (ADR 0016).

    `evidence` (ADR 0026 Epic 2, optional) is the STRUCTURED form of the measurement already
    worded in `detail` — e.g. {"method": "structural", "metric": "contrast", "value": 2.4,
    "required": 3.0, "unit": ":1"} — so the UI's compact evidence header can show
    "Structural · Contrast 2.4:1 · Required 3:1" instead of parsing prose. Only attached where a
    detector holds a REAL number (ADR 0016: a value or nothing, never a synthesized one)."""
    f = {"ruleId": rule_id, "wcag": wcag, "severity": "REVIEW", "advisory": True, "detail": detail}
    if evidence:
        f["evidence"] = evidence
    return f


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


def _vague_link_findings(texts: list[str], rule_id: str, wcag: str) -> list[dict]:
    """2.4.4 — display text that names nothing about where the link goes ("click here", a
    bare URL). One finding per file carrying the count and a REAL example off the document,
    so the review card shows what actually tripped it.

    Shared by every Office format so docx/pptx/xlsx judge link text by one predicate — the
    same one proposals.propose_link_texts derives replacements for, which is what lets an
    approved link-text fix be verified by a re-scan instead of credited on trust.

    Empty text is skipped rather than flagged: a hyperlink with no text of its own wraps a
    drawing, and an image link's purpose comes from the image's alt text — 1.1.1's subject,
    not this one. Flagging it here would report one problem twice.
    """
    vague = [s for t in texts if (s := (t or "").strip()) and _is_vague_link_text(s)]
    if not vague:
        return []
    f = _finding(rule_id, wcag, "MODERATE")
    f["detail"] = (f"{len(vague)} hyperlink(s) with unclear text (e.g. “{vague[0]}”) — "
                   "a screen-reader user cannot tell where the link goes")
    return [f]


def _docx_hyperlinks(zf: zipfile.ZipFile, doc_xml: str) -> list[tuple[str, str]]:
    """(display text, href) for every external hyperlink in the body AND the running
    header/footer and foot/endnote parts.

    Each part resolves its OWN relationships file — an rId is part-local, so the body's
    word/_rels/document.xml.rels cannot answer a footer's link, and using it would silently map a
    footer rId onto whatever the body happened to name the same. word/_rels/footer1.xml.rels is
    the only correct source for word/footer1.xml, so the rels path is derived from each part's own
    name. Missing parts and missing rels degrade to nothing, never to a wrong href."""
    parts = [("word/document.xml", doc_xml)]
    for n in zf.namelist():
        if _DOCX_STORY_PART.match(n):
            xml = _read(zf, n)
            if xml:
                parts.append((n, xml))
    links: list[tuple[str, str]] = []
    for name, xml in parts:
        head, _, tail = name.rpartition("/")
        rels = _relationships(zf, f"{head}/_rels/{tail}.rels")
        for rid, inner in _HYPERLINK.findall(xml):
            href = rels.get(rid)
            if href:
                links.append(("".join(_WT.findall(inner)), href))
    return links


def docx_checks(path: Path) -> list[dict]:
    findings: list[dict] = []
    try:
        with zipfile.ZipFile(path) as zf:
            doc = _read(zf, "word/document.xml")
            if not doc:
                return []

            # 2.4.6 — heading level skips (e.g. Heading1 → Heading3). EVERY gap is reported,
            # not just the first: remediate_office closes them all in one pass, so stopping at
            # the first understated the work and left a doc looking one edit away from clean
            # when it was several. `prev_level` advances to the level actually in the document
            # (not the clamped prev+1), which is what keeps H1→H3→H4 a single finding — the
            # outline has one gap there, and the H3→H4 step is well-formed.
            prev_level = 0
            for ordinal, m in enumerate(_HEADING_STYLE.finditer(doc), start=1):
                level = int(m.group(1))
                if prev_level > 0 and level > prev_level + 1:
                    f = _finding("DOCX_HEADING_SKIP", "2.4.6 Headings and Labels", "MODERATE")
                    # Carry the actual levels so the review card can show the before/after outline
                    # (H{prev} → H{level}, should be H{prev} → H{prev+1}) — real, not illustrative.
                    # The ordinal keeps two identical gaps (two separate H1→H3s) distinguishable.
                    f["detail"] = (f"Heading {ordinal}: level jumps from H{prev_level} to H{level} "
                                   f"(should step to H{prev_level + 1})")
                    findings.append(f)
                prev_level = level

            # 2.4.6 — a heading with NO TEXT. The outline walk above reads pStyle refs and never
            # the heading's content, so an empty Heading paragraph passed through every check
            # ACP has: it is in the outline (so no pseudo-heading finding), it breaks no level
            # sequence (so no skip finding), and it has no runs to fail contrast on.
            #
            # It is a real defect and a specifically nasty one. Screen readers offer a heading
            # list as the primary way to navigate a long document; an empty entry is an
            # announcement of nothing — the user is told a section exists, cannot tell what it
            # is, and cannot tell whether they have missed content. On a 25-page benefits
            # handbook that is a navigation dead end, not a cosmetic slip.
            #
            # Deliberately narrow. Only a heading-styled paragraph whose text is empty or
            # whitespace, and only when it holds no drawing — a heading whose content is an image
            # has a different problem (1.1.1's, if the image lacks alt text), and reporting it
            # here would report one defect twice under two criteria.
            for ordinal, p in enumerate(_PARA.findall(doc), start=1):
                if not _HEADING_ANY.search(p):
                    continue
                if "<w:drawing" in p or "<w:pict" in p:
                    continue
                if "".join(_WT.findall(p)).strip():
                    continue
                f = _finding("DOCX_HEADING_EMPTY", "2.4.6 Headings and Labels", "MODERATE")
                lvl = _HEADING_STYLE.search(p)
                f["detail"] = (
                    f"Heading {ordinal}"
                    + (f" (H{lvl.group(1)})" if lvl else "")
                    + " has no text — a screen reader announces it in the heading list with "
                      "nothing to announce, so the section cannot be identified or skipped")
                findings.append(f)

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

            # 2.4.4 — link text that conveys nothing about its destination, and 2.4.9 — display
            # text reused for a different destination. The partner engine's DOCX-LINK-001 is
            # mapped to 2.4.4 as well, but it only runs when the .NET analyser is reachable;
            # ACP's own re-scan is what credits an approved link-text fix (handlers
            # _apply_one_value_kind), so that criterion needs a check ACP always runs itself.
            # Across the body AND the header/footer/foot-endnote parts (see _docx_hyperlinks):
            # a vague or ambiguous link is a 2.4.4 / 2.4.9 failure wherever a reader meets it, and
            # a page footer is a common home for a bare "click here".
            links = _docx_hyperlinks(zf, doc)
            findings += _vague_link_findings([t for t, _ in links], "DOCX_LINK_PURPOSE_VAGUE",
                                             "2.4.4 Link Purpose (In Context)")
            findings += _duplicate_href_findings(links, "DOCX_LINK_PURPOSE_AMBIGUOUS", "2.4.9 Link Purpose (Link Only)")

            # 3.3.2 — interactive content-control form fields (checkbox, date
            # picker, dropdown, combo box, picture) with no alias/title set.
            #
            # 4.1.2 — the SAME condition, deliberately. A content control's Title
            # (w:alias) is simultaneously the visible label 3.3.2 asks for AND the
            # accessible NAME Word exposes to assistive tech, so a field without one
            # fails both: a sighted user gets no prompt, a screen-reader user gets no
            # announced name.
            #
            # This replaces a w:tag check that shipped in 062642f (PR #6). That check
            # asserted tag was "the stable programmatic identifier assistive tech uses
            # to expose the field's Name" — it is not. w:tag is a developer-facing
            # identifier for data binding and is never announced; w:alias is what
            # reaches the accessibility tree. So the old check could fail a document
            # whose fields were perfectly announceable, and pass one whose fields were
            # anonymous to AT — wrong in both directions on the criterion it claimed.
            # The 4.1.2 half moved to formats/docx/detectors/name_role_value.py when the pair
            # was migrated to the capability registry — the same move PDF 4.1.2 made, and for
            # the same reason. RULE_FORMATS could say WHICH formats the criterion is judged on
            # but not how much of it a detector reaches, so a clean document reported
            # NOT_EVALUATED ("we did not look") for a check that had in fact run. Coverage lives
            # in the registration now, and a clean file reads REVIEW.
            #
            # 3.3.2 stays here: it is not a registry pair, and it is the SAME condition — a
            # missing Title fails both at once. Delegating the 4.1.2 emission rather than
            # re-deriving it is what keeps the two from drifting apart.
            # Read controls from the body AND the running header/footer and foot/endnote parts —
            # a form field in a header (a Patient-ID or date field on a clinical form) needs a
            # label as much as one in the body. _docx_name_role reads the same part set, so 3.3.2
            # here and the 4.1.2 it delegates below stay over identical populations.
            from formats.docx.detectors.name_role_value import detect as _docx_name_role
            for story_xml in _docx_story_xmls(zf):
                for sdt_inner in _SDT.findall(story_xml):
                    pr_m = _SDT_PR.search(sdt_inner)
                    if not pr_m or not _SDT_INPUT_TYPE.search(pr_m.group(1)):
                        continue
                    alias_m = _SDT_ALIAS.search(pr_m.group(1))
                    if not alias_m or not alias_m.group(1).strip():
                        findings.append(_finding("DOCX_FORM_FIELD_NO_LABEL", "3.3.2 Labels or Instructions", "SERIOUS"))
            findings += _docx_name_role(path)

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
    """2.4.4 Link Purpose (In Context) — cell hyperlinks whose display text is vague or a
    raw URL. 2.4.6 Headings and Labels — uninformative structure labels (multiple default 'SheetN'
    tabs, or default 'ColumnN' table headers). Detection only; both route to human remediation."""
    findings: list[dict] = []
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            # 2.4.4 — judge only links that carry an explicit display text; a link with no display
            # attribute takes its label from the cell value (not resolved here), so skipping it
            # avoids false positives. Same shared judgement as docx/pptx (_vague_link_findings).
            displays: list[str] = []
            for n in names:
                if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n):
                    xml = _read(zf, n) or ""
                    for tag in _XLSX_HL.findall(xml):
                        m = _HL_DISPLAY.search(tag)
                        if m:
                            displays.append(m.group(1))
            findings += _vague_link_findings(displays, "XLSX_LINK_PURPOSE_VAGUE",
                                             "2.4.4 Link Purpose (In Context)")

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

                # 2.4.4 — link text that conveys nothing about its destination, and 2.4.9 —
                # display text reused for a different destination (both judged once, after the
                # loop, over every slide's links). PPTX-LINK-001 in the partner engine is mapped
                # to 2.4.4 too, but ACP's own re-scan is what credits an approved link-text fix
                # (handlers _apply_one_value_kind), so it needs a check ACP always runs itself.
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
            findings += _vague_link_findings([t for t, _ in all_links], "PPTX_LINK_PURPOSE_VAGUE",
                                             "2.4.4 Link Purpose (In Context)")
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


# 4.5:1 (AA) / 7:1 (AAA) measured as a TRUE WCAG contrast ratio (`_contrast_ratio`)
# between each glyph's declared fill colour and the background structurally resolved
# behind it (`_pdf_char_background`). This replaced a declared-colour luma threshold that
# assumed every page was white: it called white-on-black a SERIOUS failure (really 21:1)
# and passed #4C4C4C on #262626 (really 1.76:1), in both directions with confidence.
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


def _pdf_color_hex(color) -> str | None:
    """pdfplumber colour (DeviceGray float, RGB 3-tuple, or CMYK 4-tuple, each 0..1) → 6-hex, so it
    can feed the WCAG `_contrast_ratio` the Office non-text-contrast checks already use. None when
    the colour can't be read."""
    def _byte(x: float) -> int:
        return int(round(max(0.0, min(1.0, x)) * 255))
    try:
        if isinstance(color, (int, float)):
            v = _byte(float(color))
            return f"{v:02X}{v:02X}{v:02X}"
        if not isinstance(color, (tuple, list)) or not color:
            return None
        vals = [float(v) for v in color]
        if len(vals) == 1:
            v = _byte(vals[0])
            return f"{v:02X}{v:02X}{v:02X}"
        if len(vals) == 3:
            r, g, b = vals
        elif len(vals) == 4:
            c, m, y, k = vals
            r, g, b = (1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k)
        else:
            return None
        return "".join(f"{_byte(x):02X}" for x in (r, g, b))
    except (TypeError, ValueError):
        return None



def _cap_note(pages_total: int, cap: int) -> str:
    """Honest-caps suffix (ADR 0026 Epic 1): when a document exceeds a detector's page cap, the
    finding SAYS so — silent truncation reads as full coverage, which is a lie by omission."""
    if pages_total > cap:
        return f" — measured the first {cap} of {pages_total} pages"
    return ""


def pdf_nontext_contrast_checks(path: Path) -> list[dict]:
    """1.4.11 Non-text Contrast (Review) for PDF (ADR 0025) — the lowest-contrast bordered rectangle
    (its stroke colour against its own fill, < 3:1). The PDF analogue of the docx/pptx solid
    outline-on-fill check, reading pdfplumber rect stroke/fill colours (no render). Only rects that
    declare BOTH a stroke and a fill are measured — real measurement or nothing (ADR 0016).
    Advisory, never a pass. Never raises."""
    worst = None      # (ratio, border_hex, fill_hex)
    pages_total = 0
    try:
        import pdfplumber
        with pdfplumber.open(str(path)) as pdf:
            pages_total = len(pdf.pages)
            for page in pdf.pages[:_MAX_PAGES_SPACING]:
                for r in page.rects:
                    border = _pdf_color_hex(r.get("stroking_color"))
                    fill = _pdf_color_hex(r.get("non_stroking_color"))
                    if not border or not fill:
                        continue
                    ratio = _contrast_ratio(border, fill)
                    if ratio < 3.0 and (worst is None or ratio < worst[0]):
                        worst = (ratio, border, fill)
    except Exception:
        return []
    if worst is None:
        return []
    ratio, border_hex, fill_hex = worst
    return [_review_finding(
        "PDF_NONTEXT_LOW_CONTRAST", "1.4.11 Non-text Contrast",
        f"a shape outline #{border_hex} on its #{fill_hex} fill is {ratio:.1f}:1 (needs 3:1) — if the "
        "shape conveys meaning, its boundary may be too faint to see; verify it isn't decorative"
        + _cap_note(pages_total, _MAX_PAGES_SPACING),
        evidence={"method": "structural", "metric": "Contrast", "value": round(ratio, 2),
                  "required": 3.0, "unit": ":1",
                  **({"pages_checked": _MAX_PAGES_SPACING, "pages_total": pages_total}
                     if pages_total > _MAX_PAGES_SPACING else {})})]


_MAX_PAGES_OVER_IMAGE = 20     # cap the pages we scan for text-over-image
_MIN_OVERLAP_FRAC = 0.6        # a char counts as "over" an image when ≥60% of its box is inside one


def _bbox_overlap_frac(cx0: float, ctop: float, cx1: float, cbot: float,
                       ix0: float, itop: float, ix1: float, ibot: float) -> float:
    """Fraction of the char box (first bbox) that falls inside the image box (second). 0 when the
    char has no area or the boxes don't intersect."""
    ca = max(0.0, cx1 - cx0) * max(0.0, cbot - ctop)
    if ca <= 0:
        return 0.0
    ox = max(0.0, min(cx1, ix1) - max(cx0, ix0))
    oy = max(0.0, min(cbot, ibot) - max(ctop, itop))
    return (ox * oy) / ca


def pdf_text_over_image_checks(path: Path) -> list[dict]:
    """1.4.3 Contrast (Minimum), text-over-image case (Review) for PDF (ADR 0025). `pdf_contrast_checks`
    resolves each char's background from page STRUCTURE (fill rects, page default) — which can answer a
    panel or a coloured page exactly, but never text laid over a raster image (photo/gradient/
    screenshot), where the real background is the pixels. It abstains there rather than fabricate a
    ratio, and this owns the case instead: any char whose box sits ≥60% inside an image XObject. Purely
    structural (pdfplumber char + image bboxes, no render); the render-verified pixel measurement under
    the char is the documented follow-on. Rides the existing 1.4.3 lane as a per-file finding — 1.4.3
    stays 🟢 at the format level. Advisory, never a pass. Never raises."""
    hits = 0
    pages_total = 0
    try:
        import pdfplumber
        with pdfplumber.open(str(path)) as pdf:
            pages_total = len(pdf.pages)
            for page in pdf.pages[:_MAX_PAGES_OVER_IMAGE]:
                images = page.images
                if not images:
                    continue
                boxes = [(im["x0"], im["top"], im["x1"], im["bottom"]) for im in images]
                for ch in page.chars[:_MAX_CHARS_PER_PAGE]:
                    try:
                        cx0, ctop, cx1, cbot = (float(ch["x0"]), float(ch["top"]),
                                                float(ch["x1"]), float(ch["bottom"]))
                    except (KeyError, TypeError, ValueError):
                        continue
                    for ix0, itop, ix1, ibot in boxes:
                        if _bbox_overlap_frac(cx0, ctop, cx1, cbot, ix0, itop, ix1, ibot) >= _MIN_OVERLAP_FRAC:
                            hits += 1
                            break
    except Exception:
        return []
    if hits == 0:
        return []
    return [_review_finding(
        "PDF_TEXT_OVER_IMAGE", "1.4.3 Contrast (Minimum)",
        f"{hits} character{'s' if hits != 1 else ''} sit over an image, where the real background is "
        "the picture's pixels — the declared text colour can't prove contrast here; verify the text "
        "stays legible against the image behind it" + _cap_note(pages_total, _MAX_PAGES_OVER_IMAGE))]


_MAX_PAGES_SCANNED = 20         # cap the pages we scan for the scanned-page heuristic
_SCANNED_MAX_CHARS = 5          # a page with this few extractable chars is treated as textless
_SCANNED_MIN_IMAGE_AREA_FRAC = 0.8   # an image covering this much of the page reads as "the whole page"


def pdf_scanned_page_checks(path: Path) -> list[dict]:
    """1.4.5 Images of Text (Review) for PDF — a cheap, deterministic pre-OCR heuristic (ADR 0025
    style): a page with near-zero extractable text AND one image covering most of the page is very
    likely a scanned photocopy, not a genuine born-digital PDF. Distinct from ocr.py's
    `images_of_text`, which OCRs embedded images and needs the OCR stack available/enabled — this
    needs neither, so it still surfaces the risk when OCR is unavailable or disabled, and it's far
    cheaper to run. Structural only (pdfplumber char + image bboxes, no render, no OCR). Purely
    advisory (ADR 0023) — a full page of chars extracted from an unusual font can still trip the
    char-count floor, so this never claims a fail on its own. Never raises."""
    hits = 0
    pages_total = 0
    try:
        import pdfplumber
        with pdfplumber.open(str(path)) as pdf:
            pages_total = len(pdf.pages)
            for page in pdf.pages[:_MAX_PAGES_SCANNED]:
                if len(page.chars) > _SCANNED_MAX_CHARS:
                    continue
                pw, ph = float(page.width or 0), float(page.height or 0)
                page_area = pw * ph
                if page_area <= 0:
                    continue
                for im in page.images:
                    try:
                        ix0, itop, ix1, ibot = (float(im["x0"]), float(im["top"]),
                                                 float(im["x1"]), float(im["bottom"]))
                    except (KeyError, TypeError, ValueError):
                        continue
                    img_area = max(0.0, ix1 - ix0) * max(0.0, ibot - itop)
                    if img_area / page_area >= _SCANNED_MIN_IMAGE_AREA_FRAC:
                        hits += 1
                        break
    except Exception:
        return []
    if hits == 0:
        return []
    return [_review_finding(
        "PDF_LIKELY_SCANNED", "1.4.5 Images of Text",
        f"{hits} page{'s' if hits != 1 else ''} have almost no extractable text and are dominated "
        "by a single full-page image — this looks like a scanned document with no real text layer; "
        "verify whether OCR text was added or the page needs to be re-authored as real text"
        + _cap_note(pages_total, _MAX_PAGES_SCANNED),
        evidence={"method": "structural", "metric": "pages flagged", "value": hits})]


def pdf_over_image_locators(data) -> list[dict]:
    """The text RUNS that sit over an image — the render targets for the ADR 0025 Tier B
    pixel-sample measurement (the DRY source the on-demand endpoint re-derives from, the PDF analogue
    of `hybrid_contrast_locators`). Accepts PDF bytes OR a Path. Each run groups the over-image chars
    on one text line into a union bbox in NORMALIZED page fractions `{x,y,w,h,page}` — the shape
    `render_verify.region_contrast` samples. A single glyph is mostly ink; a run carries ink AND the
    image background around it, which is what a contrast measurement needs. Never raises."""
    import io
    runs: list[dict] = []
    try:
        import pdfplumber
        src = io.BytesIO(data) if isinstance(data, (bytes, bytearray)) else str(data)
        with pdfplumber.open(src) as pdf:
            for pno, page in enumerate(pdf.pages[:_MAX_PAGES_OVER_IMAGE], start=1):
                images = page.images
                if not images:
                    continue
                pw, ph = float(page.width or 0), float(page.height or 0)
                if pw <= 0 or ph <= 0:
                    continue
                boxes = [(im["x0"], im["top"], im["x1"], im["bottom"]) for im in images]
                lines: dict[int, list[tuple]] = {}
                for ch in page.chars[:_MAX_CHARS_PER_PAGE]:
                    try:
                        cx0, ctop, cx1, cbot = (float(ch["x0"]), float(ch["top"]),
                                                float(ch["x1"]), float(ch["bottom"]))
                    except (KeyError, TypeError, ValueError):
                        continue
                    if any(_bbox_overlap_frac(cx0, ctop, cx1, cbot, *b) >= _MIN_OVERLAP_FRAC
                           for b in boxes):
                        lines.setdefault(round(ctop), []).append((cx0, ctop, cx1, cbot))
                for chs in lines.values():
                    x0 = min(c[0] for c in chs)
                    top = min(c[1] for c in chs)
                    x1 = max(c[2] for c in chs)
                    bot = max(c[3] for c in chs)
                    runs.append({"page": pno, "chars": len(chs), "bbox": {
                        "x": x0 / pw, "y": top / ph, "w": (x1 - x0) / pw, "h": (bot - top) / ph,
                        "page": pno}})
    except Exception:
        return []
    return runs


# ── What is actually BEHIND a glyph — structural background resolution (no render) ──
# A contrast ratio needs two colours. The declared text colour is on the char; the
# background is not, and assuming the page is white is wrong in BOTH directions. Resolve
# it from structure instead: the topmost FILLED rect (content-stream order) whose box
# contains the glyph box, else the page's default background. That answers the ordinary
# dark-theme / dark-cover document exactly, with no pixel sampling. Two cases structure
# genuinely cannot answer — a glyph over an IMAGE (the background is the picture's pixels)
# and a glyph STRADDLING a fill edge (two backgrounds, neither is "the" one) — resolve to
# None so callers abstain rather than guess; `pdf_text_over_image_checks` already carries
# the over-image case as its own review finding (ADR 0025 Tier B renders that one).
_PDF_DEFAULT_BG = "FFFFFF"
# How much of a glyph's box a fill must cover to BE its background. Strict containment is too
# brittle for real documents in both directions: a glyph's font box routinely overhangs a
# snug panel by a few percent (still plainly on the panel), and a glyph beside a table rule
# grazes that rule's thin filled rect (plainly not on it). So: mostly covered ⇒ that fill is
# the background; barely touched ⇒ not this fill, keep looking; in between ⇒ the glyph really
# does sit across a fill edge with two backgrounds, and we resolve nothing rather than pick.
_PDF_BG_COVERS_FRAC = 0.9
_PDF_BG_GRAZES_FRAC = 0.1
_PDF_LARGE_PT = 18.0            # WCAG "large text": ≥18pt, or ≥14pt bold
_PDF_LARGE_BOLD_PT = 14.0


def _pdf_filled_rects(page) -> list[tuple[float, float, float, float, str]]:
    """(x0, top, x1, bottom, hex) for every rect on the page that PAINTS a fill, kept in
    content-stream order so the LAST match is the topmost. Rects whose fill colour can't
    be read are dropped — an unreadable fill is not a background we can measure against."""
    out = []
    for r in page.rects:
        if not r.get("fill"):
            continue
        hex6 = _pdf_color_hex(r.get("non_stroking_color"))
        if not hex6:
            continue
        try:
            out.append((float(r["x0"]), float(r["top"]),
                        float(r["x1"]), float(r["bottom"]), hex6))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _pdf_char_background(ch, rects, images) -> str | None:
    """The background hex behind one glyph, or None when structure can't resolve it (see
    the note above). `rects` from `_pdf_filled_rects`, `images` as (x0, top, x1, bottom)."""
    try:
        cx0, ctop, cx1, cbot = (float(ch["x0"]), float(ch["top"]),
                                float(ch["x1"]), float(ch["bottom"]))
    except (KeyError, TypeError, ValueError):
        return None
    for box in images:
        if _bbox_overlap_frac(cx0, ctop, cx1, cbot, *box) >= _MIN_OVERLAP_FRAC:
            return None                              # over a picture — pixels, not structure
    for x0, top, x1, bot, hex6 in reversed(rects):   # topmost fill wins
        frac = _bbox_overlap_frac(cx0, ctop, cx1, cbot, x0, top, x1, bot)
        if frac >= _PDF_BG_COVERS_FRAC:
            return hex6
        if frac > _PDF_BG_GRAZES_FRAC:
            return None                              # straddles this fill's edge
    return _PDF_DEFAULT_BG


def _pdf_required_ratios(ch) -> tuple[float, float]:
    """(AA, AAA) ratio this glyph must meet — the WCAG large-text bar (3:1 / 4.5:1) at
    ≥18pt or ≥14pt bold, the normal-text bar (4.5:1 / 7:1) otherwise. Without this, every
    24pt heading at 4:1 would read as a SERIOUS AA failure it isn't."""
    try:
        size = float(ch.get("size") or 0)
    except (TypeError, ValueError):
        size = 0.0
    bold = "bold" in str(ch.get("fontname") or "").lower()
    if size >= _PDF_LARGE_PT or (bold and size >= _PDF_LARGE_BOLD_PT):
        return 3.0, 4.5
    return 4.5, 7.0


def _pdf_char_cap_note(pages_total: int, pages_read: int, pages_capped: int) -> str:
    """Honest-caps suffix for the char-capped PDF text detectors (ADR 0026 Epic 1) — the
    page-based `_cap_note` can't describe a per-page CHARACTER cap, which is why
    `pdf_contrast_checks` was the one PDF detector truncating silently. Empty when nothing
    was actually truncated."""
    bits = []
    if pages_capped:
        bits.append(f"the first {_MAX_CHARS_PER_PAGE} characters on {pages_capped} "
                    f"page{'s' if pages_capped != 1 else ''}")
    if pages_read < pages_total:
        bits.append(f"the first {pages_read} of {pages_total} pages "
                    f"({_MAX_CHARS_TOTAL}-character limit reached)")
    return f" — measured {' and '.join(bits)}" if bits else ""


def _pdf_contrast_scan(path_or_bytes):
    """Walk a PDF's glyphs once, yielding (page_index, char, text_hex, bg_hex_or_None) for
    every char whose colour is readable, honouring both char caps. The single traversal
    behind BOTH the detector and the fixer's recolour plan, so a finding and a fix can
    never disagree about what a glyph's background is. Returns
    (rows, pages_total, pages_read, pages_capped). Raises — callers decide."""
    import io
    import pdfplumber
    rows = []
    total = pages_total = pages_read = pages_capped = 0
    src = (io.BytesIO(path_or_bytes) if isinstance(path_or_bytes, (bytes, bytearray))
           else str(path_or_bytes))
    with pdfplumber.open(src) as pdf:
        pages_total = len(pdf.pages)
        for pi, page in enumerate(pdf.pages):
            rects = _pdf_filled_rects(page)
            images = []
            for im in page.images:
                try:
                    images.append((float(im["x0"]), float(im["top"]),
                                   float(im["x1"]), float(im["bottom"])))
                except (KeyError, TypeError, ValueError):
                    continue
            chars = page.chars
            if len(chars) > _MAX_CHARS_PER_PAGE:
                pages_capped += 1
            for ch in chars[:_MAX_CHARS_PER_PAGE]:
                total += 1
                fg = _pdf_color_hex(ch.get("non_stroking_color"))
                if fg:
                    rows.append((pi, ch, fg, _pdf_char_background(ch, rects, images)))
            pages_read = pi + 1
            if total >= _MAX_CHARS_TOTAL:
                break
    return rows, pages_total, pages_read, pages_capped


def pdf_contrast_checks(path: Path) -> list[dict]:
    """1.4.3 / 1.4.6 Contrast for PDF — a REAL WCAG contrast ratio per glyph: its declared
    fill colour against the background structurally resolved behind it, at the bar its font
    size earns. Reports the worst genuine failure of each criterion, with the measured
    ratio as evidence. Glyphs whose background structure can't resolve are not judged here
    (`pdf_text_over_image_checks` owns that lane) — a real measurement or nothing (ADR
    0016). Never raises."""
    worst_aa = worst_aaa = None          # (ratio, text_hex, bg_hex, required)
    try:
        rows, pages_total, pages_read, pages_capped = _pdf_contrast_scan(path)
    except Exception:
        return []
    for _pi, ch, fg, bg in rows:
        if bg is None:
            continue
        ratio = _contrast_ratio(fg, bg)
        aa_req, aaa_req = _pdf_required_ratios(ch)
        if ratio < aa_req and (worst_aa is None or ratio < worst_aa[0]):
            worst_aa = (ratio, fg, bg, aa_req)
        if ratio < aaa_req and (worst_aaa is None or ratio < worst_aaa[0]):
            worst_aaa = (ratio, fg, bg, aaa_req)
    note = _pdf_char_cap_note(pages_total, pages_read, pages_capped)
    findings: list[dict] = []
    for worst, rule_id, wcag, severity in (
            (worst_aa, "PDF_LOW_CONTRAST_AA", "1.4.3 Contrast (Minimum)", "SERIOUS"),
            (worst_aaa, "PDF_LOW_CONTRAST_AAA", "1.4.6 Contrast (Enhanced)", "MODERATE")):
        if worst is None:
            continue
        ratio, fg, bg, req = worst
        f = _finding(rule_id, wcag, severity)
        f["detail"] = f"text #{fg} on #{bg} is {ratio:.2f}:1 (needs {req:g}:1)" + note
        f["evidence"] = {"method": "structural", "metric": "Contrast", "value": round(ratio, 2),
                         "required": req, "unit": ":1"}
        findings.append(f)
    return findings


def _pdf_recolor_for_all(fg: str, bgs: set[str], aa_req: float, aaa_req: float) -> str | None:
    """The ONE replacement for text colour `fg` that clears `aaa_req` — or failing that
    `aa_req` — on EVERY background in `bgs`. None when `fg` already clears AAA everywhere
    (nothing to fix) or when no candidate clears AA everywhere (abstain rather than damage:
    one colour used on both a light and a dark panel has no single right answer, and
    `min_contrast_recolor`'s black/white fallback is only guaranteed to reach 4.5:1)."""
    if not bgs or all(_contrast_ratio(fg, bg) >= aaa_req for bg in bgs):
        return None
    worst_bg = min(bgs, key=lambda b: _contrast_ratio(fg, b))
    for target in (aaa_req, aa_req):
        cand = min_contrast_recolor(fg, worst_bg, target)
        if all(_contrast_ratio(cand, bg) >= target for bg in bgs):
            return cand if cand != fg else None
    return None


def pdf_contrast_recolor_plan(src) -> dict[int, dict[str, str]]:
    """Per page index (0-based): declared text-colour hex → its replacement hex, for the
    deterministic 1.4.3/1.4.6 fixer (`remediate_pdf._fix_pdf_text_contrast`). Accepts PDF
    bytes or a path.

    Built from the SAME resolved background the detector measures, so the fixer can only
    move a colour it has proved fails, and only the way that colour's real background calls
    for — a dark cover wants LIGHTER text, not darker. A colour is absent from the plan, and
    so never touched, when it already clears AAA on every background it is painted on, when
    any of its glyphs sits over an image or straddles a fill edge (background unresolvable),
    or when no single replacement clears AA on all of them. Never raises."""
    groups: dict[int, dict[str, dict]] = {}
    try:
        rows, _pt, _pr, _pc = _pdf_contrast_scan(src)
    except Exception:
        return {}
    for pi, ch, fg, bg in rows:
        g = groups.setdefault(pi, {}).setdefault(
            fg, {"bgs": set(), "aa": 0.0, "aaa": 0.0, "blocked": False})
        if bg is None:
            g["blocked"] = True             # one unresolvable glyph disqualifies the colour
            continue
        g["bgs"].add(bg)
        aa, aaa = _pdf_required_ratios(ch)
        g["aa"], g["aaa"] = max(g["aa"], aa), max(g["aaa"], aaa)   # strictest bar in the group
    plan: dict[int, dict[str, str]] = {}
    for pi, colours in groups.items():
        page_plan = {fg: new for fg, g in colours.items()
                     if not g["blocked"]
                     and (new := _pdf_recolor_for_all(fg, g["bgs"], g["aa"], g["aaa"]))}
        if page_plan:
            plan[pi] = page_plan
    return plan


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
    pages_total = 0
    try:
        import pdfplumber
        with pdfplumber.open(str(path)) as pdf:
            pages_total = len(pdf.pages)
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
        "a reader's request for looser (1.5×) line spacing; verify the text stays legible"
        + _cap_note(pages_total, _MAX_PAGES_SPACING),
        evidence={"method": "structural", "metric": "Line spacing", "value": round(ratio, 2),
                  "required": 1.5, "unit": "×",
                  **({"pages_checked": _MAX_PAGES_SPACING, "pages_total": pages_total}
                     if pages_total > _MAX_PAGES_SPACING else {})})]


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
    pages_total = 0
    try:
        import pdfplumber
        with pdfplumber.open(str(path)) as pdf:
            pages_total = len(pdf.pages)
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
        "only way to tell a link from surrounding text; verify it's distinguishable without colour"
        + _cap_note(pages_total, _MAX_PAGES_SPACING))]


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


# xl/theme/theme1.xml's <a:clrScheme> lists dk1,lt1,dk2,lt2,accent1-6,hlink,folHlink in
# that XML order — but a cell's <color theme="N"/> index does NOT follow that order.
# SpreadsheetML swaps the first two pairs (a documented OOXML/Excel quirk, matched by
# openpyxl and SheetJS): index 0/1 are lt1/dk1, not dk1/lt1.
_XLSX_THEME_SLOT_ORDER = (
    "lt1", "dk1", "lt2", "dk2",
    "accent1", "accent2", "accent3", "accent4", "accent5", "accent6",
    "hlink", "folHlink",
)
_CLR_SCHEME = re.compile(r"<a:clrScheme\b[^>]*>(.*?)</a:clrScheme>", re.S)
_CLR_SLOT = re.compile(r"<a:(dk1|lt1|dk2|lt2|accent[1-6]|hlink|folHlink)>(.*?)</a:\1>", re.S)
_SRGB_CLR = re.compile(r'<a:srgbClr\s+val="([0-9A-Fa-f]{6})"')
_SYS_CLR = re.compile(r'<a:sysClr\b[^>]*\blastClr="([0-9A-Fa-f]{6})"')


def _parse_xlsx_theme(theme_xml: str) -> list[str | None]:
    """Returns the 12 theme colors in SpreadsheetML `theme=` index order
    (see _XLSX_THEME_SLOT_ORDER), or None per-slot if unresolvable."""
    scheme_m = _CLR_SCHEME.search(theme_xml)
    if not scheme_m:
        return [None] * 12
    slots: dict[str, str] = {}
    for name, body in _CLR_SLOT.findall(scheme_m.group(1)):
        m = _SRGB_CLR.search(body) or _SYS_CLR.search(body)
        if m:
            slots[name] = m.group(1).upper()
    return [slots.get(name) for name in _XLSX_THEME_SLOT_ORDER]


def _apply_xlsx_tint(hexcolor: str, tint: float) -> str:
    """SpreadsheetML tint (ECMA-376 §18.8.3): a float in [-1.0, 1.0] applied to the
    HSL Lightness channel — negative darkens toward black, positive lightens toward
    white. This is NOT the same formula as DOCX's themeTint/themeShade byte-fraction
    math; reusing that formula here would produce a wrong ratio, not just a missing one."""
    import colorsys
    if tint == 0:
        return hexcolor
    r, g, b = (int(hexcolor[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    l = l * (1.0 + tint) if tint < 0 else l * (1.0 - tint) + tint
    l = max(0.0, min(1.0, l))
    rr, gg, bb = colorsys.hls_to_rgb(h, l, s)
    return f"{round(rr * 255):02X}{round(gg * 255):02X}{round(bb * 255):02X}"


def _theme_rgb(color_attrs: str, theme_colors: list[str | None]) -> str | None:
    """Resolves <color theme="N" tint="F"/> (or <fgColor theme=.../>) through the
    workbook's theme colour scheme. None if the theme index is out of range or that
    slot itself didn't resolve (e.g. an unrecognised sysClr) — unresolvable stays
    unresolvable, never guessed at."""
    theme_m = re.search(r'theme="(\d+)"', color_attrs)
    if not theme_m:
        return None
    idx = int(theme_m.group(1))
    if idx < 0 or idx >= len(theme_colors) or theme_colors[idx] is None:
        return None
    base = theme_colors[idx]
    tint_m = re.search(r'tint="(-?[\d.]+)"', color_attrs)
    if not tint_m:
        return base
    try:
        return _apply_xlsx_tint(base, float(tint_m.group(1)))
    except ValueError:
        return base


def _explicit_rgb(color_attrs: str) -> str | None:
    """Only <color rgb="XXXXXXXX"/> (or <fgColor rgb=.../>) resolves — indexed=
    colors return None (unresolvable), matching the module-level stance: guessing
    at an indexed color is exactly the false-positive risk (flagging routine
    header/table styling) this check must avoid. theme= colors are resolved
    separately via _theme_rgb, given they're now safe to resolve deterministically."""
    m = re.search(r'rgb="([0-9A-Fa-f]{6,8})"', color_attrs)
    return m.group(1)[-6:].upper() if m else None


def _xlsx_font_color(font_xml: str, theme_colors: list[str | None] | None = None) -> str | None:
    m = re.search(r"<color\b([^/]*)/>", font_xml)
    if not m:
        return None
    return _explicit_rgb(m.group(1)) or (_theme_rgb(m.group(1), theme_colors) if theme_colors else None)


def _xlsx_fill_color(fill_xml: str, theme_colors: list[str | None] | None = None) -> str | None:
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
    if not fg_m:
        return None
    return _explicit_rgb(fg_m.group(1)) or (_theme_rgb(fg_m.group(1), theme_colors) if theme_colors else None)


def xlsx_contrast_checks(path: Path) -> list[dict]:
    """1.4.3 / 1.4.6 Contrast — see module docstring for the deliberately
    narrow resolution scope (direct RGB only; theme/indexed/patterned fills
    are skipped, not guessed at). Uses the true WCAG relative-luminance ratio
    (_contrast_ratio, the same function pptx_contrast_checks already uses),
    not a luma-difference proxy — a cell can have a large luma gap and still
    fail the ratio (or vice versa), so the proxy could both over- and
    under-flag relative to the real thresholds."""
    findings: list[dict] = []
    try:
        with zipfile.ZipFile(path) as zf:
            styles = _read(zf, "xl/styles.xml")
            if not styles:
                return []
            theme_xml = _read(zf, "xl/theme/theme1.xml")
            theme_colors = _parse_xlsx_theme(theme_xml) if theme_xml else [None] * 12
            fonts = [_xlsx_font_color(m, theme_colors) for m in _FONT_BLOCK.findall(_container(_FONTS_CONTAINER, styles))]
            fills = [_xlsx_fill_color(m, theme_colors) for m in _FILL_BLOCK.findall(_container(_FILLS_CONTAINER, styles))]

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
                    f6, b6 = colors[0][-6:], colors[1][-6:]
                    ratio = _contrast_ratio(f6, b6)
                    if ratio < 7.0:
                        seen_aaa = True
                    if ratio < 4.5:
                        seen_aa = True
                    if ratio < 7.0 and (worst is None or ratio < worst[0]):
                        worst = (ratio, f6, b6)
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
# 4.1.2 and 2.4.3 for PDF moved to api/formats/pdf/ when they became the first pairs behind
# the capability registry (see api/rule_registry.py). They were the two whose coverage this
# module could not express: both detectors ran on every PDF, but neither pair was declared in
# store.RULE_FORMATS or REVIEW_FORMATS, so a clean scan reported NOT_EVALUATED — "we did not
# look" — for work that had in fact been done. Coverage lives in the registration now.
#
# These wrappers stay because `checks_for` below, `remediate_pdf`, and their existing tests all
# call them by these names. They are a thin forward, not a second implementation.
def _pdf_page_has_widget(page, pikepdf) -> bool:
    from formats.pdf.acroform import page_has_widget
    return page_has_widget(page, pikepdf)


def pdf_form_field_checks(path: Path) -> list[dict]:
    """4.1.2 findings per interactive form field. Implementation: formats/pdf/detectors/
    name_role_value.py — registered as PARTIAL coverage (AcroForm fields only)."""
    from formats.pdf.detectors.name_role_value import detect
    return detect(path)


def pdf_focus_order_checks(path: Path) -> list[dict]:
    """2.4.3 Focus Order for PDF. Implementation: formats/pdf/detectors/focus_order.py —
    registered as HEURISTIC coverage (/Tabs = /S is a proxy, not a proof)."""
    from formats.pdf.detectors.focus_order import detect
    return detect(path)


def pdf_non_text_content_checks(path: Path) -> list[dict]:
    """1.1.1 findings per tagged /Figure with no /Alt. Implementation: formats/pdf/detectors/
    non_text_content.py.

    RULE_FORMATS already lists pdf for 1.1.1 — the pass/fail lane was declared, and only the
    partner catalog's `pdf.missing-alt-text` implemented it. That left the in-process re-scan
    (proposals.verify_residual_scs, first-party checks only) unable to observe 1.1.1 on a PDF,
    so the write-back lane's credit gate cleared it on no evidence. This fills the declaration
    in rather than making a new claim."""
    from formats.pdf.detectors.non_text_content import detect
    return detect(path)


def office_non_text_content_checks(path: Path, ext: str) -> list[dict]:
    """1.1.1 findings per docx/pptx/xlsx image with no usable alt text. Implementations:
    formats/<fmt>/detectors/non_text_content.py, one per format (the rules index reads a
    detector's format from its path), over one shared walk in formats/office/images.py.

    Same shape as the PDF one above and for the same reason: RULE_FORMATS already lists all
    three formats for 1.1.1, but the only implementations were the partner catalog's
    DOCX-ALT-001 / PPTX-ALT-001 / XLSX-ALT-001. The in-process re-scan runs first-party checks
    only, so it could not observe 1.1.1 on an Office file, and the write-back lane's credit
    gate cleared it on no evidence."""
    fmt = ext.lower().lstrip(".")
    if fmt not in ("docx", "pptx", "xlsx"):
        return []
    import importlib
    mod = importlib.import_module(f"formats.{fmt}.detectors.non_text_content")
    return mod.detect(path)


# ── 3.1.2 Language of Parts — which passages already carry a language mark ────
# textchecks.detect_language_parts reads extracted TEXT and nothing else, so until this
# existed it could not tell a correctly-marked multilingual document from an unmarked one:
# it fired on both, could never certify a pass, and — the reason this was built — no write
# could ever clear it. apply_text_values writes w:lang on the runs of an approved passage
# and the criterion kept firing, so the value never earned credit.
_W_RUN_L = re.compile(r"<w:r\b[^>]*>.*?</w:r>", re.S)
_W_LANG_VAL = re.compile(r'<w:lang\b[^>]*\bw:val="([^"]+)"')
_A_RUN_L = re.compile(r"<a:r>.*?</a:r>", re.S)
_A_LANG_VAL = re.compile(r'<a:rPr\b[^>]*\blang="([^"]+)"')


def language_marked_spans(path: Path, ext: str) -> dict[str, str]:
    """{base language subtag: all text explicitly marked with it} for an Office file.

    Keyed by the BASE subtag ("fr" for fr-FR), because 3.1.2 asks that a passage's language
    be identified, not that a region be. Never raises; {} for a format with no per-run
    language mechanism.

    Keyed by language rather than returned as one "is marked" flag on purpose. PowerPoint
    stamps `lang="en-US"` on essentially every run it writes, and Word does the same through
    docDefaults, so "this run carries a language mark" is near-universal and proves nothing.
    What 3.1.2 actually asks is whether the passage is marked as the language it IS — so the
    caller matches a passage's DETECTED language against the text marked with that language,
    and a document full of default en-US marks still fails for its unmarked French.

    xlsx is absent by construction, not by omission: SpreadsheetML's rich-text run properties
    (CT_RPrElt) have no language element at all — verified against the schema — so there is
    nowhere in the format to record this and no write can ever clear 3.1.2 there. PDF would
    need a /Lang walk of the structure tree and is not built, so PDF behaviour is unchanged.
    """
    fmt = (ext or "").lower().lstrip(".")
    out: dict[str, list[str]] = {}

    def _collect(xml: str, run_re, lang_re, text_re) -> None:
        for rm in run_re.finditer(xml):
            run = rm.group(0)
            lm = lang_re.search(run)
            if not lm:
                continue
            base = lm.group(1).split("-")[0].strip().lower()
            text = "".join(text_re.findall(run)).strip()
            if base and text:
                out.setdefault(base, []).append(text)

    try:
        with zipfile.ZipFile(path) as zf:
            if fmt == "docx":
                # document.xml AND the running header/footer and foot/endnote parts — the same
                # set pii.extract_text flattens into the text 3.1.2 judges. Read from the body
                # alone, a foreign passage correctly marked with w:lang in a header appears in that
                # text as unexplained foreign words while its mark is invisible here, and 3.1.2
                # fires on a passage the document DID identify. Symmetry with extract_text is the
                # invariant: a language mark must be read wherever the text it marks is read.
                _collect(_read(zf, "word/document.xml") or "", _W_RUN_L, _W_LANG_VAL, _WT)
                for n in zf.namelist():
                    if _DOCX_STORY_PART.match(n):
                        _collect(_read(zf, n) or "", _W_RUN_L, _W_LANG_VAL, _WT)
            elif fmt == "pptx":
                for n in zf.namelist():
                    if re.fullmatch(r"ppt/slides/slide\d+\.xml", n):
                        _collect(_read(zf, n) or "", _A_RUN_L, _A_LANG_VAL, _AT)
    except Exception:
        return {}
    return {k: " ".join(v) for k, v in out.items()}


def checks_for(path: Path, ext: str) -> list[dict]:
    """Dispatch by extension; returns [] for formats with no structural check yet."""
    ext = ext.lower()
    if ext == ".docx":
        return (docx_checks(path) + office_control_review_checks(path, ext)
                + office_color_only_checks(path, ext)
                + office_reflow_checks(path, ext) + office_text_spacing_checks(path, ext)
                + docx_nontext_contrast_checks(path) + office_non_text_content_checks(path, ext))
    if ext == ".pptx":
        return (pptx_checks(path) + pptx_contrast_checks(path) + pptx_audio_autoplay_checks(path)
                + office_control_review_checks(path, ext)
                + pptx_focus_order_checks(path) + pptx_nontext_contrast_checks(path)
                + office_reflow_checks(path, ext) + office_text_spacing_checks(path, ext)
                + pptx_resize_text_checks(path) + pptx_complex_bg_contrast_checks(path)
                + office_non_text_content_checks(path, ext))
    if ext == ".pdf":
        return (pdf_contrast_checks(path) + pdf_bypass_blocks_check(path) + pdf_form_field_checks(path)
                + pdf_headings_labels_check(path) + pdf_link_purpose_check(path)
                + pdf_text_spacing_checks(path) + pdf_use_of_color_checks(path)
                + pdf_nontext_contrast_checks(path) + pdf_text_over_image_checks(path)
                + pdf_focus_order_checks(path) + pdf_scanned_page_checks(path)
                + pdf_non_text_content_checks(path))
    if ext == ".xlsx":
        return (xlsx_contrast_checks(path) + xlsx_structure_checks(path)
                + office_control_review_checks(path, ext) + office_color_only_checks(path, ext)
                + xlsx_nontext_contrast_checks(path) + office_non_text_content_checks(path, ext))
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
                # Body AND the running header/footer and foot/endnote parts: a clinical form puts a
                # Patient-ID or date field in a running header, and a control there is as
                # interactive — and as trap-prone — as one in the body. _docx_story_xmls is the same
                # part set link purpose, language of parts and use-of-color read.
                cc = 0
                ff = 0
                for xml in _docx_story_xmls(zf):
                    # Only genuine INPUT content controls (checkbox/date/dropdown/combo/
                    # picture) — the same input-type gate the 3.3.2 detector uses, so
                    # non-interactive template placeholders (w:text/w:richText) don't count.
                    for sdt_inner in _SDT.findall(xml):
                        pr_m = _SDT_PR.search(sdt_inner)
                        if pr_m and _SDT_INPUT_TYPE.search(pr_m.group(1)):
                            cc += 1
                    ff += len(_FFDATA.findall(xml))
                if cc:
                    counts["interactive content control"] = cc
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


# Control kinds a PRECISE first-party check already judges for 4.1.2, per format. The advisory
# below must not also claim uncertainty about these, or the criterion could never resolve:
# docx_checks reads w:alias on every input content control and knows exactly whether each is
# named, so a document whose only controls are content controls has a real 4.1.2 verdict.
_NAME_ROLE_PROVEN = {".docx": {"interactive content control"}}


def office_control_review_checks(path: Path, ext: str) -> list[dict]:
    """REVIEW findings for 2.1.2 + 4.1.2 when a document embeds interactive controls
    (ADR 0023). Advisory only — carries the concrete control evidence, never a pass,
    never a fix. Emits nothing (→ the criteria stay N/A) for a static document."""
    controls = office_interactive_controls(path, ext)
    if not controls:
        return []
    phrase = _controls_phrase(controls)
    out = [_review_finding(
        "OFFICE_INTERACTIVE_CONTROL_KEYBOARD", "2.1.2 No Keyboard Trap",
        f"document embeds {phrase} — verify keyboard focus can move away from every "
        "control (no keyboard trap); ACP can't confirm this statically")]

    # 4.1.2 is claimed only for control kinds nothing can judge statically — an arbitrary
    # ActiveX or OLE control, whose name and role live in code we never see. Content controls
    # are NOT such a kind any more: their accessible name is w:alias, right there in the XML.
    #
    # Emitting it for them anyway is not merely noisy, it is self-defeating. A REVIEW finding
    # still names its SC, so the residual re-scan that grants remediation credit would see
    # 4.1.2 unresolved no matter how many field names a reviewer approved, and a correctly
    # named document could never certify a pass. The advisory would permanently outvote the
    # precise check that replaced it.
    proven = _NAME_ROLE_PROVEN.get((ext or "").lower(), set())
    unproven = [c for c in controls if c["type"] not in proven]
    if unproven:
        out.append(_review_finding(
            "OFFICE_INTERACTIVE_CONTROL_NAME_ROLE", "4.1.2 Name, Role, Value",
            f"document embeds {_controls_phrase(unproven)} — verify each control exposes an "
            "accessible name and role to assistive technology; ACP can't confirm this statically"))
    return out


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
                        "it isn't lost for colour-blind or screen-reader users",
                        # A count, with no threshold to compare it against: 1.4.1 has no "how
                        # many is too many", one colour-only rule is already the barrier. Carried
                        # anyway so the card states HOW MUCH there is to check without the
                        # reviewer re-counting (same shape as the scanned-pages evidence above).
                        evidence={"method": "structural", "metric": "Colour-only rules",
                                  "value": cf}))
            if ext == ".docx":
                doc = _read(zf, "word/document.xml") or ""
                colour_only = sum(1 for _rid, inner in _HYPERLINK.findall(doc) if _W_U_NONE.search(inner))
                if colour_only:
                    findings.append(_review_finding(
                        "DOCX_COLOR_ONLY_LINK", "1.4.1 Use of Color",
                        f"{colour_only} hyperlink(s) have their underline removed — a link set apart "
                        "from body text by colour alone fails for colour-blind users; verify each "
                        "link is identifiable without relying on colour",
                        evidence={"method": "structural", "metric": "Colour-only links",
                                  "value": colour_only}))
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
        "shape conveys meaning, its boundary may be too faint to see; verify it isn't decorative",
        evidence={"method": "structural", "metric": "Contrast", "value": round(ratio, 2),
                  "required": 3.0, "unit": ":1"})]


def docx_nontext_contrast_checks(path: Path) -> list[dict]:
    """1.4.11 Non-text Contrast (Review) for docx — the lowest-contrast solid outline-on-fill
    DrawingML shape (<3:1). Word's shapes carry the SAME `<a:ln>` outline + `<a:solidFill>` under
    `<wps:spPr>` as pptx, so this mirrors `pptx_nontext_contrast_checks`.

    Reads the body AND the running header/footer and foot/endnote parts: a banner shape or a rule
    line drawn into a page header — a very common home for exactly those graphics — has the same
    faint boundary and the same 1.4.11 question, but a scan of word/document.xml alone said nothing
    about it. That is the same header/footer blind spot #214/#226/#227/#229 closed for other
    content checks, and `_docx_story_xmls` is the one name for that set of parts so these checks
    cannot drift apart on which parts count. Only the single WORST shape is reported, so widening
    the scan surfaces a faint header shape — it never multiplies findings. Never raises."""
    worst = None      # (ratio, border_hex, fill_hex)
    try:
        with zipfile.ZipFile(path) as zf:
            for xml in _docx_story_xmls(zf):
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
        "shape conveys meaning, its boundary may be too faint to see; verify it isn't decorative",
        evidence={"method": "structural", "metric": "Contrast", "value": round(ratio, 2),
                  "required": 3.0, "unit": ":1"})]


# xlsx shapes live in xl/drawings/drawingN.xml under the spreadsheetDrawing namespace (<xdr:sp>),
# but Excel is inconsistent about prefixing the inner shape-properties element — some files write
# <xdr:spPr>, others the bare <spPr> — so this tolerates both, unlike docx/pptx's single fixed
# namespace. The <a:ln>/<a:solidFill> content inside is the same DrawingML as docx/pptx either way.
_XDR_SPPR = re.compile(r"<(?:xdr:)?spPr\b.*?</(?:xdr:)?spPr>", re.S)


def xlsx_nontext_contrast_checks(path: Path) -> list[dict]:
    """1.4.11 Non-text Contrast (Review) for xlsx — the lowest-contrast solid outline-on-fill
    DrawingML shape (<3:1) across every worksheet's drawing part. Mirrors
    docx_nontext_contrast_checks/pptx_nontext_contrast_checks; only the drawing-part glob and the
    shape-properties element's namespace tolerance differ. Never raises."""
    worst = None      # (ratio, border_hex, fill_hex)
    try:
        with zipfile.ZipFile(path) as zf:
            for drawing_name in sorted(n for n in zf.namelist()
                                        if re.fullmatch(r"xl/drawings/drawing\d+\.xml", n)):
                xml = _read(zf, drawing_name)
                if not xml:
                    continue
                for sppr in _XDR_SPPR.findall(xml):
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
        "XLSX_NONTEXT_LOW_CONTRAST", "1.4.11 Non-text Contrast",
        f"a shape outline #{border_hex} on its #{fill_hex} fill is {ratio:.1f}:1 (needs 3:1) — if the "
        "shape conveys meaning, its boundary may be too faint to see; verify it isn't decorative",
        evidence={"method": "structural", "metric": "Contrast", "value": round(ratio, 2),
                  "required": 3.0, "unit": ":1"})]


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
                ev = ({"method": "structural", "metric": "Narrowest column",
                       "value": round(frac * 100), "unit": "%"} if frac is not None else None)
                findings.append(_review_finding("OFFICE_WIDE_TABLE_REFLOW", "1.4.10 Reflow", detail,
                                                evidence=ev))
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
                ev = ({"method": "structural", "metric": "Line spacing", "value": round(ratio, 2),
                       "required": 1.5, "unit": "×"} if ratio is not None else None)
                findings.append(_review_finding("OFFICE_EXACT_LINE_SPACING", "1.4.12 Text Spacing", detail,
                                                evidence=ev))
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
