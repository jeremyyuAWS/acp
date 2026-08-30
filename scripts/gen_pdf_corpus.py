#!/usr/bin/env python3
"""A LABELLED .pdf corpus — the fourth and last format to get ground truth.

WHY THIS EXISTS. `scripts/gen_fixture_coverage.py` reports coverage per (criterion, format)
pair; pdf sat at 0 of 15 because no labelled corpus existed. This declares EIGHT of them, and
completes the sweep begun with .docx: every format ACP scans now has ground truth.

SAME RULE AS THE XLSX AND PPTX CORPORA, and it is the rule that makes the number mean
something: a pair is declared only when a FIRST-PARTY detector — pure Python under
`api/formats/pdf/detectors/` and `api/office_structure.py`, no partner engine — was driven
against the fixture and confirmed to fire, with an adversarial counterpart confirmed to stay
silent. Coverage is counted from declarations, so a fixture whose seeded violation nobody has
confirmed is caught would raise the number without raising what the number measures.

    1.1.1   a tagged /Figure with no /Alt            pdf_non_text_content_checks
    1.4.1   a coloured link with no underline        pdf_use_of_color_checks
    1.4.3   grey text on an explicit white ground    pdf_contrast_checks
    1.4.11  a faint rect outline on its own fill     pdf_nontext_contrast_checks
    2.4.3   form widgets on a page without /Tabs /S  pdf_focus_order_checks
    2.4.4   a vague link label ("Click here")        pdf_link_purpose_check
    2.4.6   a tagged 6-page file with no heading     pdf_headings_labels_check
    4.1.2   an AcroForm field with no /TU            pdf_form_field_checks

WHY PDF REACHES FURTHEST OF ANY FORMAT — eight pairs from a standing start, where xlsx managed
eight only after zip-part injection. The PDF analyser is vendored in-tree (ADR 0029), so unlike
the .NET Office analyser it is present wherever the suite runs: `scripts/check_engines.py`
reports office and ocr unavailable in a bare container and pdf available. Every detector above
is reachable without installing anything.

The seven not here (1.3.1, 1.3.2, 1.3.3, 1.4.5, 2.4.2, 3.1.1, 3.1.2) need tag-tree semantics no
detector reads yet, OCR (1.4.5), or langdetect (3.1.1/3.1.2).

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
                     T=String("email"), Rect=Array([50, 100, 250, 130]), V=String(""))
    if named:
        fld.TU = String("Email address")
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
    return {"4.1.2": "REVIEW"}, "the same field carrying /TU 'Email address' (adversarial)"


def f_no_tabs_structure(path: Path):
    _form(path, named=True, tabs_s=False)
    return ({"2.4.3": "FAIL"},
            "a page carrying form widgets without /Tabs /S — tab order is not declared to "
            "follow the document's structure")


def f_tabs_structure_ok(path: Path):
    _form(path, named=True, tabs_s=True)
    return {"2.4.3": "REVIEW"}, "the same page with /Tabs /S set (adversarial)"


FIXTURES = [
    ("figure-no-alt",           f_figure_no_alt,           "violation"),
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

DECLARED = ("1.1.1", "1.4.1", "1.4.11", "1.4.3", "2.4.3", "2.4.4", "2.4.6", "4.1.2")


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
        expectations, note = build(path)
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
