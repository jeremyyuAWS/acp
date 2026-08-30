#!/usr/bin/env python3
"""A LABELLED .xlsx corpus — the second format to get ground truth, after .docx.

WHY THIS EXISTS. `scripts/gen_fixture_coverage.py` reports 15 of 62 applicable (criterion,
format) pairs covered: .docx complete, and xlsx / pptx / pdf at zero, because no labelled corpus
existed for any of them. This is the start of the xlsx half.

IT IS DELIBERATELY PARTIAL, AND THE LIMIT IS VERIFICATION, NOT EFFORT. Every fixture here seeds a
violation that a FIRST-PARTY detector — pure Python in `api/office_structure.py`, no external
engine — is confirmed to fire on, and every adversarial fixture is confirmed to leave it silent.
The other eleven xlsx pairs are not here because their detection runs through the .NET Office
analyser (or, for 3.1.2, through langdetect), and a fixture whose seeded violation nobody can
confirm is caught would inflate the very coverage number this corpus exists to report honestly.
Adding them is incremental work on a machine with the engine built; the shape is set.

    1.4.1   colour-scale conditional formatting          office_color_only_checks
    1.4.3   text/fill contrast under 4.5:1               xlsx_contrast_checks
    2.4.4   vague or raw-URL hyperlink labels            xlsx_structure_checks
    2.4.6   default SheetN tabs / ColumnN headers        xlsx_structure_checks

THE VOCABULARY IS NOT PASS/FAIL, and assuming it is would invalidate the labels. ACP answers four
things, and which are reachable is a property of the pair. On .xlsx only FIVE of the fifteen
Core-17 pairs can ever return PASS:

    1.3.1  1.3.2  1.4.3  2.4.2  3.1.1

Ten are REVIEW-lane: a review detector does not certify conformance (ADR 0016), so a CLEAN file
there resolves to REVIEW and NEVER to PASS. Every declaration below is checked against
`corpus_expectations.possible_verdicts()` at generation time — a fixture that expects PASS on
1.4.1 fails to build. Without that check the corpus would report a false failure on every run
forever, and it would read as a product defect rather than a manifest defect.

Note what that means for 1.4.1, 2.4.4 and 2.4.6 here: their violation fixtures expect FAIL or
REVIEW per their lane, and their adversarial counterparts expect REVIEW — not PASS — because the
engine is not permitted to certify those pairs at all.

Run:
    python scripts/gen_xlsx_corpus.py --out ~/Downloads/acp-xlsx-eval/sc-corpus
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

FMT = "xlsx"

# A readable sheet on a white ground — dark slate on white is ~12.6:1, so nothing a fixture does
# not deliberately break trips the contrast check.
INK = "FF1A1F26"
PAPER = "FFFFFFFF"


def _wb(title: str = "Q3 Benefits Summary"):
    """A workbook clean on everything the corpus is not deliberately breaking: a named sheet (so
    2.4.6's default-tab rule stays quiet), a document title, and legible text."""
    from openpyxl import Workbook
    wb = Workbook()
    wb.properties.title = title
    ws = wb.active
    ws.title = "Summary"
    return wb, ws


def _say(ws, ref: str, text: str, *, colour: str = INK, fill: str = PAPER):
    from openpyxl.styles import Font, PatternFill
    ws[ref] = text
    ws[ref].font = Font(color=colour)
    ws[ref].fill = PatternFill("solid", fgColor=fill)


# ── 1.4.3 Contrast (Minimum) ─────────────────────────────────────────────────────

def f_contrast_fail(wb, ws):
    # #DDDDDD on white is ~1.6:1 — far under 4.5, and unambiguous rather than a boundary case.
    _say(ws, "A1", "Quarterly revenue summary for the finance committee", colour="FFDDDDDD")
    return {"1.4.3": "FAIL"}, "grey #DDDDDD on white ≈ 1.6:1, well under the 4.5:1 minimum"


def f_contrast_ok(wb, ws):
    _say(ws, "A1", "Quarterly revenue summary for the finance committee")
    # PASS is reachable here — 1.4.3 is one of the five .xlsx pairs that can certify.
    return {"1.4.3": "PASS"}, "dark slate on white ≈ 12.6:1 — comfortably over the minimum"


# ── 2.4.4 Link Purpose (In Context) ──────────────────────────────────────────────

def f_link_vague(wb, ws):
    ws.title = "Policies"
    _say(ws, "A1", "Travel policy")
    _say(ws, "A2", "click here")
    ws["A2"].hyperlink = "https://example.com/fy26-travel-policy.pdf"
    return {"2.4.4": "REVIEW"}, "a 'click here' label — the destination is unknowable from the text"


def f_link_descriptive_ok(wb, ws):
    ws.title = "Policies"
    _say(ws, "A1", "Travel policy")
    _say(ws, "A2", "Read the FY26 travel policy")
    ws["A2"].hyperlink = "https://example.com/fy26-travel-policy.pdf"
    # REVIEW, not PASS: 2.4.4 on .xlsx is a review-lane pair and cannot certify however clean the
    # file is. A fixture expecting PASS here would fail _validate, which is the point of it.
    return {"2.4.4": "REVIEW"}, "a descriptive label — must NOT be flagged (adversarial)"


# ── 2.4.6 Headings and Labels ────────────────────────────────────────────────────

def f_default_sheet_tabs(wb, ws):
    ws.title = "Sheet1"
    wb.create_sheet("Sheet2")
    wb.create_sheet("Sheet3")
    _say(ws, "A1", "Regional totals")
    return {"2.4.6": "REVIEW"}, "three default SheetN tabs — the structure labels say nothing"


def f_one_default_tab_ok(wb, ws):
    # THE EDGE CASE, and the reason the detector requires two: a lone 'Sheet1' is what Excel
    # gives every new workbook, and flagging it would fire on almost every file in an estate.
    ws.title = "Sheet1"
    _say(ws, "A1", "Regional totals")
    return {"2.4.6": "REVIEW"}, "a LONE default tab — normal, must not be flagged (adversarial)"


def f_named_tabs_ok(wb, ws):
    ws.title = "Regional totals"
    wb.create_sheet("Headcount")
    wb.create_sheet("Assumptions")
    _say(ws, "A1", "Regional totals")
    return {"2.4.6": "REVIEW"}, "three named tabs — must not be flagged (adversarial)"


# ── 1.4.1 Use of Color ───────────────────────────────────────────────────────────

def f_colour_scale(wb, ws):
    from openpyxl.formatting.rule import ColorScaleRule
    ws.title = "Risk"
    _say(ws, "A1", "Region")
    _say(ws, "B1", "Score")
    for i, v in enumerate((10, 55, 90), start=2):
        _say(ws, f"A{i}", f"Region {i - 1}")
        ws[f"B{i}"] = v
    ws.conditional_formatting.add(
        "B2:B4", ColorScaleRule(start_type="min", start_color="FFF8696B",
                                end_type="max", end_color="FF63BE7B"))
    return {"1.4.1": "REVIEW"}, "a red→green colorScale — status carried by colour alone"


def f_icon_set_ok(wb, ws):
    from openpyxl.formatting.rule import IconSetRule
    ws.title = "Risk"
    _say(ws, "A1", "Region")
    _say(ws, "B1", "Score")
    for i, v in enumerate((10, 55, 90), start=2):
        _say(ws, f"A{i}", f"Region {i - 1}")
        ws[f"B{i}"] = v
    # An iconSet pairs colour WITH a shape, so it is NOT colour-only — the detector says so
    # explicitly, and this fixture is what holds it to that.
    ws.conditional_formatting.add("B2:B4", IconSetRule("3TrafficLights1", "percent", [0, 33, 67]))
    return {"1.4.1": "REVIEW"}, "an iconSet — colour PLUS a shape, must not be flagged (adversarial)"


FIXTURES = [
    ("contrast-fail",        f_contrast_fail,          "violation"),
    ("contrast-ok",          f_contrast_ok,            "clean"),
    ("link-vague",           f_link_vague,             "violation"),
    ("link-descriptive-ok",  f_link_descriptive_ok,    "adversarial"),
    ("sheet-tabs-default",   f_default_sheet_tabs,     "violation"),
    ("sheet-tab-single-ok",  f_one_default_tab_ok,     "edge"),
    ("sheet-tabs-named-ok",  f_named_tabs_ok,          "adversarial"),
    ("colour-scale-only",    f_colour_scale,           "violation"),
    ("colour-icon-set-ok",   f_icon_set_ok,            "adversarial"),
]

# The criteria this corpus declares. Kept explicit so gen_fixture_coverage and the tests agree
# with the generator about what it claims, rather than each deriving it separately.
DECLARED = ("1.4.1", "1.4.3", "2.4.4", "2.4.6")


def _validate(name: str, expectations: dict[str, str]) -> list[str]:
    """Reject an expectation the engine could never produce — the whole reason
    corpus_expectations exists. A manifest that expects PASS on a REVIEW-lane pair does not
    describe a product bug; it describes a manifest bug, and it would report a false failure on
    every run until somebody re-derived this by hand."""
    problems = []
    for sc, verdict in expectations.items():
        allowed = ce.possible_verdicts(sc, FMT)
        if verdict not in allowed:
            problems.append(
                f"{name}: expects {sc}={verdict} but the engine can only emit "
                f"{','.join(sorted(allowed))} for ({sc}, {FMT})")
    return problems


def build_all(docs: Path) -> tuple[list[dict], list[str]]:
    """Write every fixture and return (manifest rows, validation problems)."""
    docs.mkdir(parents=True, exist_ok=True)
    manifest, problems = [], []
    for name, build, kind in FIXTURES:
        wb, ws = _wb()
        expectations, note = build(wb, ws)
        path = docs / f"{name}.xlsx"
        wb.save(path)
        problems += _validate(name, expectations)
        manifest.append({"file": f"docs/{name}.xlsx", "name": name, "kind": kind,
                         "format": FMT, "expect": expectations, "note": note})
    return manifest, problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path,
                    default=Path.home() / "Downloads" / "acp-xlsx-eval" / "sc-corpus")
    args = ap.parse_args()

    manifest, problems = build_all(args.out / "docs")
    for row in manifest:
        print(f"  {row['kind']:11} {row['name']:22} {row['expect']}")

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
    kinds = {}
    for row in manifest:
        kinds[row["kind"]] = kinds.get(row["kind"], 0) + 1
    print(f"\n{len(manifest)} fixtures: " + ", ".join(f"{n} {k}" for k, n in sorted(kinds.items())))
    print(f"declares {len(DECLARED)} of {len(scs)} applicable .xlsx pairs: {', '.join(DECLARED)}")
    print(f"wrote {args.out / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
