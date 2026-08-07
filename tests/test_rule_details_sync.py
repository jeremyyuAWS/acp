"""The SPA's per-rule detail must be GENERATED from docs/rules/*.md, never retyped.

Same contract as test_scope_presets_frontend_sync.py, for a second generated module. The prose
here is the answer to "what does ACP actually check for 1.3.1 on DOCX" — the text an engineer
maintains beside the detector — and the copy in the UI is the one a CUSTOMER reads. So it is the
copy that must not go stale.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
GEN = ROOT / "scripts" / "gen_rule_details.py"
DOCS = ROOT / "docs" / "rules"
sys.path.insert(0, str(ROOT / "scripts"))
from gen_rule_details import OUTS  # noqa: E402

sys.path.insert(0, str(ROOT / "api"))


def _run(*args: str) -> subprocess.CompletedProcess:
    """Read the GENERATOR's exit status, never a pipeline's — CLAUDE.md, 'Verify before you
    diagnose'. A stale-file check that cannot fail is indistinguishable from one that passed."""
    return subprocess.run([sys.executable, str(GEN), *args],
                          capture_output=True, text=True, cwd=str(ROOT))


_ID = r"[A-Za-z0-9._-]+"


def _details_block(js: str) -> str:
    """Just the RULE_DETAILS object. RULES_BY_SC below it has the same `  "key":` shape, so an
    unbounded scan reports 45 rules for 36 docs."""
    m = re.search(r"export const RULE_DETAILS = \{(.*?)^\}", js, re.M | re.S)
    assert m, "RULE_DETAILS not found in the generated module"
    return m.group(1)


def test_generated_files_are_current():
    r = _run("--check")
    assert r.returncode == 0, (
        "a generated ruleDetails.js is stale — a rule doc changed without regenerating it.\n"
        "Fix: python scripts/gen_rule_details.py\n\n" + r.stderr)


@pytest.mark.parametrize("out", OUTS, ids=lambda p: p.parent.parent.name)
def test_each_spa_has_its_copy(out):
    """Named per SPA so a failure says WHICH drifted — the lesson from #150, where two different
    staleness causes landed in one run and a single aggregate message hid the second."""
    assert out.exists(), f"{out.relative_to(ROOT)} was never generated"
    r = _run("--stdout")
    assert r.returncode == 0, r.stderr
    assert out.read_text() == r.stdout, f"{out.relative_to(ROOT)} is stale"


def test_both_spas_are_byte_identical():
    texts = {o.relative_to(ROOT).as_posix(): o.read_text() for o in OUTS}
    assert len(set(texts.values())) == 1, "ruleDetails.js differs between SPAs: " + ", ".join(texts)


def test_check_actually_fails_on_drift():
    """Without this, the guard above proves nothing."""
    out = OUTS[0]
    original = out.read_text()
    try:
        out.write_text(original.replace('severity: "CRITICAL"', 'severity: "TRIVIAL"', 1))
        assert _run("--check").returncode == 1, "--check passed on a file it should have rejected"
    finally:
        out.write_text(original)
    assert _run("--check").returncode == 0, "the drift test did not restore the file"


def test_every_rule_doc_reaches_the_spa():
    """No doc silently dropped. Derived on both sides rather than pinned to a count, which would
    go stale the next time a rule is documented."""
    docs = {p.stem for p in DOCS.glob("*.md") if p.stem != "README"}
    emitted = set(re.findall(rf'^  "({_ID})": \{{', _details_block(OUTS[0].read_text()), flags=re.M))
    assert emitted == docs, f"missing from the SPA: {sorted(docs - emitted)}"


def test_missing_remediation_prose_is_null_not_invented():
    """Six docs have no 'Fix mode rationale'. Those must emit null.

    A detail panel that fabricates the remediation story for a sixth of the catalog is worse than
    one that says nothing, because the reader cannot tell which sentences are real.
    """
    js = OUTS[0].read_text()
    assert "remediation: null," in js, "no rule emits a null remediation — the gap was papered over"
    documented = {p.stem for p in DOCS.glob("*.md")
                  if p.stem != "README" and "## Fix mode rationale" in p.read_text()}
    for m in re.finditer(rf'^  "({_ID})": \{{(.*?)^  \}},', _details_block(js), flags=re.M | re.S):
        rule, body = m.group(1), m.group(2)
        has_prose = "remediation: null," not in body
        assert has_prose == (rule in documented), (
            f"{rule}: emitted remediation prose does not match whether its doc has the section")


def test_tracked_17_is_the_backend_list():
    """The 17 is defined ONCE, in Python. This is the fifth number this product quotes and the
    only defence against a sixth is that nothing may retype it."""
    import assessment_policy as ap

    js = OUTS[0].read_text()
    m = re.search(r"export const TRACKED_17 = new Set\(\[(.*?)\]\)", js, re.S)
    assert m, "TRACKED_17 not emitted"
    emitted = set(re.findall(r'"(\d+\.\d+\.\d+)"', m.group(1)))
    assert emitted == set(ap.MOVA_TRACKED)
    assert len(emitted) == 17


def test_tracked_17_is_document_core_minus_the_three_viewer_criteria():
    """Pins the RELATIONSHIP, not a second copy of the list.

    17 = the 20-check document core minus 1.4.4, 1.4.10 and 1.4.12 — resize, reflow and text
    spacing, which are viewer behaviours rather than properties of a static document. If someone
    "restores" one as an oversight, this says why it was not.
    """
    import assessment_policy as ap

    doc_core = set(re.findall(
        r"'(\d+\.\d+\.\d+)'",
        (ROOT / "frontend" / "src" / "documents20.js").read_text()))
    assert len(doc_core) == 20, f"documents20.js no longer lists 20: {len(doc_core)}"
    assert doc_core - set(ap.MOVA_TRACKED) == {"1.4.4", "1.4.10", "1.4.12"}
