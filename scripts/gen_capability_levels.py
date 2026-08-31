#!/usr/bin/env python3
"""Four separate answers about every (criterion, format) pair, on four separate denominators.

WHY THIS EXISTS. `gen_matrix_coverage.py` answers one question — the strongest tier a cell could
honestly claim — and derives it from what the code DECLARES: the rule registry, the capability
tables, the lane tables. That is the right input for a ceiling, and it is blind to two failure
modes this repo has now hit four times:

  * a detector that is registered but that no scan ever invokes
    (docx 1.3.5, pdf 1.3.5, pdf 2.5.3 — tests/test_orphaned_detectors.py)
  * a detector that is invoked but cannot fire on any input
    (pdf 1.3.2 — tests/test_pdf_reading_order.py)

Both read as `review` — "a detector produces evidence" — because both are registered. Neither
produces evidence. One number cannot carry that distinction, so this reports four, and refuses to
add them together.

THE DENOMINATORS ARE DIFFERENT AND THE DIFFERENCE IS THE POINT. Mixing them is how "57%" comes to
mean nothing:

  REGISTERED           over the rule registry's own cells (22 criteria x 4 formats)
  REACHABLE            over the same cells — but as three states, not a count of successes
  TESTED               over assessment_policy.SCOPE_PRESETS['acp-core-17'] (62 pairs)
  REMEDIATION-VERIFIED over the write lanes handlers.py actually declares (17 pairs)

NONE OF THESE IS A COMPLIANCE MEASURE. "Tested" means a labelled fixture proves a detector fires
and an adversarial counterpart stays silent. It says nothing about whether a document conforms to
WCAG, nor whether the detector's judgement is correct, nor whether every failure within a
criterion is caught. A pair can be tested and still be a partial check — most are.

REACHABILITY IS THREE STATES BECAUSE IT CANNOT BE DERIVED. Asking statically whether a registered
detector is reachable from `office_structure.checks_for` flags 11 of 32 registrations, of which 3
are real: the registered detector and the scan-path implementation are frequently different code
emitting the same criterion (1.1.1 docx, 2.4.3 pdf, 2.4.4 docx and 4.1.2 docx/pdf all look
unreachable and are all proven to fire). So reachability is reported from EVIDENCE only:

  PROVEN       a ground-truth corpus pair shows a real scan reporting it
  DISPROVEN    a test shows a real scan does not report it, on a document that should trip it
  UNVERIFIED   neither — nobody has run the experiment

UNVERIFIED IS THE LOAD-BEARING STATE. It is not a failure and not a pass; it is the honest answer
for a cell nobody has tested, and counting it as capability is exactly the over-claim the four
findings above are instances of. Every cell starts here and leaves only by evidence.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))
sys.path.insert(0, str(ROOT / "scripts"))

FORMATS = ("docx", "xlsx", "pptx", "pdf")
PRESET = "acp-core-17"

# Cells a test shows a real scan does NOT report, on a document built to trip them. Each names the
# test that establishes it, so the claim is checkable rather than asserted here. These are the only
# way out of UNVERIFIED in the negative direction — a cell is never marked disproven by reading.
DISPROVEN = {
    ("1.3.2", "pdf"): ("tests/test_pdf_reading_order.py — pdf.reading-order compares a word list "
                       "against itself, so divergence is 0.0 on every input including a fully "
                       "reversed content stream"),
    ("1.3.5", "docx"): ("tests/test_orphaned_detectors.py — input_purpose.detect returns a finding "
                        "when called directly; checks_for never invokes it"),
    ("1.3.5", "pdf"): ("tests/test_orphaned_detectors.py — same shape, PDF_INPUT_NO_PURPOSE"),
    ("2.5.3", "pdf"): ("tests/test_orphaned_detectors.py — same shape, PDF_LABEL_NOT_IN_NAME"),
}

# Write lanes are read from handlers.py rather than restated, so this cannot drift from what an
# approved value can actually be written into.
_LANE_CONSTS = ("_LINK_SCS_BY_EXT", "_SENSORY_EXTS", "_LANGUAGE_EXTS", "_STRUCTURE_LABEL_EXTS",
                "_PDF_APPLY_EXTS", "_FIELD_NAME_EXTS", "_OFFICE_ALT_MIME")

# A lane is remediation-VERIFIED only when a test writes an approved value and then checks the
# saved document through the real path — not when the applier returns without raising, and not
# when a re-scan is simulated. Every OTHER apply test drives handlers._apply_approved_values with
# residual=set(), supplying the re-scan result rather than performing one, which is why this was
# empty when the report shipped. Populate it as lanes earn it; each entry must name its test.
#
# What an entry claims, exactly: ACP's own criterion stops firing on a document ACP changed, and
# the document survived the change. It is NOT a claim that the result conforms — a detector
# keying on link text alone approximates "Link Purpose (In Context)" in both directions, and no
# automated check can confirm a screen reader announces the new text usefully.
REMEDIATION_VERIFIED: dict[tuple[str, str], str] = {
    ("2.4.4", "docx"): (
        "tests/test_remediation_verified_docx_link.py — a real assessment reports 2.4.4, the "
        "proposer offers a value, a reviewer approves it, handlers._apply_approved_values writes "
        "it with the re-scan UNPATCHED, and the saved package is re-opened: the visible text "
        "changed, the href, the other hyperlink, the emphasised runs and the table did not, the "
        "file still opens, and a second real assessment no longer reports 2.4.4. Negative "
        "controls: an approved value that is itself vague is written but never credited, and an "
        "already-descriptive document is left byte-identical"),
    ("2.4.4", "xlsx"): (
        "tests/test_remediation_verified_xlsx_link.py — extraction, proposal, writer and "
        "verification moved as one change. The CELL VALUE (what a reader sees in the grid) "
        "carries the approved text, read back with openpyxl; the href, formulas, cell styles, "
        "the other hyperlink and an unrelated cell holding the same string all survive; a "
        "shared <si> is never edited in place (a new entry is appended and only the linked cell "
        "repointed, with uniqueCount bumped and count left alone); the workbook opens; a re-scan "
        "no longer reports 2.4.4. A formula-labelled cell is REFUSED with a reason rather than "
        "rewritten, and never gets its display= written as a consolation"),
    ("1.1.1", "pptx"): (
        "tests/test_remediation_verified_pptx_alt.py — a real assessment reports 1.1.1 on an "
        "undescribed picture and carries a locator apply_alt.parse_locator resolves; a "
        "reviewer-authored description goes through handlers._apply_approved_values with the "
        "re-scan UNPATCHED; the saved deck carries the descr, the title and body copy survive, "
        "python-pptx re-opens it, and a second real assessment no longer reports 1.1.1. The "
        "load-bearing control is a TWO-picture deck with one description approved: the write "
        "succeeds, the criterion still fails, and nothing is credited or published"),
    ("3.1.2", "docx"): (
        "tests/test_remediation_verified_docx_language.py — the only lane whose whole chain is "
        "deterministic, so the test starts from the document and takes the reviewer's value from "
        "the draft propose_language_parts actually offers. A real assessment reports 3.1.2 on an "
        "unmarked French passage, the approved code goes through handlers._apply_approved_values "
        "with the re-scan UNPATCHED, the passage's runs gain w:lang, and a second real assessment "
        "no longer reports it. Because a language mark is metadata, the assertion is stronger "
        "than elsewhere: the whole extracted text is byte-identical before and after. A value "
        "that is not a language code is refused rather than written where AT reads a language"),
    ("2.4.4", "pptx"): (
        "tests/test_remediation_verified_pptx_link.py — the proposer's draft, a reviewer's "
        "edit, handlers._apply_approved_values with the re-scan UNPATCHED, then the saved deck "
        "re-opened: the visible text changed, the href, the run's <a:hlinkClick>, the author's "
        "bold, the other slide's hyperlink and both titles did not, python-pptx re-opens it, "
        "and a second real assessment no longer reports 2.4.4. The control this lane makes "
        "possible and no single-criterion lane can: pptx declares scs_to_clear = {2.4.4, "
        "2.4.9}, so an approved value that clears 2.4.4 by REUSING the other link's text — "
        "breaking 2.4.9 in the same write — is written and never credited"),
    ("1.1.1", "docx"): (
        "tests/test_remediation_verified_docx_alt.py — a real assessment reports 1.1.1 on two "
        "undescribed images carrying locators apply_alt.parse_locator resolves to wp:docPr; "
        "reviewer-authored descriptions go through handlers._apply_approved_values with the "
        "re-scan UNPATCHED; the saved document carries both descr values, the heading, bold "
        "run, table and closing paragraph survive, python-docx re-opens it, and a second real "
        "assessment no longer reports 1.1.1. It is also the first proof of the DECORATIVE half "
        "of the lane — a reviewer's 'this image carries no information' answered with the OOXML "
        "adec:decorative marker, which reaches _apply_one_value_kind through extra_work=True "
        "with an empty value map and clears the criterion on the re-scan. Controls: describing "
        "one of two images is written but never credited, and an approval aimed at an image the "
        "document does not have resolves to nothing and changes nothing"),
    ("2.4.9", "docx"): (
        "tests/test_remediation_verified_office_link_duplicate.py — parametrised over docx and "
        "pptx, because 2.4.9 is one writer and one criterion differing only in which part the "
        "hyperlink lives in. Two links reading 'annual report' at two DIFFERENT destinations; "
        "the proposer offers a value for each side of the collision; relabelling ONE through "
        "handlers._apply_approved_values with the re-scan UNPATCHED clears it, with the other "
        "link, both destinations and the surrounding content untouched. The mirror control of "
        "the pptx 2.4.4 proof: relabelling the duplicate to 'click here' genuinely clears 2.4.9 "
        "and trips 2.4.4, and because the lane declares scs_to_clear = {2.4.4, 2.4.9} it is "
        "written and never credited"),
    ("2.4.9", "pptx"): (
        "tests/test_remediation_verified_office_link_duplicate.py — the pptx half of the same "
        "parametrised proof, where the two colliding links sit on DIFFERENT slides and so "
        "resolve through different per-slide rels parts"),
    ("3.1.2", "pptx"): (
        "tests/test_remediation_verified_pptx_language.py — the docx language proof's twin, "
        "kept a separate file because the WRITE differs: PresentationML records a run's "
        "language as a bare `lang=` attribute on <a:rPr>, not Word's <w:lang w:val=…> element. "
        "A real assessment reports 3.1.2 on an unmarked French passage, the code "
        "propose_language_parts actually drafts is approved and written through the real lane "
        "with the re-scan UNPATCHED, and a second assessment no longer reports it. As on docx "
        "the survival assertion is the strong one — a language mark is metadata, so the whole "
        "extracted text must be byte-identical. A value that is not a language code is refused "
        "by the writer and reported unresolved rather than written"),
    ("1.1.1", "xlsx"): (
        "tests/test_remediation_verified_xlsx_alt.py — the third alt-text lane, and the only "
        "one whose image is not in the content part at all: SpreadsheetML keeps pictures in "
        "xl/drawings/drawingN.xml, so the locator names a drawing and the element is cNvPr "
        "with or without an xdr: prefix (Excel writes it prefixed, openpyxl bare). The "
        "workbook starts with openpyxl's hard-coded descr placeholder \"Picture\" — attribute "
        "present, saying nothing — which the detector reads as undescribed; approved "
        "descriptions go through handlers._apply_approved_values with the re-scan UNPATCHED; "
        "the sheet name, cell values and shared strings are read back with openpyxl. Control: "
        "describing one of two images is written and never credited"),
    ("4.1.2", "docx"): (
        "tests/test_remediation_verified_docx_field_name.py — a Word content control with no "
        "Title: a real assessment reports 4.1.2, an approved name goes through "
        "handlers._apply_approved_values with the re-scan UNPATCHED, and w:alias reaches the "
        "document. The same write also clears 3.3.2, asserted rather than assumed — w:alias is "
        "simultaneously the accessible name and the visible label, and the lane's scs_to_clear "
        "is {4.1.2} alone, so that is a property of the document rather than of the "
        "bookkeeping. Controls: an author-supplied Title is never overwritten, an approval "
        "aimed at a control that is not there changes nothing, and a w:text control is not a "
        "form field at all — the exclusion both detector and writer gate on"),
}

# WHAT NEITHER ENTRY ABOVE CLAIMS, written here rather than left to be inferred from their
# brevity: that a screen reader announces the new text usefully. Both lanes verify that the text
# a SIGHTED reader sees changed and that the document survived; how Excel or Word expose a
# hyperlink's accessible name to assistive technology is a rendered behaviour, and nothing in
# this repo can observe it. A lane that needed that evidence would need a different instrument
# than a test suite, and saying so is cheaper than a footnote nobody reads.


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def registered_pairs() -> dict[tuple[str, str], str]:
    """{(sc, fmt): detector module} for every registration carrying a detector."""
    import rule_registry as reg
    reg.load()
    out = {}
    for r in reg.all_registrations():
        det = getattr(r, "detector", None)
        if det is not None:
            out[(r.rule, r.fmt)] = getattr(det, "__module__", "?")
    return out


def tested_pairs() -> dict[tuple[str, str], str]:
    """{(sc, fmt): 'declared'|'engine'} — delegated to gen_fixture_coverage.coverage() rather than
    re-derived from the generators' DECLARED tuples.

    The first version of this function did re-derive it, and got 36 instead of 51: gen_sc_corpus
    (.docx) has no DECLARED tuple — its declarations live in per-fixture expectations, which
    gen_fixture_coverage's _docx_declared() knows how to read and a naive getattr does not. Two
    reports disagreeing about the same fact is the exact failure this file exists to prevent, so
    there is one implementation and this defers to it."""
    gfc = _load("gen_fixture_coverage", ROOT / "scripts" / "gen_fixture_coverage.py")
    cov = gfc.coverage()
    out = {}
    for fmt, row in cov.items():
        engine = set(row.get("engine_only") or ())
        for sc in row["covered"]:
            out[(sc, fmt)] = "engine" if sc in engine else "declared"
    return out


def write_lanes() -> set[tuple[str, str]]:
    """The (criterion, format) pairs an approved value can be written into, parsed from
    handlers.py — importing it drags in the scheduler and the DB driver."""
    import ast
    tree = ast.parse((ROOT / "api" / "handlers.py").read_text())
    consts = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") in _LANE_CONSTS:
            try:
                consts[node.targets[0].id] = ast.literal_eval(node.value)
            except Exception:
                pass
    pairs: set[tuple[str, str]] = set()
    for ext, scs in (consts.get("_LINK_SCS_BY_EXT") or {}).items():
        pairs.update((sc, ext) for sc in scs)
    for sc, key in (("1.3.3", "_SENSORY_EXTS"), ("3.1.2", "_LANGUAGE_EXTS"),
                    ("2.4.6", "_STRUCTURE_LABEL_EXTS"), ("4.1.2", "_FIELD_NAME_EXTS")):
        pairs.update((sc, ext) for ext in (consts.get(key) or ()))
    for ext in (consts.get("_OFFICE_ALT_MIME") or {}):
        pairs.add(("1.1.1", ext))
    for ext in (consts.get("_PDF_APPLY_EXTS") or ()):
        pairs.add(("1.1.1", ext))
    return pairs


def preset_pairs() -> set[tuple[str, str]]:
    import assessment_policy as ap
    return {(sc, fmt) for sc, fmts in ap.SCOPE_PRESETS[PRESET].items() for fmt in fmts}


def levels() -> dict:
    reg = registered_pairs()
    tested = tested_pairs()
    lanes = write_lanes()
    preset = preset_pairs()

    reachability = {}
    for pair in set(reg) | preset:
        if pair in DISPROVEN:
            reachability[pair] = "disproven"
        elif pair in tested:
            reachability[pair] = "proven"
        else:
            reachability[pair] = "unverified"

    return {
        "registered": {
            "denominator": "rule registry cells carrying a detector",
            "count": len(reg),
            "pairs": sorted(f"{sc} {fmt}" for sc, fmt in reg),
        },
        "reachable": {
            "denominator": "registry cells and preset pairs, as three evidence states",
            "proven": sorted(f"{sc} {fmt}" for p, s in reachability.items()
                             if s == "proven" for sc, fmt in [p]),
            "disproven": {f"{sc} {fmt}": DISPROVEN[(sc, fmt)] for sc, fmt in DISPROVEN},
            "unverified": sorted(f"{sc} {fmt}" for p, s in reachability.items()
                                 if s == "unverified" for sc, fmt in [p]),
        },
        "tested": {
            "denominator": f"{len(preset)} pairs in {PRESET} — tested pairs, NOT compliance",
            "count": len(tested),
            "of": len(preset),
            "engine_only": sorted(f"{sc} {fmt}" for (sc, fmt), k in tested.items()
                                  if k == "engine"),
        },
        "remediation_verified": {
            "denominator": f"{len(lanes)} write lanes declared in handlers.py",
            "count": len(REMEDIATION_VERIFIED),
            "of": len(lanes),
            "lanes": sorted(f"{sc} {fmt}" for sc, fmt in lanes),
        },
    }


def _report(d: dict) -> str:
    lines = [
        "CAPABILITY LEVELS — four questions, four denominators, deliberately not added together",
        "",
        "This is not a compliance measure. 'Tested' means a labelled fixture proves a detector",
        "fires and an adversarial counterpart stays silent — not that a document conforms, nor",
        "that the detector's judgement is correct, nor that every failure within a criterion is",
        "caught. The four counts below are not addable and share no denominator.",
        "",
    ]
    r = d["reachable"]
    lines += [
        f"  REGISTERED             {d['registered']['count']:>3}"
        f"    {d['registered']['denominator']}",
        f"  REACHABLE  proven      {len(r['proven']):>3}"
        f"    a corpus pair shows a real scan reporting it",
        f"             disproven   {len(r['disproven']):>3}"
        f"    a test shows a real scan does NOT report it",
        f"             unverified  {len(r['unverified']):>3}"
        f"    nobody has run the experiment",
        f"  TESTED                 {d['tested']['count']:>3} of {d['tested']['of']}"
        f"  {d['tested']['denominator']}",
        f"  REMEDIATION-VERIFIED   {d['remediation_verified']['count']:>3}"
        f" of {d['remediation_verified']['of']}"
        f"  {d['remediation_verified']['denominator']}",
        "",
        "DISPROVEN — registered, and a real scan does not report it:",
    ]
    for pair, why in sorted(r["disproven"].items()):
        lines.append(f"    {pair:14} {why}")
    lines += ["",
              "UNVERIFIED is not a failure and not a pass. It is the honest state for a cell",
              "nobody has tested, and counting it as capability is the over-claim the four",
              "disproven cells above are instances of.", ""]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap_ = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap_.add_argument("--json", action="store_true", help="emit the whole map as JSON")
    args = ap_.parse_args(argv)
    d = levels()
    print(json.dumps(d, indent=1) if args.json else _report(d))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
