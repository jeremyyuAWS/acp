"""config/rule-catalog.json's `source` field points at the code that implements each rule.

THIRTY-ONE OF SEVENTY POINTED AT NOTHING. The .NET analysers were catalogued under
`digital-accessibility/…`, which is not a directory in this repository; they live at
`engine/office-analysers/…`. The PDF rules were catalogued under
`deploy/public/vendor/worker-python/…`, which does not exist either; they live at
`engine/pdf-analyser/…`. Both roots moved and the catalog did not follow.

WHY A DEAD POINTER HERE COSTS MORE THAN A DEAD POINTER USUALLY DOES. CLAUDE.md's standing
instruction for this repository is to check a rule against its SOURCE rather than against its
catalog description — the entry for XLSX-LANG-001 describes a styles.xml lookup and the rule reads
the core properties, so a fixture written from the description detects nothing. `source` is the
field that instruction depends on. Following it landed nowhere for 31 of the 70 rules, which turns
"read the rule" into "find the rule first", and the reader who gives up reads the description
instead.

The same shape is already recorded twice in CLAUDE.md: a stale header in `tests/engines.py` saying
the PDF engine "lives outside this repo entirely" (false for months, contradicted by its own code
twelve lines below), and a catalog description that contradicts its own rule. This is the third,
and unlike prose it is mechanically checkable — so it is checked here rather than corrected and
left to drift again.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = ROOT / "config" / "rule-catalog.json"
FORMATS = ("docx", "pptx", "xlsx", "pdf")


@pytest.fixture(scope="module")
def catalog() -> dict:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def _rules(catalog):
    for fmt in FORMATS:
        for rule in catalog[fmt]:
            yield fmt, rule


def test_every_source_path_exists(catalog):
    """THE ONE THAT WAS BROKEN. Named per rule so the failure says which, rather than a count."""
    missing = [(fmt, rule["id"], rule["source"])
               for fmt, rule in _rules(catalog)
               if not (ROOT / rule["source"]).exists()]
    assert not missing, (
        "rule-catalog.json points at files that do not exist:\n" +
        "\n".join(f"  {fmt:5} {rid:22} -> {src}" for fmt, rid, src in missing) +
        "\nCLAUDE.md tells a reader to check a rule against its source rather than its "
        "description; a dead pointer here is what sends them back to the description.")


def test_every_rule_declares_a_source(catalog):
    """An absent `source` passes the check above vacuously — `(ROOT / "").exists()` is true for
    the repository root. Kept separate so that hole cannot open quietly."""
    for fmt, rule in _rules(catalog):
        assert rule.get("source", "").strip(), f"{fmt} {rule['id']} declares no source"


def test_the_source_files_are_not_the_repository_root(catalog):
    """The specific way the check above could pass while meaning nothing."""
    for fmt, rule in _rules(catalog):
        resolved = (ROOT / rule["source"]).resolve()
        assert resolved != ROOT.resolve(), f"{fmt} {rule['id']} resolves to the repo root"
        assert resolved.is_file(), f"{fmt} {rule['id']} -> {rule['source']} is not a file"


def test_the_two_engine_roots_are_where_the_catalog_says(catalog):
    """The roots themselves, asserted once. If an engine moves again this fails with the reason
    rather than as 25 separate missing-file lines."""
    for root in ("engine/office-analysers", "engine/pdf-analyser"):
        assert (ROOT / root).is_dir(), (
            f"{root} is gone — an engine has moved and every catalog `source` under it is now a "
            f"dead pointer")


def test_the_stale_roots_are_not_referenced_again(catalog):
    """The two roots that were wrong, named so a copy-paste from an old entry fails loudly."""
    text = CATALOG_PATH.read_text(encoding="utf-8")
    for stale in ("digital-accessibility/", "deploy/public/vendor/worker-python/"):
        assert stale not in text, (
            f"{stale} is back in rule-catalog.json and is not a path in this repository")


def test_wcag_and_wcag_sc_agree(catalog):
    """`wcag` is the rubric key (SC_1_1_1), `wcag_sc` the dotted number (1.1.1). They are two
    spellings of one fact, and nothing was checking they stayed the same fact."""
    for fmt, rule in _rules(catalog):
        derived = rule["wcag"].replace("SC_", "").replace("_", ".")
        assert derived == rule["wcag_sc"], (
            f"{fmt} {rule['id']}: wcag={rule['wcag']} implies {derived}, "
            f"wcag_sc says {rule['wcag_sc']}")


def test_rule_ids_are_unique_across_formats(catalog):
    seen: dict[str, str] = {}
    for fmt, rule in _rules(catalog):
        assert rule["id"] not in seen, (
            f"{rule['id']} appears in both {seen[rule['id']]} and {fmt}")
        seen[rule["id"]] = fmt


def test_the_catalog_still_has_rules_for_every_format(catalog):
    """ANTI-VACUOUS. Every test above passes trivially on an empty catalog, and an empty format
    is exactly what a bad merge of a 70-rule JSON file produces."""
    for fmt in FORMATS:
        assert len(catalog[fmt]) >= 10, f"{fmt} has only {len(catalog[fmt])} rules"
