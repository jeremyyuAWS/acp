"""Severity calibration guard — image-alt rules must be SERIOUS, not CRITICAL.

767 of 795 findings were CRITICAL before this rework; the recalibration downgrades
image alt-text findings (decorative-image blocker) from CRITICAL to SERIOUS because
missing alt text is a major barrier but rarely task-blocking on its own (a form with
no submit label, by contrast, IS task-blocking and stays CRITICAL).

These tests read the source files directly so they catch a regression the instant
a developer edits a severity string, without requiring a full scan run.
"""
from __future__ import annotations
import ast
import json
import re
import sys
from pathlib import Path

ACP = Path(__file__).resolve().parent.parent
API = ACP / "api"
sys.path.insert(0, str(API))


# ---------------------------------------------------------------------------
# scanner.py — HTML_IMG_MISSING_ALT must be SERIOUS
# ---------------------------------------------------------------------------

def _scanner_issues():
    """Parse scanner.py for all issues.append(...) calls and return a list of
    (ruleId, severity) tuples extracted from the string literals."""
    src = (API / "scanner.py").read_text()
    # Find ruleId/severity pairs in dict literals passed to issues.append
    pairs = re.findall(
        r'"ruleId":\s*"([^"]+)"[^}]*"severity":\s*"([^"]+)"',
        src
    )
    return pairs


def test_html_img_missing_alt_is_serious_not_critical():
    """HTML_IMG_MISSING_ALT must be SERIOUS (missing alt is a major barrier but
    not unconditionally task-blocking; a submit button with no label is CRITICAL)."""
    pairs = _scanner_issues()
    img_alt = [sev for rid, sev in pairs if rid == "HTML_IMG_MISSING_ALT"]
    assert img_alt, "HTML_IMG_MISSING_ALT not found in scanner.py — rule may have been renamed"
    for sev in img_alt:
        assert sev == "SERIOUS", (
            f"HTML_IMG_MISSING_ALT has severity {sev!r}; expected SERIOUS. "
            "Image alt-text is a major barrier (SERIOUS) not a task-blocker (CRITICAL)."
        )


def test_html_input_no_label_remains_critical():
    """HTML_INPUT_NO_LABEL must stay CRITICAL — an unlabelled form control
    prevents task completion for AT users."""
    pairs = _scanner_issues()
    label = [sev for rid, sev in pairs if rid == "HTML_INPUT_NO_LABEL"]
    assert label, "HTML_INPUT_NO_LABEL not found in scanner.py"
    for sev in label:
        assert sev == "CRITICAL", (
            f"HTML_INPUT_NO_LABEL has severity {sev!r}; expected CRITICAL."
        )


# ---------------------------------------------------------------------------
# rule-catalog.json — office alt-text entries must be SERIOUS
# ---------------------------------------------------------------------------

ALT_RULE_IDS = {"DOCX-ALT-001", "PPTX-ALT-001", "XLSX-ALT-001", "pdf.missing-alt-text"}


def _catalog_entries():
    catalog = json.loads((ACP / "config" / "rule-catalog.json").read_text())
    entries = []
    for fmt, rules in catalog.items():
        if fmt == "_meta":
            continue
        if isinstance(rules, list):
            for r in rules:
                if isinstance(r, dict):
                    entries.append((fmt, r.get("id", ""), r.get("severity", "")))
    return entries


def test_catalog_alt_rules_are_serious_not_critical():
    """DOCX-ALT-001, PPTX-ALT-001, XLSX-ALT-001, pdf.missing-alt-text must be
    SERIOUS in rule-catalog.json.  They were CRITICAL before the 2026-08 rework."""
    entries = _catalog_entries()
    found = {rule_id: sev for _, rule_id, sev in entries if rule_id in ALT_RULE_IDS}
    missing = ALT_RULE_IDS - set(found)
    assert not missing, f"Alt-text rules missing from catalog: {missing}"
    for rule_id, sev in found.items():
        assert sev == "SERIOUS", (
            f"{rule_id} has severity {sev!r} in rule-catalog.json; expected SERIOUS. "
            "Office alt-text findings are major barriers (SERIOUS), not task-blockers (CRITICAL)."
        )


def test_no_alt_rule_is_critical():
    """Belt-and-suspenders: no rule whose id contains 'ALT' or 'alt' may be CRITICAL."""
    entries = _catalog_entries()
    violations = [
        (fmt, rule_id, sev)
        for fmt, rule_id, sev in entries
        if ("ALT" in rule_id.upper() or "alt" in rule_id.lower()) and sev == "CRITICAL"
    ]
    assert not violations, (
        "The following alt-text catalog rules are still CRITICAL (should be SERIOUS): "
        + str(violations)
    )
