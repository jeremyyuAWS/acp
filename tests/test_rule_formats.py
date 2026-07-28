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


def registry_covers(rule: str, fmt: str) -> bool:
    """Whether this pair has been migrated to the capability registry.

    Several expectations below differ for a migrated pair — it has a real detector, so its
    clean result is REVIEW rather than NOT_EVALUATED. Asking the registry keeps those tests
    describing the invariant ("never a silent pass") instead of hard-coding today's roster,
    so migrating the next pair doesn't require editing assertions that are still correct.
    """
    try:
        import rule_registry
        rule_registry.load()
        return rule_registry.is_registered(rule, fmt)
    except Exception:
        return False


def _wcag_scs(path: Path) -> set[str]:
    return set(re.findall(r'"wcag":\s*"(\d+\.\d+\.\d+)', path.read_text()))


_OFFICE_STRUCT_FORMATS = {
    # office_structure.py's per-check format coverage — docx_checks()/pptx_checks()
    # cover 2.4.6 + 2.4.9 for those two formats; pdf_contrast_checks() +
    # xlsx_contrast_checks() + pptx_contrast_checks() cover 1.4.3 + 1.4.6 for pdf,
    # xlsx and pptx (the html coverage for these two comes from scanner.py, already
    # counted above via html_scs); pdf_bypass_blocks_check() covers 2.4.1 for PDF
    # only; docx_checks()'s form-field-label check covers 3.3.2 for docx only, and
    # its no-section-headings check covers 2.4.10 for docx only. (3.1.5 Reading Level
    # lives in textchecks.py and is derived as all-formats automatically.)
    "1.3.2": {"docx"},    # docx_checks() floating-text reading-order (pdf/pptx/xlsx + html come from elsewhere)
    "2.4.4": {"xlsx", "pdf"},    # xlsx_structure_checks() vague hyperlink + pdf_link_purpose_check() raw-URL link
    "2.4.6": {"docx", "pptx", "xlsx", "pdf"},   # + xlsx default labels + pdf_headings_labels_check() tagged-no-heading
    "2.4.9": {"docx", "pptx"},
    "1.4.3": {"pdf", "pptx", "xlsx"},
    "1.4.6": {"pdf", "pptx", "xlsx"},
    "2.4.1": {"pdf"},
    "3.3.2": {"docx"},
    "2.4.10": {"docx"},
    "1.4.8": {"docx"},    # docx_checks() justified-body-text check
    "1.4.2": {"pptx"},    # pptx_audio_autoplay_checks() — auto-starting embedded audio
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
    """The actual bug this fix closes: an HTML-only rule must never read PASS for a format it
    was not evaluated against.

    The invariant is "never a silent PASS", not "always NOT_EVALUATED" — those were the same
    statement only while no non-HTML detector existed for these criteria. A pair registered in
    the capability registry HAS a detector, so its clean result is REVIEW: weaker than PASS,
    stronger than "we did not look". Asserting the exact token here would make the test fail
    the moment a criterion gained real coverage, which is backwards.
    """
    html_only = [rid for rid, fmts in store.RULE_FORMATS.items() if fmts == frozenset({"html"})]
    assert html_only, "expected at least one HTML-only rule to exist"
    for rid in html_only:
        for fmt in ("docx", "pptx", "xlsx", "pdf"):
            assert store._rule_outcome(rid, fmt, 0) != "PASS", (
                f"{rid} must not silently PASS on a .{fmt} file"
            )
            if not registry_covers(rid, fmt):
                assert store._rule_outcome(rid, fmt, 0) == "NOT_EVALUATED", (
                    f"{rid} has no {fmt} detector, so it must read NOT_EVALUATED"
                )


def test_an_unrun_check_never_claims_the_criterion_is_inapplicable():
    """We may say "we did not check this". We may not say "this does not apply".

    2.4.3 Focus Order and 4.1.2 Name/Role/Value are html-only in RULE_FORMATS, but both
    genuinely apply to a tagged PDF — PDF/UA specifies them. Emitting NOT_APPLICABLE there
    asserted they were out of scope, which nothing in this codebase ever determined.

    UPDATED: this test used to assert both read NOT_EVALUATED on pdf, reasoning "no validator
    ran". That reason expired. `pdf_form_field_checks` and `pdf_focus_order_checks` both ship
    and run on every PDF, so the outcome must now state the fact we actually hold — we checked
    the AcroForm layer and nothing else — which is REVIEW. Reporting NOT_EVALUATED for work
    that was genuinely done is the mirror image of the original bug, and the reason both pairs
    were the first migrated to the capability registry.

    The principle the test was written to defend is untouched: the token still never claims
    inapplicability, and still never fabricates a pass.
    """
    assert store.NOT_EVALUATED == "NOT_EVALUATED"
    for rid in ("2.4.3", "4.1.2"):
        assert registry_covers(rid, "pdf"), (
            f"{rid} × pdf lost its registry entry — if the detector was deliberately removed, "
            f"this expectation should go back to NOT_EVALUATED"
        )
        assert store._rule_outcome(rid, "pdf", 0) == store.REVIEW
        assert store._rule_outcome(rid, "pdf", 1) == "FAIL"
    # A rule with no format restriction at all still evaluates where it has a validator. 1.1.1 is
    # a 🟡 review-lane criterion, so a clean scan is REVIEW ("verify"), not a certified pass (#174).
    assert store._rule_outcome("1.1.1", "pdf", 0) == store.REVIEW
    assert store._rule_outcome("1.1.1", "pdf", 3) == "FAIL"
    # An unknown format is unevaluated, never a pass.
    assert store._rule_outcome("1.1.1", None, 0) == store.NOT_EVALUATED


def test_rule_outcome_still_computes_pass_fail_for_applicable_formats():
    # 2.4.6 html + 3.1.1 pdf are 🟢 auto-assess → a clean scan is a real PASS.
    assert store._rule_outcome("2.4.6", "html", 0) == "PASS"
    assert store._rule_outcome("2.4.6", "html", 3) == "FAIL"
    assert store._rule_outcome("3.1.1", "pdf", 0) == "PASS"   # cross-format auto-assess rule
    assert store._rule_outcome("3.1.1", "pdf", 1) == "FAIL"


def test_file_format_recognizes_every_scanned_extension():
    assert store._file_format("report.html") == "html"
    assert store._file_format("report.htm") == "html"
    assert store._file_format("report.docx") == "docx"
    assert store._file_format("report.pptx") == "pptx"
    assert store._file_format("report.xlsx") == "xlsx"
    assert store._file_format("report.pdf") == "pdf"
    assert store._file_format("report.txt") is None
