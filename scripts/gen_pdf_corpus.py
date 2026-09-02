#!/usr/bin/env python3
"""A LABELLED .pdf corpus — the fourth and last format to get ground truth.

WHY THIS EXISTS. `scripts/gen_fixture_coverage.py` reports coverage per (criterion, format)
pair; pdf sat at 0 of 15 because no labelled corpus existed. This declares ELEVEN of them, and
completes the sweep begun with .docx: every format ACP scans now has ground truth.

THE RULE THAT MAKES THE NUMBER MEAN SOMETHING: a pair is declared only when a detector that
runs WHEREVER THE SUITE RUNS was driven against the fixture and confirmed to fire, with an
adversarial counterpart confirmed to stay silent. Coverage is counted from declarations, so a
fixture whose seeded violation nobody has confirmed is caught would raise the number without
raising what the number measures.

    1.1.1   a tagged /Figure with no /Alt            pdf_non_text_content_checks
    1.4.1   a coloured link with no underline        pdf_use_of_color_checks
    1.4.3   grey text on an explicit white ground    pdf_contrast_checks
    1.4.11  a faint rect outline on its own fill     pdf_nontext_contrast_checks
    2.4.2   no /Title in the info dictionary         analysers…pdf.document_title
    2.4.3   form widgets on a page without /Tabs /S  pdf_focus_order_checks
    2.4.4   a vague link label ("Click here")        pdf_link_purpose_check
    2.4.6   a tagged 6-page file with no heading     pdf_headings_labels_check
    3.1.1   no /Lang in the document catalog         analysers…pdf.document_language
    1.3.3   a sensory-only instruction, as prose     textchecks.detect_sensory
    4.1.2   an AcroForm field with no /TU            pdf_form_field_checks

TWO CODE PATHS, ONE AVAILABILITY STORY. The first eight run through
`office_structure.checks_for`; 2.4.2 and 3.1.1 are catalog rules in
`engine/pdf-analyser/analysers/rules/pdf/`. The xlsx and pptx corpora phrased their rule as
"first-party, no partner engine", and applying that phrasing here was a MISTAKE this file made
in its first draft: it listed 2.4.2 and 3.1.1 among criteria needing "tag-tree semantics or
langdetect", when each is one pikepdf dictionary lookup in a tree vendored in-repo since ADR
0029. The property that actually matters is whether a detector runs everywhere the suite runs,
not which directory it lives in — for PDF, both paths do. `scripts/check_engines.py` reports
office and ocr unavailable in a bare container and pdf available.

Those two are also the most valuable pairs here: both sit in the ASSESSMENT AUTO lane at
ceiling C, so a clean result CERTIFIES the document. They were two of the ten
certification-capable pairs in the whole preset with nothing verifying them.

The four not here: 1.4.5 needs tesseract, 3.1.2 needs langdetect, and 1.3.1/1.3.2 have
vendored rules (pdf.tagged, pdf.table-headers, pdf.reading-order) that are reachable and
simply not yet fixtured. 1.3.3 WAS on this list and is now declared: it is a text predicate
with no engine behind it, which reading the list rather than testing it had obscured.

THREE DETECTOR SUBTLETIES, each of which would silently cover nothing if a fixture ignored it:

  * 1.4.3 measures a glyph against the background STRUCTURALLY RESOLVED behind it — and, unlike
    pptx, an unpainted page is NOT an abstention: `_pdf_char_background` falls through to
    `_PDF_DEFAULT_BG` ("FFFFFF"), so a bare page is measured against white. The trap that cost
    the pptx contrast fixture its first draft does NOT transfer here; this was established by
    removing the fixture's background rect and watching the finding stay put, not by reading
    across from pptx. The fixture paints the rect anyway so that what it measures against is
    stated in the fixture rather than inherited from a constant that could change.
    PDF's real abstentions are elsewhere: a glyph over an IMAGE (pixels, not structure — that
    is pdf_text_over_image_checks' lane) and a glyph straddling a fill's edge.
  * 1.4.11 measures only rects declaring BOTH a stroke and a fill. A stroked-but-unfilled rect
    is skipped by design (ADR 0016: a real measurement or nothing).
  * 2.4.6 applies a five-page floor — a one-page memo legitimately needs no headings — so its
    fixtures are six pages. But 2.4.1 applies the SAME floor to a file with an empty outline,
    so six blank pages raise 2.4.1 as well; the fixtures therefore carry a bookmark to stay
    single-criterion.

The one place that isolation is not achievable: the 1.4.3 violation also raises 1.4.6, because
one measurement (~1.9:1) fails the AA and AAA bars at once and one detector emits both. Neither
1.4.6 nor 2.4.1 is in the preset, so neither affects the coverage count either way.

ONE CRITERION AT A TIME IS LOAD-BEARING HERE, and PDF makes it harder than Office did: the
1.4.1 and 2.4.4 detectors both read the same hyperlink. The fixtures are built so each trips
exactly one — the 1.4.1 link has a DESCRIPTIVE label with its underline suppressed, and the
2.4.4 link is UNDERLINED with a vague label. Swap either and one fixture would quietly be
measuring two things at once. test_pdf_corpus.py asserts both separations directly.

Run:
    python scripts/gen_pdf_corpus.py --out ~/Downloads/acp-pdf-eval/sc-corpus
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))
sys.path.insert(0, str(ROOT / "scripts"))

import corpus_expectations as ce  # noqa: E402

FMT = "pdf"

INK = "#1A1F26"      # ~15:1 on white
FAINT = "#C8C8C8"    # ~1.7:1 on white — under even the 3:1 non-text bar
GREY = "#BBBBBB"     # ~1.9:1 on white — a real 1.4.3 AA failure at any size
PAPER = "#FFFFFF"
LINK_URL = "https://example.org/accessibility-policy"

_PAGE = (400, 220)
_MIN_PAGES = 6       # clears the five-page floor pdf_headings_labels_check applies

# Stamped onto EVERY fixture that is not deliberately testing their absence. Without this each
# fixture would also raise 2.4.2 (no /Title) and 3.1.1 (no /Lang), because a pikepdf-authored or
# reportlab-authored PDF carries neither by default — so every fixture in the corpus would be a
# three-criterion fixture and none of the per-criterion counts would mean anything.
DOC_TITLE = "Q3 regional accessibility report"
DOC_LANG = "en-GB"


# ── reportlab-drawn fixtures (content: text, links, rects) ───────────────────────

def _canvas(path: Path):
    from reportlab.pdfgen import canvas
    return canvas.Canvas(str(path), pagesize=_PAGE)


def _link(path: Path, text: str, colour: str, underline: bool) -> None:
    """One page, one hyperlink. Label and underline are the only knobs, because 1.4.1 is about
    the CUE and 2.4.4 is about the LABEL, and each fixture must move exactly one."""
    from reportlab.lib.colors import HexColor
    c = _canvas(path)
    c.setFont("Helvetica", 14)
    c.setFillColor(HexColor(colour))
    c.drawString(50, 120, text)
    w = c.stringWidth(text, "Helvetica", 14)
    if underline:
        c.setStrokeColor(HexColor(colour))
        c.setLineWidth(1)
        c.line(50, 117, 50 + w, 117)
    c.linkURL(LINK_URL, (50, 116, 50 + w, 136), relative=0)
    c.save()


def f_link_colour_only(path: Path):
    # Label is deliberately DESCRIPTIVE so 2.4.4 stays quiet and only the missing cue trips.
    _link(path, "the accessibility policy", "#0000EE", underline=False)
    return ({"1.4.1": "FAIL"},
            "a link set apart only by its colour — no underline or other non-colour cue")


def f_link_underlined_ok(path: Path):
    _link(path, "the accessibility policy", "#0000EE", underline=True)
    return ({"1.4.1": "REVIEW"},
            "the same link, same colour, WITH an underline — must not be flagged (adversarial)")


def f_link_vague(path: Path):
    # Underlined, so the 1.4.1 detector stays quiet and only the label trips 2.4.4.
    _link(path, "Click here", "#0000EE", underline=True)
    return ({"2.4.4": "FAIL"},
            "an underlined link labelled 'Click here' — the label names nothing about where it goes")


def f_link_descriptive_ok(path: Path):
    _link(path, "the accessibility policy", "#0000EE", underline=True)
    return ({"2.4.4": "REVIEW"},
            "the same link with a label that names its destination (adversarial)")


def _text_on_ground(path: Path, fg: str) -> None:
    """Text over an explicit white rect. The rect is NOT what makes the detector fire — an
    unpainted page resolves to `_PDF_DEFAULT_BG` and is measured just the same (verified by
    removing it). It is here so the ground being measured against is visible in the fixture
    instead of inherited from a constant in the detector."""
    from reportlab.lib.colors import HexColor
    c = _canvas(path)
    c.setFillColor(HexColor(PAPER))
    c.rect(0, 0, _PAGE[0], _PAGE[1], stroke=0, fill=1)
    c.setFillColor(HexColor(fg))
    c.setFont("Helvetica", 12)
    c.drawString(50, 120, "Quarterly compliance summary")
    c.save()


def f_contrast_fail(path: Path):
    _text_on_ground(path, GREY)
    return ({"1.4.3": "FAIL"},
            f"12pt {GREY} text on an explicit {PAPER} ground — ~1.9:1, needs 4.5:1")


def f_contrast_ok(path: Path):
    _text_on_ground(path, INK)
    return {"1.4.3": "PASS"}, f"the same text and ground at {INK} — ~15:1 (adversarial)"


def _rect(path: Path, border: str) -> None:
    from reportlab.lib.colors import HexColor
    c = _canvas(path)
    c.setFillColor(HexColor(PAPER))
    c.setStrokeColor(HexColor(border))
    c.setLineWidth(2)
    c.rect(40, 60, 300, 100, stroke=1, fill=1)   # BOTH stroke and fill — the detector needs both
    c.save()


def f_rect_faint_outline(path: Path):
    _rect(path, FAINT)
    return ({"1.4.11": "FAIL"},
            f"a {FAINT} outline on its own {PAPER} fill — ~1.7:1, needs 3:1")


def f_rect_strong_outline_ok(path: Path):
    _rect(path, INK)
    return {"1.4.11": "REVIEW"}, f"the same rect outlined {INK} — ~15:1 (adversarial)"


# ── pikepdf-built fixtures (structure: tag tree, AcroForm) ───────────────────────

def _blank(pages: int = 1):
    from pikepdf import Pdf
    pdf = Pdf.new()
    for _ in range(pages):
        pdf.add_blank_page(page_size=_PAGE)
    return pdf


def _tag_tree(pdf, kids) -> None:
    """Attach `kids` under a /Document element beneath /StructTreeRoot, with the /P back-links a
    conforming tag tree carries."""
    from pikepdf import Array, Dictionary, Name
    doc = pdf.make_indirect(Dictionary(Type=Name.StructElem, S=Name.Document, K=Array(kids)))
    for k in kids:
        k.P = doc
    root = pdf.make_indirect(Dictionary(Type=Name.StructTreeRoot, K=Array([doc])))
    doc.P = root
    pdf.Root.StructTreeRoot = root
    pdf.Root.MarkInfo = Dictionary(Marked=True)


def _figure(path: Path, alt: str | None) -> None:
    from pikepdf import Dictionary, Name, String
    pdf = _blank()
    fig = Dictionary(Type=Name.StructElem, S=Name.Figure, Pg=pdf.pages[0].obj)
    if alt is not None:
        fig.Alt = String(alt)
    fig = pdf.make_indirect(fig)
    _tag_tree(pdf, [fig])
    pdf.save(str(path))


def f_figure_no_alt(path: Path):
    _figure(path, None)
    return ({"1.1.1": "FAIL"},
            "a tagged /Figure with no /Alt — a screen reader announces nothing for it")


def f_figure_with_alt_ok(path: Path):
    _figure(path, "A bar chart of quarterly revenue by region")
    return {"1.1.1": "REVIEW"}, "the same figure carrying an /Alt (adversarial)"


def _headings(path: Path, with_heading: bool) -> None:
    """Six pages so the file clears pdf_headings_labels_check's five-page floor — and, for the
    same reason, a bookmark tree, because pdf_bypass_blocks_check applies that same floor to a
    file with an empty outline. Without the bookmarks BOTH of these fixtures also raise 2.4.1,
    which does not confound the 2.4.6 comparison (it is constant across the pair) but does make
    them stop being single-criterion. Adding one outline entry is cheaper than explaining that.
    """
    from pikepdf import Dictionary, Name, OutlineItem
    pdf = _blank(_MIN_PAGES)
    pg = pdf.pages[0].obj
    kids = []
    if with_heading:
        kids.append(pdf.make_indirect(Dictionary(Type=Name.StructElem, S=Name.H1, Pg=pg)))
    kids.append(pdf.make_indirect(Dictionary(Type=Name.StructElem, S=Name.P, Pg=pg)))
    _tag_tree(pdf, kids)
    with pdf.open_outline() as outline:
        outline.root.append(OutlineItem("Section 1", 0))
    pdf.save(str(path))


def f_no_headings(path: Path):
    _headings(path, False)
    return ({"2.4.6": "FAIL"},
            f"a tagged {_MIN_PAGES}-page file whose tag tree holds no heading element — "
            "assistive tech has nothing to navigate by")


def f_headings_ok(path: Path):
    _headings(path, True)
    return {"2.4.6": "REVIEW"}, "the same file with an /H1 in the tree (adversarial)"


def _form(path: Path, named: bool, tabs_s: bool) -> None:
    from pikepdf import Array, Dictionary, Name, String
    pdf = _blank()
    page = pdf.pages[0]
    fld = Dictionary(Type=Name.Annot, Subtype=Name.Widget, FT=Name.Tx,
                     T=String("reference"), Rect=Array([50, 100, 250, 130]), V=String(""))
    if named:
        fld.TU = String("Reference number")
    fld = pdf.make_indirect(fld)
    page.obj.Annots = Array([fld])
    if tabs_s:
        page.obj.Tabs = Name.S
    pdf.Root.AcroForm = pdf.make_indirect(Dictionary(Fields=Array([fld])))
    pdf.save(str(path))


def f_field_no_name(path: Path):
    _form(path, named=False, tabs_s=True)
    return ({"4.1.2": "FAIL"},
            "an AcroForm text field with no /TU — AT has no accessible name to announce")


def f_field_named_ok(path: Path):
    _form(path, named=True, tabs_s=True)
    return {"4.1.2": "REVIEW"}, "the same field carrying /TU 'Reference number' (adversarial)"


def f_no_tabs_structure(path: Path):
    _form(path, named=True, tabs_s=False)
    return ({"2.4.3": "FAIL"},
            "a page carrying form widgets without /Tabs /S — tab order is not declared to "
            "follow the document's structure")


def f_tabs_structure_ok(path: Path):
    _form(path, named=True, tabs_s=True)
    return {"2.4.3": "REVIEW"}, "the same page with /Tabs /S set (adversarial)"


# ── the two catalog rules, run from the vendored analyser ───────────────────────
# 2.4.2 and 3.1.1 do NOT go through office_structure.checks_for — they are catalog rules
# implemented in engine/pdf-analyser/analysers/rules/pdf/. That is a different code path, not a
# different availability story: both are pure Python reading /Title and /Lang with pikepdf, and
# the analyser is vendored in-tree (ADR 0029), so they run wherever the suite runs. An earlier
# draft of this file listed both as unreachable "tag-tree semantics or langdetect" work; they
# are neither, and each is one dictionary lookup.
#
# These two matter more than their count suggests: both sit in the ASSESSMENT AUTO lane at
# ceiling C, meaning a clean result certifies the document. They were two of the ten
# certification-capable pairs with no ground-truth fixture behind them.

def f_no_document_title(path: Path):
    _blank().save(str(path))
    return {"2.4.2": "FAIL"}, "no /Title in the document info dictionary", {"title": None}


def f_document_title_ok(path: Path):
    _blank().save(str(path))
    return {"2.4.2": "PASS"}, f"/Title set to {DOC_TITLE!r} (adversarial)", {}


def f_no_document_language(path: Path):
    _blank().save(str(path))
    return {"3.1.1": "FAIL"}, "no /Lang in the document catalog", {"lang": None}


def f_document_language_ok(path: Path):
    _blank().save(str(path))
    return {"3.1.1": "PASS"}, f"/Lang set to {DOC_LANG!r} (adversarial)", {}


# ── 1.3.3 Sensory Characteristics — a TEXT criterion, not a structural one ──────
# Every other pair in this corpus is decided by reading the file's structure. 1.3.3 is decided by
# reading its PROSE: textchecks.detect_sensory looks for an instruction that identifies a control
# only by shape, colour or position. That makes it the one criterion here whose fixture is the
# same on all four formats — the words are the fixture, and the container is incidental.
#
# It also makes it reachable everywhere, which is why it is in DECLARED and not DECLARED_ENGINE:
# no analyser, no OCR, no langdetect. `content_findings` guards each sub-check separately, so
# 3.1.2 going quiet on a box without langdetect does not take 1.3.3 with it.

SENSORY_BAD = ("To continue, click the round green button on the right. "
               "See the box below for the payment terms.")
SENSORY_OK = ("To continue, choose Submit under Payment options. "
              "The payment terms are in the Payment terms section.")


def _prose(path: Path, body: str) -> None:
    from reportlab.lib.colors import HexColor
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(str(path), pagesize=(520, 200))
    c.setFillColor(HexColor(PAPER))
    c.rect(0, 0, 520, 200, stroke=0, fill=1)
    c.setFillColor(HexColor(INK))
    c.setFont("Helvetica", 11)
    # Split so the line box stays inside the page — extraction joins them back with a space.
    for i, chunk in enumerate(body.split(". ")):
        c.drawString(30, 140 - i * 20, chunk.strip().rstrip(".") + ".")
    c.save()


def f_sensory_instruction(path: Path):
    _prose(path, SENSORY_BAD)
    return ({"1.3.3": "FAIL"},
            "an instruction identifying a control only by shape, colour and position — "
            "unusable to a screen-reader or low-vision reader")


def f_sensory_instruction_ok(path: Path):
    _prose(path, SENSORY_OK)
    return ({"1.3.3": "REVIEW"},
            "the same instruction naming the control and the section (adversarial)")


# 1.3.1 on PDF is the tag tree itself: without /StructTreeRoot and /MarkInfo a screen reader has
# no headings, no reading order and no table semantics to read, whatever the page looks like. The
# prose is deliberately flat — no instruction, no link, no heading — so the only thing separating
# this pair is the tagging.
TAGGING_PROSE = ("Payment terms are agreed at the start of each billing period. "
                 "Invoices are issued monthly and settled within thirty days.")


def f_untagged_document(path: Path):
    _prose(path, TAGGING_PROSE)
    return ({"1.3.1": "FAIL"},
            "no structure tree and no /MarkInfo — assistive technology gets nothing but a bag "
            "of glyphs",
            {"tagged": False})


def f_tagged_document_ok(path: Path):
    _prose(path, TAGGING_PROSE)
    return ({"1.3.1": "REVIEW"},
            "the same page carrying /StructTreeRoot and /MarkInfo (adversarial). REVIEW, not "
            "PASS: a tag tree existing says nothing about whether the tags are CORRECT, which "
            "is a judgement no detector makes (ADR 0016)")



# ── 1.4.5 Images of Text — decided by OCR, not by the container ─────────────────
# Like 1.3.3, this criterion reads the DOCUMENT'S PIXELS rather than its structure: ocr.py runs
# tesseract over each embedded raster and flags any carrying >= ocr._MIN_WORDS (10) real words.
# The image is the fixture and the page is the container, so the wording is identical across
# the .xlsx, .pptx and .pdf corpora — see tests/test_images_of_text_corpus.py, which asserts that
# sameness so one detector change reads as one result in three places.
#
# THE ALT IS CORRECT ON PURPOSE, and that is what keeps the fixture single-criterion. 1.4.5 is
# alt-agnostic — `images_of_text` never looks at a descr — so an image of prose fails 1.4.5
# whether or not it is described. Leaving the alt off would fail 1.1.1 as well and the fixture
# would measure two things at once. (The .docx corpus's equivalent DOES declare both, which is
# correct there: gen_sc_corpus is scored by score_assessment rather than by the single-criterion
# sweep these three corpora use.)
#
# THE WORD FLOOR IS THE TRAP. _MIN_WORDS counts OCR'd TOKENS, not what was drawn — dates and
# phone numbers are not words. The .docx corpus hit this: three short lines recovered six words,
# so 1.4.9 (floor 3) fired and 1.4.5 (floor 10) did not, and the fixture read as an engine bug.
# Hence prose, and enough of it: this image OCRs to 29 words, with room for the odd merge
# ("begins on" comes back as "beginson").
IMAGE_OF_TEXT_PROSE = ("Open enrollment for the coming plan year",
                       "begins on the first of March and closes",
                       "on the last day of the same month. Call",
                       "the benefits office to change your plan.")
IMAGE_OF_TEXT_ALT = ("Open enrollment runs from 1 March to 31 March; call the benefits office "
                     "to change plan.")
# WCAG 1.4.5 exempts logotypes, and ocr._MIN_WORDS is what encodes that exemption here: two words
# is under the floor, so the control is clean for the same reason a real logo would be.
LOGO_TEXT = ("UT Health",)


def _text_png(lines, size=(900, 360)) -> bytes:
    """A PNG with real, OCR-legible text baked into it.

    Scaled up AFTER drawing because PIL's default bitmap font is too small for tesseract to read
    reliably at native size. An unreadable image-of-text fixture silently becomes a no-text
    fixture, and 1.4.5 then stops firing for a reason that has nothing to do with the detector —
    which is the failure mode a ground-truth corpus exists to make impossible."""
    import io
    from PIL import Image, ImageDraw
    im = Image.new("RGB", size, "white")
    d = ImageDraw.Draw(im)
    y = 20
    for line in lines:
        d.text((20, y), line, fill="black")
        y += 70
    im = im.resize((size[0] * 2, size[1] * 2), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def _text_png_file(lines, size=(900, 360)):
    import tempfile
    png = Path(tempfile.mkdtemp()) / "image-of-text.png"
    png.write_bytes(_text_png(lines, size))
    return png


def _page_with_image(path: Path, lines, size, heading: str) -> None:
    from reportlab.lib.colors import HexColor
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(str(path), pagesize=(520, 400))
    c.setFillColor(HexColor(PAPER))
    c.rect(0, 0, 520, 400, stroke=0, fill=1)
    c.setFillColor(HexColor(INK))
    c.setFont("Helvetica", 12)
    c.drawString(30, 370, heading)
    w, h = size
    draw_w = 460.0
    c.drawImage(ImageReader(str(_text_png_file(lines, size))), 30, 120,
                width=draw_w, height=draw_w * h / w)
    c.save()


def f_image_of_text(path: Path):
    _page_with_image(path, IMAGE_OF_TEXT_PROSE, (900, 360), "Enrollment notice")
    return ({"1.4.5": "FAIL"},
            "a page whose body is a picture of prose rather than real text — selectable by "
            "nobody, resizable by nobody, and searchable by nobody")


def f_image_of_text_logo_ok(path: Path):
    _page_with_image(path, LOGO_TEXT, (300, 100), "Enrollment notice")
    return ({"1.4.5": "REVIEW"},
            "a logotype on an otherwise ordinary page (adversarial). WCAG 1.4.5 exempts logos, "
            "so a finding here is a false positive")



# ── 3.1.2 Language of Parts — decided by the prose, like 1.3.3 ──────────────────
# textchecks.detect_language_parts reads EXTRACTED TEXT: it needs at least two segments of
# >= _MIN_SEG_WORDS (12) real words, in at least two confidently-detected languages, and it
# reports the passages whose language the document never identifies. The words are the fixture
# and the page is the container, so the wording is identical across the .xlsx, .pptx and
# .pdf corpora — see tests/test_language_parts_corpus.py.
#
# THE CONTROL IS MONOLINGUAL, NOT "THE SAME DOCUMENT WITH THE FRENCH MARKED", and on two of the
# three formats that is forced rather than chosen. office_structure.language_marked_spans returns
# {} for .xlsx and .pdf: SpreadsheetML's rich-text run properties have no language element at
# all, and PDF's /Lang structure-tree walk is not built. Marking is therefore unrepresentable
# there, and a "marked" fixture would fail 3.1.2 exactly like the violation — measured, not
# assumed. .pptx CAN carry the mark, so it gets a third fixture proving that a write clears the
# criterion; the other two would be asserting a capability the format does not have.
LANG_EN_BODY = (
    "The benefits office publishes a summary of every plan option before the enrollment window opens.",
    "Employees may change their elections at any point during the month without providing a reason.",
    "Questions about eligibility should be directed to the benefits office rather than to a manager.",
)
LANG_FR_PASSAGE = ("Le bureau des avantages sociaux publie chaque annee un resume complet de "
                   "toutes les options offertes aux employes de la region.")
# Same length and register as the French passage, so the control differs by LANGUAGE and nothing
# else — a shorter filler would fall under the 12-word floor and be skipped rather than judged.
LANG_EN_TAIL = ("Enrollment closes at the end of the month for every employee in every "
                "participating region.")


def _lang_page(path: Path, lines) -> None:
    from reportlab.lib.colors import HexColor
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(str(path), pagesize=(560, 400))
    c.setFillColor(HexColor(PAPER))
    c.rect(0, 0, 560, 400, stroke=0, fill=1)
    c.setFillColor(HexColor(INK))
    c.setFont("Helvetica", 9)
    y = 370
    for line in lines:
        words, buf = line.split(), ""
        for w in words:
            if len(buf) + len(w) > 85:
                c.drawString(30, y, buf)
                y -= 14
                buf = w
            else:
                buf = (buf + " " + w).strip()
        c.drawString(30, y, buf)
        y -= 22
    c.save()


def f_language_parts(path: Path):
    _lang_page(path, list(LANG_EN_BODY) + [LANG_FR_PASSAGE])
    return ({"3.1.2": "FAIL"},
            "an English page with an unmarked French paragraph — a screen reader pronounces it "
            "with English phonetics and it is unintelligible")


def f_language_parts_ok(path: Path):
    _lang_page(path, list(LANG_EN_BODY) + [LANG_EN_TAIL])
    return ({"3.1.2": "REVIEW"},
            "the same page entirely in one language (adversarial). Monolingual rather than "
            "marked because PDF's /Lang structure-tree walk is not built, so there is nowhere "
            "a mark could be read from")


FIXTURES = [
    ("untagged-document",       f_untagged_document,       "violation"),
    ("tagged-document-ok",      f_tagged_document_ok,      "adversarial"),
    ("sensory-instruction",     f_sensory_instruction,     "violation"),
    ("sensory-instruction-ok",  f_sensory_instruction_ok,  "adversarial"),
    ("no-document-title",       f_no_document_title,       "violation"),
    ("document-title-ok",       f_document_title_ok,       "adversarial"),
    ("no-document-language",    f_no_document_language,    "violation"),
    ("document-language-ok",    f_document_language_ok,    "adversarial"),
    ("figure-no-alt",           f_figure_no_alt,           "violation"),
    ("image-of-text",           f_image_of_text,           "violation"),
    ("image-of-text-logo-ok",   f_image_of_text_logo_ok,   "adversarial"),
    ("language-parts",          f_language_parts,          "violation"),
    ("language-parts-ok",       f_language_parts_ok,       "adversarial"),
    ("figure-with-alt-ok",      f_figure_with_alt_ok,      "adversarial"),
    ("link-colour-only",        f_link_colour_only,        "violation"),
    ("link-underlined-ok",      f_link_underlined_ok,      "adversarial"),
    ("contrast-fail",           f_contrast_fail,           "violation"),
    ("contrast-ok",             f_contrast_ok,             "adversarial"),
    ("rect-faint-outline",      f_rect_faint_outline,      "violation"),
    ("rect-strong-outline-ok",  f_rect_strong_outline_ok,  "adversarial"),
    ("no-tabs-structure",       f_no_tabs_structure,       "violation"),
    ("tabs-structure-ok",       f_tabs_structure_ok,       "adversarial"),
    ("link-vague",              f_link_vague,              "violation"),
    ("link-descriptive-ok",     f_link_descriptive_ok,     "adversarial"),
    ("no-headings",             f_no_headings,             "violation"),
    ("headings-ok",             f_headings_ok,             "adversarial"),
    ("field-no-name",           f_field_no_name,           "violation"),
    ("field-named-ok",          f_field_named_ok,          "adversarial"),
]

DECLARED = ("1.1.1", "1.3.1", "1.3.3", "1.4.1", "1.4.11", "1.4.3", "1.4.5", "2.4.2",
            "2.4.3", "2.4.4", "2.4.6", "3.1.1", "3.1.2", "4.1.2")


def _stamp(path: Path, title: str | None, lang: str | None,
           display_title: bool = True, tagged: bool = True) -> None:
    """Give a built fixture the four document-wide properties every accessible PDF carries — or
    deliberately withhold the one it is testing the absence of.

    Applied to EVERY fixture rather than left to each builder, because the failure mode of
    forgetting is silent: the fixture simply grows a second and third finding and the corpus
    stops being per-criterion without anything going red.

    THAT IS NOT A HYPOTHETICAL — it is what happened, and it is why `tagged` and `display_title`
    are here at all. When this corpus landed, `_stamp` set only /Title and /Lang, and the corpus
    test hand-picked two of the analyser's eight rules to check. Driven through the product's own
    entry point instead, ALL 22 fixtures raised an undeclared 2.4.2 (`pdf.display-doc-title`) and
    18 raised an undeclared 1.3.1 (`pdf.tagged`). The worst of those was `document-title-ok` — the
    2.4.2 CONTROL, whose whole job is to stay silent on 2.4.2, and which did not. Its label was a
    claim about a rule nobody was running.

    So all four are stamped here, together, and each is withheld only by a fixture that says so."""
    import pikepdf
    with pikepdf.open(str(path), allow_overwriting_input=True) as pdf:
        if title is not None:
            pdf.docinfo[pikepdf.Name("/Title")] = pikepdf.String(title)
        if lang is not None:
            pdf.Root.Lang = pikepdf.String(lang)
        # /Title alone does not satisfy 2.4.2: a viewer shows the FILENAME in its window bar
        # unless ViewerPreferences opts into the title (pdf.display-doc-title).
        if display_title:
            pdf.Root.ViewerPreferences = pikepdf.Dictionary(DisplayDocTitle=True)
        # `pdf.tagged` wants BOTH a structure tree and /MarkInfo /Marked. The four fixtures built
        # by _figure and _headings already have a real tag tree with content in it; the rest get a
        # minimal empty one, which is enough to say "this document is tagged" without adding
        # structure that another criterion would then read.
        if tagged:
            if "/StructTreeRoot" not in pdf.Root:
                doc = pdf.make_indirect(pikepdf.Dictionary(
                    Type=pikepdf.Name.StructElem, S=pikepdf.Name.Document,
                    K=pikepdf.Array([])))
                root = pdf.make_indirect(pikepdf.Dictionary(
                    Type=pikepdf.Name.StructTreeRoot, K=pikepdf.Array([doc])))
                doc.P = root
                pdf.Root.StructTreeRoot = root
            pdf.Root.MarkInfo = pikepdf.Dictionary(Marked=True)
        pdf.save(str(path))


def _validate(name: str, expectations: dict[str, str]) -> list[str]:
    """Reject an expectation the engine could never produce. A manifest that expects PASS on a
    REVIEW-lane pair does not describe a product bug; it describes a manifest bug, and it would
    report a false failure on every run until somebody re-derived this by hand."""
    problems = []
    for sc, verdict in expectations.items():
        allowed = ce.possible_verdicts(sc, FMT)
        if verdict not in allowed:
            problems.append(
                f"{name}: expects {sc}={verdict} but the engine can only emit "
                f"{','.join(sorted(allowed))} for ({sc}, {FMT})")
    return problems


def build_all(docs: Path) -> tuple[list[dict], list[str]]:
    docs.mkdir(parents=True, exist_ok=True)
    manifest, problems = [], []
    for name, build, kind in FIXTURES:
        path = docs / f"{name}.pdf"
        built = build(path)
        expectations, note = built[0], built[1]
        # A builder may return a third element saying which piece of document metadata it is
        # deliberately withholding; everything else gets all four, so no fixture accidentally
        # tests 1.3.1, 2.4.2 or 3.1.1 as well as its own criterion.
        meta = built[2] if len(built) > 2 else {}
        _stamp(path, meta.get("title", DOC_TITLE), meta.get("lang", DOC_LANG),
               display_title=meta.get("display_title", True),
               tagged=meta.get("tagged", True))
        problems += _validate(name, expectations)
        manifest.append({"file": f"docs/{name}.pdf", "name": name, "kind": kind,
                         "format": FMT, "expect": expectations, "note": note})
    return manifest, problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path,
                    default=Path.home() / "Downloads" / "acp-pdf-eval" / "sc-corpus")
    args = ap.parse_args()

    manifest, problems = build_all(args.out / "docs")
    for row in manifest:
        print(f"  {row['kind']:11} {row['name']:24} {row['expect']}")
    if problems:
        print("\nIMPOSSIBLE EXPECTATIONS — fix the fixture, not the engine:", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        return 1

    scs = sorted(sc for sc, f in ce.pol.SCOPE_PRESETS["acp-core-17"].items() if FMT in f)
    (args.out / "manifest.json").write_text(json.dumps({
        "format": FMT, "fixtures": manifest,
        "lanes": {sc: {"clean_verdict": ce.clean_verdict(sc, FMT),
                       "possible": sorted(ce.possible_verdicts(sc, FMT)),
                       "can_pass": ce.can_ever_pass(sc, FMT)} for sc in scs},
    }, indent=1) + "\n")
    kinds: dict[str, int] = {}
    for row in manifest:
        kinds[row["kind"]] = kinds.get(row["kind"], 0) + 1
    print(f"\n{len(manifest)} fixtures: " + ", ".join(f"{n} {k}" for k, n in sorted(kinds.items())))
    print(f"declares {len(DECLARED)} of {len(scs)} applicable .pdf pairs: {', '.join(DECLARED)}")
    print(f"wrote {args.out / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
