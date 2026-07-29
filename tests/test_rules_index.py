"""Contract: the generated rules/ index must list every first-party rule that actually runs.

scripts/gen_rules_index.py reads the first-party checks out of the code precisely so the index
"cannot drift from what actually runs" (its own docstring). But it reads them by PAIRING literals
within a syntactic grouping, so a check that builds its findings in a shape the pairing doesn't
know about vanishes from the index silently — no error, just a rule that stops being documented.
That is what happened when pdf_contrast_checks moved to a table of rows driving a loop: both
PDF_LOW_CONTRAST_AA and _AAA disappeared from rules/wcag-1-4-3 and rules/wcag-1-4-6.

So the rule ids are re-derived here the crude way — every rule-id-shaped string literal in the
modules the generator parses — and compared with what it indexed. The two derivations are
independent by construction: one is structural, one is textual, and a shape only the parser
understands cannot fool both.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent

# SHOUTY_CASE with at least one underscore — the shape every first-party rule id has
# (DOCX_HEADING_SKIP, PDF_LOW_CONTRAST_AA). Excludes bare severities and hex/placeholder
# literals ("FFFFFF"), which carry no underscore.
_RULE_ID_LITERAL = re.compile(r'"([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)"')
# api/ocr.py reads its tuning knobs from the environment by name, and api/scanner.py sets the
# .NET host's; ACP_*/DOTNET_* are config keys, never rule ids. Every real rule id is prefixed
# with the format it applies to (DOCX_/PPTX_/XLSX_/PDF_/HTML_), so neither namespace can
# collide — this excludes environment keys, not rules that failed to reach the index.
_ENV_PREFIXES = ("ACP_", "DOTNET_")
# scanner.py is the HTML engine. It was absent from both the generator and this cross-check,
# so all 32 HTML_* rules were undocumented and nothing noticed — the precise failure this file
# exists to catch, hidden by the module list rather than by the pairing.
_CHECK_MODULES = ("office_structure.py", "textchecks.py", "ocr.py", "scanner.py")


@pytest.fixture(scope="module")
def gri():
    spec = importlib.util.spec_from_file_location(
        "acp_gen_rules_index", ACP / "scripts" / "gen_rules_index.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _indexed_ids(gri) -> set[str]:
    return {chk["id"] for checks in gri.load_first_party().values() for chk in checks}


def test_every_first_party_rule_id_reaches_the_index(gri):
    indexed = _indexed_ids(gri)
    missing = []
    for mod in _CHECK_MODULES:
        source = (ACP / "api" / mod).read_text()
        for rid in sorted(set(_RULE_ID_LITERAL.findall(source))):
            if rid.startswith(_ENV_PREFIXES) or rid in gri._SEVERITIES or rid in indexed:
                continue
            missing.append(f"api/{mod}: {rid}")
    assert not missing, (
        "these rules run but gen_rules_index.py cannot see them, so rules/ silently stops "
        "documenting them — teach _rules_in the shape that emits them:\n" + "\n".join(missing))


def test_the_index_never_lists_a_severity_as_a_rule(gri):
    """A severity sits beside the rule id in every finding shape and is SHOUTY_CASE too, so a
    loose pairing turns it into a phantom rule called `SERIOUS`, complete with a source path."""
    phantoms = sorted(_indexed_ids(gri) & gri._SEVERITIES)
    assert not phantoms, f"severity words indexed as first-party rules: {phantoms}"


# ── rules/README.md ownership table ───────────────────────────────────────────
# The table's criteria list and Engines column are generated; its Owner column is not.
# It drifted for exactly as long as all three were left to a human: 18 of 38 criteria, and
# format lists that had stopped being true (2.4.6 read html-only while four other formats
# checked it). These pin the split — derived columns regenerate, a claim survives.

def _readme() -> str:
    return (ACP / "rules" / "README.md").read_text()


def test_ownership_table_lists_every_criterion_with_the_right_engines(gri):
    import json
    index = {e["sc"]: e for e in json.loads((ACP / "rules" / "index.json").read_text())}
    rows = dict(gri._OWNER_ROW.findall(_readme()))
    listed = {slug.replace("-", ".") for slug in rows}
    assert listed == set(index), (
        "ownership table is out of step with rules/index.json — "
        f"missing {sorted(set(index) - listed)}, stale {sorted(listed - set(index))}. "
        "Run python scripts/gen_rules_index.py.")
    # …and the Engines cell says what the index says, not what it said when someone typed it.
    text = _readme()
    for sc, entry in index.items():
        row = next(ln for ln in text.splitlines()
                   if f"](./{entry['dir']}/)" in ln)
        assert f"| {', '.join(entry['engines'])} |" in row, (
            f"{sc}: table says {row.split('|')[3].strip()!r}, index says "
            f"{', '.join(entry['engines'])!r}")


def test_regeneration_preserves_a_claimed_owner(gri, tmp_path, monkeypatch):
    """The whole reason the table is only PARTLY generated. If a regeneration wiped the
    Owner column, the file would be generated in practice and nobody would claim anything."""
    readme = tmp_path / "README.md"
    rows = "\n".join([
        "| Success Criterion | Level | Engines | Owner |",
        "|-------------------|-------|---------|-------|",
        "| [1.1.1 Non-text Content](./wcag-1-1-1/) | A | docx | Ada L. |",
        "| [2.4.6 Headings and Labels](./wcag-2-4-6/) | AA | html | _unassigned_ |",
    ])
    readme.write_text(f"prose above\n\n{gri._OWNERSHIP_BEGIN}\n{rows}\n{gri._OWNERSHIP_END}\n\nprose below\n")
    monkeypatch.setattr(gri, "OUT", tmp_path)
    # 1.1.1 keeps its owner even though its engines changed; the new criterion starts unowned.
    index_rows = [("1.1.1", "Non-text Content", "A", ["docx", "html"], "wcag-1-1-1"),
                  ("2.4.6", "Headings and Labels", "AA", ["html"], "wcag-2-4-6"),
                  ("3.1.1", "Language of Page", "A", ["html"], "wcag-3-1-1")]
    criteria, claimed = gri.update_readme(index_rows)
    out = readme.read_text()
    assert (criteria, claimed) == (3, 1)
    assert "| Ada L. |" in out, "a claimed owner was lost to regeneration"
    assert "| A | docx, html | Ada L. |" in out, "engines must regenerate while the owner stays"
    assert "[3.1.1 Language of Page](./wcag-3-1-1/) | A | html | _unassigned_ |" in out
    assert out.startswith("prose above") and out.endswith("prose below\n"), "prose was disturbed"


def test_missing_markers_fail_loudly_rather_than_silently_skipping(gri, tmp_path, monkeypatch):
    readme = tmp_path / "README.md"
    readme.write_text("prose with no markers and a table someone will forget to update\n")
    monkeypatch.setattr(gri, "OUT", tmp_path)
    with pytest.raises(SystemExit, match="missing the ownership-table markers"):
        gri.update_readme([("1.1.1", "Non-text Content", "A", ["docx"], "wcag-1-1-1")])
