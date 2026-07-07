"""Contract: store.py's RULE_FORMATS must match what actually validates each rule,
derived independently from source — mirrors frontend/src/wcagCatalog.test.js's
drift guard. Without this, RULE_FORMATS is exactly the kind of hand-maintained
table that silently went stale before (the false-PASS bug this file guards
against in the first place).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import store  # noqa: E402

_ALL_FORMATS = frozenset({"html", "docx", "pptx", "xlsx", "pdf"})
_OFFICE_PDF = frozenset({"docx", "pptx", "xlsx", "pdf"})


def _wcag_scs(path: Path) -> set[str]:
    return set(re.findall(r'"wcag":\s*"(\d+\.\d+\.\d+)', path.read_text()))


_OFFICE_STRUCT_FORMATS = {
    # office_structure.py's per-check format coverage — docx_checks()/pptx_checks()
    # cover 2.4.6 + 2.4.9 for those two formats; pdf_contrast_checks() +
    # xlsx_contrast_checks() cover 1.4.3 + 1.4.6 for pdf and xlsx (the html
    # coverage for these two comes from scanner.py, already counted above via
    # html_scs); pdf_bypass_blocks_check() covers 2.4.1 for PDF only;
    # docx_checks()'s form-field-label check covers 3.3.2 for docx only.
    "2.4.6": {"docx", "pptx"},
    "2.4.9": {"docx", "pptx"},
    "1.4.3": {"pdf", "xlsx"},
    "1.4.6": {"pdf", "xlsx"},
    "2.4.1": {"pdf"},
    "3.3.2": {"docx"},
}


def _derive_formats() -> dict[str, frozenset[str]]:
    html_scs = _wcag_scs(ACP / "api" / "scanner.py")
    ocr_scs = _wcag_scs(ACP / "api" / "ocr.py")
    tc_scs = _wcag_scs(ACP / "api" / "textchecks.py")
    catalog = json.loads((ACP / "config" / "rule-catalog.json").read_text())
    partner: dict[str, set[str]] = {}
    for fmt, rules in catalog.items():
        if fmt == "_meta":
            continue
        for r in rules:
            partner.setdefault(r["wcag_sc"], set()).add(fmt)

    derived: dict[str, set[str]] = {}
    for sc in html_scs:
        derived.setdefault(sc, set()).add("html")
    for sc in ocr_scs:
        derived.setdefault(sc, set()).update(_OFFICE_PDF)
    for sc in tc_scs:
        derived.setdefault(sc, set()).update(_ALL_FORMATS)
    for sc, fmts in partner.items():
        derived.setdefault(sc, set()).update(fmts)
    for sc, fmts in _OFFICE_STRUCT_FORMATS.items():
        derived.setdefault(sc, set()).update(fmts)
    return {sc: frozenset(fmts) for sc, fmts in derived.items()}


def test_rule_formats_matches_derived_ground_truth():
    derived = _derive_formats()
    catalog_ids = {r["id"] for r in store.RULE_CATALOG}

    # Every catalog rule must have a formats entry.
    missing = catalog_ids - set(store.RULE_FORMATS)
    assert not missing, f"RULE_CATALOG rules with no RULE_FORMATS entry: {sorted(missing)}"

    # Every rule's declared formats must match what's actually derivable from source.
    mismatches = []
    for rid in sorted(catalog_ids):
        want = derived.get(rid, frozenset())
        got = store.RULE_FORMATS[rid]
        if want and got != want:
            mismatches.append(f"{rid}: declared={sorted(got)} derived={sorted(want)}")
    assert not mismatches, "RULE_FORMATS drift:\n" + "\n".join(mismatches)


def test_no_html_only_rule_shows_pass_on_a_non_html_file():
    """The actual bug this fix closes: an HTML-only rule must read NOT_APPLICABLE,
    never PASS, for a format it was never evaluated against."""
    html_only = [rid for rid, fmts in store.RULE_FORMATS.items() if fmts == frozenset({"html"})]
    assert html_only, "expected at least one HTML-only rule to exist"
    for rid in html_only:
        for fmt, filename in (("docx", "x.docx"), ("pptx", "x.pptx"), ("xlsx", "x.xlsx"), ("pdf", "x.pdf")):
            assert store._rule_outcome(rid, fmt, 0) == "NOT_APPLICABLE", (
                f"{rid} should be NOT_APPLICABLE on a .{fmt} file, not silently PASS"
            )


def test_rule_outcome_still_computes_pass_fail_for_applicable_formats():
    assert store._rule_outcome("2.4.6", "html", 0) == "PASS"
    assert store._rule_outcome("2.4.6", "html", 3) == "FAIL"
    assert store._rule_outcome("1.3.3", "pdf", 0) == "PASS"   # cross-format rule
    assert store._rule_outcome("1.3.3", "pdf", 1) == "FAIL"


def test_file_format_recognizes_every_scanned_extension():
    assert store._file_format("report.html") == "html"
    assert store._file_format("report.htm") == "html"
    assert store._file_format("report.docx") == "docx"
    assert store._file_format("report.pptx") == "pptx"
    assert store._file_format("report.xlsx") == "xlsx"
    assert store._file_format("report.pdf") == "pdf"
    assert store._file_format("report.txt") is None
