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
# api/ocr.py reads its tuning knobs from the environment by name; ACP_* is a config key, never
# a rule id, and no rule id starts with the product's own prefix.
_ENV_PREFIX = "ACP_"
_CHECK_MODULES = ("office_structure.py", "textchecks.py", "ocr.py")


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
            if rid.startswith(_ENV_PREFIX) or rid in gri._SEVERITIES or rid in indexed:
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
