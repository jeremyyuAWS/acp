"""ADR 0002 §1/§4 enforcement: the rule-registry contract.

Every rule in config/rule-catalog.json must carry the full required field set
with valid values, a unique id, a source path that resolves to a real file in
this repo, and a docs/rules/RULE-ID.md file with the required sections. This is
the CI gate ADR 0002 names — without it the registry and docs drift silently
(they already had: stale source paths and 27 missing docs before this landed).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
CATALOG = json.loads((ACP / "config/rule-catalog.json").read_text())

RULES = [r for fmt, rules in CATALOG.items() if fmt != "_meta" for r in rules]
IDS = [r["id"] for r in RULES]

REQUIRED = ["id", "title", "description", "wcag", "wcag_sc", "wcag_display",
            "wcag_level", "severity", "fix_mode", "source"]
SEVERITIES = {"CRITICAL", "SERIOUS", "MODERATE", "MINOR"}
FIX_MODES = {"auto", "ai-assisted", "human-only"}
LEVELS = {"A", "AA"}
DOC_SECTIONS = ["## What it checks", "## Why it matters", "## Unit test recipe",
                "## Failure modes"]


def test_catalog_has_rules():
    assert len(RULES) >= 30, f"catalog suspiciously small: {len(RULES)} rules"


def test_ids_unique_across_whole_catalog():
    dupes = {i for i in IDS if IDS.count(i) > 1}
    assert not dupes, f"duplicate rule ids: {sorted(dupes)}"


@pytest.mark.parametrize("rule", RULES, ids=IDS)
def test_required_fields(rule):
    missing = [f for f in REQUIRED if not str(rule.get(f, "")).strip()]
    assert not missing, f"{rule.get('id', '?')}: missing/empty {missing}"


@pytest.mark.parametrize("rule", RULES, ids=IDS)
def test_field_values(rule):
    assert len(rule["title"]) <= 80, "title over 80 chars"
    assert len(rule["description"]) <= 300, "description over 300 chars"
    assert rule["severity"] in SEVERITIES, f"bad severity {rule['severity']}"
    assert rule["fix_mode"] in FIX_MODES, f"bad fix_mode {rule['fix_mode']}"
    assert rule["wcag_level"] in LEVELS, f"bad wcag_level {rule['wcag_level']}"
    assert re.fullmatch(r"SC_\d+_\d+_\d+", rule["wcag"]), f"bad rubric key {rule['wcag']}"
    assert re.fullmatch(r"\d+\.\d+\.\d+", rule["wcag_sc"]), f"bad SC number {rule['wcag_sc']}"
    # The rubric key and the dotted SC must agree — they feed different surfaces
    # (scoring vs display) and a mismatch mislabels findings.
    assert rule["wcag"] == "SC_" + rule["wcag_sc"].replace(".", "_"), \
        f"wcag {rule['wcag']} does not match wcag_sc {rule['wcag_sc']}"


@pytest.mark.parametrize("rule", RULES, ids=IDS)
def test_source_file_exists(rule):
    assert (ACP / rule["source"]).is_file(), \
        f"{rule['id']}: source does not resolve in-repo: {rule['source']}"


@pytest.mark.parametrize("rule", RULES, ids=IDS)
def test_rule_doc_exists_with_required_sections(rule):
    doc = ACP / "docs/rules" / f"{rule['id']}.md"
    assert doc.is_file(), f"{rule['id']}: missing docs/rules/{rule['id']}.md (ADR 0002 §4)"
    text = doc.read_text()
    missing = [s for s in DOC_SECTIONS if s not in text]
    assert not missing, f"{rule['id']}: doc missing sections {missing}"
