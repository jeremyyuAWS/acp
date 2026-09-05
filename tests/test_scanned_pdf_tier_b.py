"""ADR 0027 Tier B — WCAG REVIEW findings from scanned-PDF layout descriptions.

Test sections:

1. findings_from_layouts() — correctness of returned finding dicts (shape, severity,
   wcag strings, advisory flag, detail content).

2. Empty / edge-case inputs — no pages → empty list; single page.

3. Scanner wiring guard — confirms pdf_vision_review is imported inside the Tier A/B
   block in scanner.py, and that the Tier B print statement is present.

4. Structural guards — five expected rule IDs all present; no duplicate ruleIds;
   all findings have required keys.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

import pdf_vision_review as pvr  # noqa: E402


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_page(page: int = 1, description: str = "A scanned page.") -> dict:
    return {"page": page, "description": description, "evidence": "vision-layout-v1"}


# ══ 1. findings_from_layouts ════════════════════════════════════════════════

class TestFindingsFromLayouts:
    def test_returns_five_findings_for_one_page(self):
        findings = pvr.findings_from_layouts([_make_page()])
        assert len(findings) == 5

    def test_all_findings_are_review_severity(self):
        findings = pvr.findings_from_layouts([_make_page()])
        assert all(f["severity"] == "REVIEW" for f in findings)

    def test_all_findings_are_advisory(self):
        findings = pvr.findings_from_layouts([_make_page()])
        assert all(f.get("advisory") is True for f in findings)

    def test_five_expected_rule_ids_present(self):
        expected = {
            "PDF_SCANNED_NO_ALT",
            "PDF_SCANNED_STRUCTURE",
            "PDF_SCANNED_READING_ORDER",
            "PDF_SCANNED_HEADINGS",
            "PDF_SCANNED_LANGUAGE",
        }
        findings = pvr.findings_from_layouts([_make_page()])
        assert {f["ruleId"] for f in findings} == expected

    def test_wcag_criteria_covered(self):
        findings = pvr.findings_from_layouts([_make_page()])
        wcags = {f["wcag"] for f in findings}
        assert "1.1.1 Non-text Content" in wcags
        assert "1.3.1 Info and Relationships" in wcags
        assert "1.3.2 Meaningful Sequence" in wcags
        assert "2.4.6 Headings and Labels" in wcags
        assert "3.1.1 Language of Page" in wcags

    def test_no_duplicate_rule_ids(self):
        findings = pvr.findings_from_layouts([_make_page(), _make_page(2)])
        rule_ids = [f["ruleId"] for f in findings]
        assert len(rule_ids) == len(set(rule_ids))

    def test_detail_contains_page_count_singular(self):
        findings = pvr.findings_from_layouts([_make_page()])
        for f in findings:
            assert "1 page" in f["detail"]

    def test_detail_contains_page_count_plural(self):
        pages = [_make_page(i) for i in range(1, 4)]
        findings = pvr.findings_from_layouts(pages)
        for f in findings:
            assert "3 pages" in f["detail"]

    def test_detail_mentions_scanned_or_untagged(self):
        findings = pvr.findings_from_layouts([_make_page()])
        for f in findings:
            assert "scanned" in f["detail"].lower() or "untagged" in f["detail"].lower()

    def test_each_finding_has_required_keys(self):
        required = {"ruleId", "wcag", "severity", "advisory", "detail"}
        findings = pvr.findings_from_layouts([_make_page()])
        for f in findings:
            assert required.issubset(f.keys()), f"Missing keys in {f}"

    def test_filename_param_accepted(self):
        # filename is accepted without raising even though not embedded in findings
        findings = pvr.findings_from_layouts([_make_page()], filename="doc.pdf")
        assert len(findings) == 5


# ══ 2. Empty / edge-case inputs ═════════════════════════════════════════════

class TestEdgeCases:
    def test_empty_pages_returns_empty_list(self):
        assert pvr.findings_from_layouts([]) == []

    def test_none_equivalent_empty_returns_empty(self):
        assert pvr.findings_from_layouts([]) == []

    def test_single_page_returns_five_findings(self):
        findings = pvr.findings_from_layouts([_make_page(1)])
        assert len(findings) == 5

    def test_many_pages_still_five_findings(self):
        pages = [_make_page(i) for i in range(1, 10)]
        findings = pvr.findings_from_layouts(pages)
        assert len(findings) == 5

    def test_findings_are_independent_of_page_count_beyond_one(self):
        one = pvr.findings_from_layouts([_make_page()])
        eight = pvr.findings_from_layouts([_make_page(i) for i in range(1, 9)])
        assert {f["ruleId"] for f in one} == {f["ruleId"] for f in eight}


# ══ 3. Scanner wiring guard ══════════════════════════════════════════════════

class TestScannerWiring:
    def test_pdf_vision_review_imported_in_scanner(self):
        scanner_path = ROOT / "api" / "scanner.py"
        src = scanner_path.read_text()
        assert "import pdf_vision_review" in src, (
            "pdf_vision_review not imported in scanner.py — Tier B wiring is missing"
        )

    def test_findings_from_layouts_called_in_scanner(self):
        scanner_path = ROOT / "api" / "scanner.py"
        src = scanner_path.read_text()
        assert "findings_from_layouts" in src, (
            "findings_from_layouts not called in scanner.py — Tier B wiring is missing"
        )

    def test_tier_b_print_present_in_scanner(self):
        scanner_path = ROOT / "api" / "scanner.py"
        src = scanner_path.read_text()
        assert "Tier B" in src, (
            "Tier B print/log statement not found in scanner.py"
        )

    def test_tier_b_findings_injected_into_raw_issues(self):
        scanner_path = ROOT / "api" / "scanner.py"
        src = scanner_path.read_text()
        # The wiring block must extend raw["issues"] with Tier B findings
        assert '_tier_b' in src and 'raw["issues"]' in src, (
            "Tier B findings not injected into raw['issues'] in scanner.py"
        )


# ══ 4. Module-level structural guards ════════════════════════════════════════

class TestModuleStructure:
    def test_module_exposes_findings_from_layouts(self):
        assert callable(pvr.findings_from_layouts)

    def test_scanned_rules_constant_has_five_entries(self):
        assert len(pvr._SCANNED_RULES) == 5

    def test_each_scanned_rule_is_three_tuple(self):
        for entry in pvr._SCANNED_RULES:
            assert len(entry) == 3, f"Expected 3-tuple, got {entry}"

    def test_all_rule_ids_start_with_pdf_scanned(self):
        for rule_id, _, _ in pvr._SCANNED_RULES:
            assert rule_id.startswith("PDF_SCANNED_"), (
                f"{rule_id} does not start with PDF_SCANNED_"
            )

    def test_all_wcag_strings_contain_criterion_number(self):
        import re
        for _, wcag, _ in pvr._SCANNED_RULES:
            assert re.search(r'\d+\.\d+\.\d+', wcag), (
                f"WCAG string '{wcag}' does not contain a criterion number"
            )
