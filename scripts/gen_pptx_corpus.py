#!/usr/bin/env python3
"""A LABELLED .pptx corpus — the third format to get ground truth, after .docx and .xlsx.

WHY THIS EXISTS. `scripts/gen_fixture_coverage.py` reports coverage per (criterion, format) pair;
pptx sat at 0 of 17 because no labelled corpus existed. This declares NINE of them.

SAME RULE AS THE XLSX CORPUS: a pair is only declared when a FIRST-PARTY detector — pure Python
in `api/office_structure.py`, no .NET engine — was driven against the fixture and confirmed to
fire, with an adversarial counterpart confirmed to stay silent. Coverage is counted from
declarations, so a fixture whose seeded violation nobody can confirm is caught would raise the
number without raising what the number measures.

    1.1.1   a picture with no descr                office_non_text_content_checks
    1.4.1   a hyperlink run with u="none"          office_color_only_checks
    1.4.3   run colour on an explicit shape fill   pptx_contrast_checks
    1.4.11  a faint shape outline on its fill      pptx_nontext_contrast_checks
    2.1.2   an embedded control                    office_control_review_checks
    2.4.3   title placeholder not first in order   pptx_focus_order_checks
    2.4.4   a vague hyperlink label                pptx_checks
    2.4.6   an empty title placeholder             pptx_checks
    4.1.2   an embedded control (same fixture)     office_control_review_checks

The eight not here (1.3.1, 1.3.2, 1.3.3, 1.4.5, 2.1.1, 2.4.2, 3.1.1, 3.1.2) run through the .NET
analyser, langdetect, or — for 2.1.1 — are human-only on pptx by registration.

TWO DETECTOR SUBTLETIES WORTH KNOWING, because a fixture that ignores them silently covers
nothing:

  * 1.4.3 needs an EXPLICIT shape solid fill as well as an explicit run colour. A bare textbox
    has no fill, so the detector cannot know what the text sits on and correctly says nothing —
    the first draft of that fixture declared 1.4.3 and detected zero.
  * 1.4.3 is judged at the WCAG LARGE-text bar (3:1), not 4.5:1, because run font size is often
    inherited from the placeholder and not reliably knowable. Flagging only below the large-text
    threshold guarantees every finding is a real failure at any size.

Run:
    python scripts/gen_pptx_corpus.py --out ~/Downloads/acp-pptx-eval/sc-corpus
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))
sys.path.insert(0, str(ROOT / "scripts"))

import corpus_expectations as ce  # noqa: E402

FMT = "pptx"

INK = (0x1A, 0x1F, 0x26)      # ~15:1 on white
FAINT = (0xDD, 0xDD, 0xDD)    # ~1.6:1 on white — under even the 3:1 large-text bar
PAPER = (0xFF, 0xFF, 0xFF)

# A 1x1 PNG, inline — the fixture needs an image to embed, not a picture of anything, and a
# committed binary is provenance a reviewer has to take on trust.
_PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c6360f8cf0000010101001b0b8b5c0000000049454e44ae426082")


def _deck(title: str = "Q3 regional revenue"):
    """A one-slide deck that is clean on everything a fixture does not deliberately break: a
    real title (so 2.4.6 stays quiet) and title-first placeholder order (so 2.4.3 does)."""
    from pptx import Presentation
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[5])   # title only
    slide.shapes.title.text = title
    return prs, slide


def _textbox(slide, text: str, *, colour=INK, fill=PAPER, underline=None, link: str | None = None):
    """A textbox with an EXPLICIT solid fill — 1.4.3 needs one to know what the text sits on."""
    from pptx.dml.color import RGBColor
    from pptx.util import Inches, Pt
    tb = slide.shapes.add_textbox(Inches(1), Inches(3), Inches(7), Inches(1))
    if fill is not None:
        tb.fill.solid()
        tb.fill.fore_color.rgb = RGBColor(*fill)
    run = tb.text_frame.paragraphs[0].add_run()
    run.text = text
    run.font.size = Pt(18)
    run.font.color.rgb = RGBColor(*colour)
    if underline is not None:
        run.font.underline = underline
    if link:
        run.hyperlink.address = link
    return tb


def _replace_parts(path: Path, parts: dict[str, str]) -> None:
    """Rewrite the saved deck, REPLACING any part named in `parts` and adding the rest.

    Replacing rather than appending matters: a zip may legally hold two entries with the same
    name, and readers differ on which one wins — a fixture built that way would be testing the
    zip library, not the detector.
    """
    import shutil
    import tempfile
    tmp = Path(tempfile.mkdtemp()) / path.name
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            if item.filename in parts:
                continue
            zout.writestr(item, zin.read(item.filename))
        for name, body in parts.items():
            zout.writestr(name, body)
    shutil.move(str(tmp), str(path))


# ── 2.4.6 Headings and Labels ────────────────────────────────────────────────────

def f_title_empty(prs, slide):
    slide.shapes.title.text = ""
    _textbox(slide, "Revenue grew across every region this quarter.")
    return {"2.4.6": "REVIEW"}, "a title placeholder present but left empty"


def f_title_ok(prs, slide):
    _textbox(slide, "Revenue grew across every region this quarter.")
    return {"2.4.6": "REVIEW"}, "a real title — must not be flagged (adversarial)"


# ── 2.4.4 Link Purpose ───────────────────────────────────────────────────────────

def f_link_vague(prs, slide):
    _textbox(slide, "click here", link="https://example.com/fy26-travel-policy.pdf")
    return {"2.4.4": "REVIEW"}, "a 'click here' label — the destination is unknowable"


def f_link_descriptive_ok(prs, slide):
    _textbox(slide, "Read the FY26 travel policy",
             link="https://example.com/fy26-travel-policy.pdf")
    return {"2.4.4": "REVIEW"}, "a descriptive label — must not be flagged (adversarial)"


# ── 1.4.1 Use of Color ───────────────────────────────────────────────────────────

def f_link_underline_off(prs, slide):
    # u="none" on the run's rPr: the link is set apart from surrounding text by COLOUR ALONE.
    _textbox(slide, "Read the FY26 travel policy", underline=False,
             link="https://example.com/fy26-travel-policy.pdf")
    return {"1.4.1": "REVIEW"}, "a hyperlink with its underline suppressed — colour is the only cue"


def f_link_underlined_ok(prs, slide):
    _textbox(slide, "Read the FY26 travel policy", underline=True,
             link="https://example.com/fy26-travel-policy.pdf")
    return {"1.4.1": "REVIEW"}, "the same link, underlined — must not be flagged (adversarial)"


# ── 1.4.3 Contrast (Minimum) ─────────────────────────────────────────────────────

def f_contrast_fail(prs, slide):
    _textbox(slide, "Revenue grew across every region this quarter.", colour=FAINT)
    return {"1.4.3": "REVIEW"}, "#DDDDDD on an explicit white fill ≈ 1.6:1, under even the 3:1 bar"


def f_contrast_ok(prs, slide):
    _textbox(slide, "Revenue grew across every region this quarter.")
    return {"1.4.3": "REVIEW"}, "the same shape, legible ink — must not be flagged (adversarial)"


# ── 1.4.11 Non-text Contrast ─────────────────────────────────────────────────────

def _shape(slide, outline):
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.util import Inches
    sh = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                                Inches(1), Inches(2), Inches(2.5), Inches(1))
    sh.fill.solid()
    sh.fill.fore_color.rgb = RGBColor(*PAPER)
    sh.line.color.rgb = RGBColor(*outline)
    return sh


def f_shape_faint_outline(prs, slide):
    _shape(slide, (0xC8, 0xC8, 0xC8))
    return {"1.4.11": "REVIEW"}, "a shape outline #C8C8C8 on white ≈ 1.8:1, under 3:1"


def f_shape_strong_outline_ok(prs, slide):
    # THE SAME SHAPE, drawn visibly. If 1.4.11 ever reported on a shape's PRESENCE rather than
    # its measured ratio, this would fire too — and that measurement is the whole criterion.
    _shape(slide, INK)
    return {"1.4.11": "REVIEW"}, "the same shape at ≈15:1 — must not be flagged (adversarial)"


# ── 2.4.3 Focus Order ────────────────────────────────────────────────────────────

def f_title_not_first(prs, slide):
    """Rebuild on a layout with two placeholders and move the title after the body."""
    return None   # handled by `post`, below — see FIXTURES


def f_focus_order(prs, slide):
    from pptx import Presentation
    # A fresh deck on the title+content layout: two placeholders, so document order is meaningful.
    prs2 = Presentation()
    s = prs2.slides.add_slide(prs2.slide_layouts[1])
    s.placeholders[1].text = "Revenue grew across every region this quarter."
    s.shapes.title.text = "Q3 regional revenue"
    tree = s.shapes._spTree
    el = s.shapes.title._element
    tree.remove(el)
    tree.append(el)                       # title now LAST in document order
    return prs2, ({"2.4.3": "REVIEW"},
                  "the title placeholder is not first in document order")


def f_focus_order_ok(prs, slide):
    from pptx import Presentation
    prs2 = Presentation()
    s = prs2.slides.add_slide(prs2.slide_layouts[1])
    s.shapes.title.text = "Q3 regional revenue"
    s.placeholders[1].text = "Revenue grew across every region this quarter."
    return prs2, ({"2.4.3": "REVIEW"},
                  "title first, body second — must not be flagged (adversarial)")


# ── 4.1.2 Name, Role, Value / 2.1.2 No Keyboard Trap ─────────────────────────────

def f_embedded_control(prs, slide):
    _textbox(slide, "Complete the survey below.")
    # ONE fixture, TWO criteria: an embedded control is evidence for the accessible-name question
    # AND the keyboard-trap question, and the detector reports both. Neither is settleable from
    # the file alone, which is why both are review-lane.
    return ({"4.1.2": "REVIEW", "2.1.2": "REVIEW"},
            "an embedded VBA project — name/role and keyboard behaviour both need a human",
            {"ppt/vbaProject.bin": "stand-in for a real macro project"})


def f_no_controls_ok(prs, slide):
    _textbox(slide, "Complete the survey below.")
    return ({"4.1.2": "REVIEW", "2.1.2": "REVIEW"},
            "a static deck with no controls — must not be flagged (adversarial)")


# ── 1.1.1 Non-text Content ───────────────────────────────────────────────────────

def f_picture_no_alt(prs, slide):
    import tempfile
    from pptx.util import Inches
    png = Path(tempfile.mkdtemp()) / "px.png"
    png.write_bytes(_PNG_1PX)
    slide.shapes.add_picture(str(png), Inches(1), Inches(2), Inches(2), Inches(2))
    return {"1.1.1": "REVIEW"}, "a picture with no descr — nothing for a screen reader"


def f_no_picture_ok(prs, slide):
    _textbox(slide, "North 412  ·  South 388  ·  East 501")
    return {"1.1.1": "REVIEW"}, "no non-text content at all — must not be flagged (adversarial)"


FIXTURES = [
    ("title-empty",             f_title_empty,             "violation"),
    ("title-ok",                f_title_ok,                "adversarial"),
    ("link-vague",              f_link_vague,              "violation"),
    ("link-descriptive-ok",     f_link_descriptive_ok,     "adversarial"),
    ("link-underline-off",      f_link_underline_off,      "violation"),
    ("link-underlined-ok",      f_link_underlined_ok,      "adversarial"),
    ("contrast-fail",           f_contrast_fail,           "violation"),
    ("contrast-ok",             f_contrast_ok,             "adversarial"),
    ("shape-faint-outline",     f_shape_faint_outline,     "violation"),
    ("shape-strong-outline-ok", f_shape_strong_outline_ok, "adversarial"),
    ("focus-order",             f_focus_order,             "violation"),
    ("focus-order-ok",          f_focus_order_ok,          "adversarial"),
    ("embedded-control",        f_embedded_control,        "violation"),
    ("no-controls-ok",          f_no_controls_ok,          "adversarial"),
    ("picture-no-alt",          f_picture_no_alt,          "violation"),
    ("no-picture-ok",           f_no_picture_ok,           "adversarial"),
]

DECLARED = ("1.1.1", "1.4.1", "1.4.11", "1.4.3", "2.1.2", "2.4.3", "2.4.4", "2.4.6", "4.1.2")


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
        prs, slide = _deck()
        built = build(prs, slide)
        # A builder returns (expectations, note), or (expectations, note, parts) when it needs a
        # zip part python-pptx cannot author, or (presentation, (expectations, note)) when it has
        # to construct its own deck on a different layout. Dispatched by shape rather than by a
        # flag, so each builder reads as the simplest thing that expresses its case.
        parts = None
        if len(built) == 2 and isinstance(built[1], tuple):
            prs, (expectations, note) = built
        else:
            expectations, note = built[0], built[1]
            parts = built[2] if len(built) > 2 else None
        path = docs / f"{name}.pptx"
        prs.save(path)
        if parts:
            _replace_parts(path, parts)
        problems += _validate(name, expectations)
        manifest.append({"file": f"docs/{name}.pptx", "name": name, "kind": kind,
                         "format": FMT, "expect": expectations, "note": note})
    return manifest, problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path,
                    default=Path.home() / "Downloads" / "acp-pptx-eval" / "sc-corpus")
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
    print(f"declares {len(DECLARED)} of {len(scs)} applicable .pptx pairs: {', '.join(DECLARED)}")
    print(f"wrote {args.out / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
