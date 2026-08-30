"""The rules every labelled corpus has to follow, enforced in one place for all of them.

WHY THIS EXISTS. Three corpora were written in quick succession — xlsx, then pptx, then pdf — and
the discipline GREW as they went. Each new one learned something the previous had not thought to
assert, and nothing carried the lesson backwards. By the end, the newest corpus checked six
properties and the oldest checked three, which is exactly the shape of drift the repo's other
guards exist to stop: the weakest link is the one nobody is looking at, because attention follows
whatever was written last.

So the invariants live here, parametrised over every corpus, and a fourth format inherits all of
them on the day it joins `CORPORA` rather than on the day someone remembers.

WHAT A CONTROL IS, AND THE FALSE ALARM THAT DEFINED IT. `test_pptx_corpus` and `test_pdf_corpus`
each assert their violation and adversarial criterion sets are EQUAL, keyed on `kind ==
"adversarial"`. Applied to xlsx that reports 1.4.3 as an uncontrolled violation — and it is not:
xlsx uses a four-way taxonomy (violation / adversarial / clean / edge) and its 1.4.3 control is
`contrast-ok`, labelled `clean`. The coverage was there; only the word differed.

That near-miss is why the rule here is stated by ROLE rather than by label: a control is any
NON-violation fixture declaring the criterion. Keying on the label would have reported a gap in a
corpus that has none, and "the guard found a problem" is the hardest kind of false alarm to walk
back — someone would have "fixed" a corpus that was already correct.

THE SIX RULES, and what each one protects:

 1. every violation has a control      — without it, nothing measures false positives
 2. every control has a violation      — a control alone proves only that silence is possible
 3. DECLARED matches the fixtures      — the coverage report reads the constant, not the files
 4. DECLARED sits inside the preset    — otherwise coverage inflates against a denominator
                                         that does not contain it
 5. BASELINE equals DECLARED           — a baseline below reality is a ratchet with slack
 6. no expectation the engine can't emit — a manifest bug that reads as a product bug forever
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))
sys.path.insert(0, str(ROOT / "scripts"))

import corpus_expectations as ce  # noqa: E402

PRESET = "acp-core-17"

# (format, generator module). docx is deliberately absent: gen_sc_corpus predates the constant-
# plus-manifest shape these rules are written against — it returns expectations from each build
# function and has no DECLARED — so it is covered by tests/test_docx_corpus_regression_gate.py
# instead. Adding it here would mean loosening every rule below to accommodate one exception.
CORPORA = [("xlsx", "gen_xlsx_corpus"), ("pptx", "gen_pptx_corpus"), ("pdf", "gen_pdf_corpus")]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def built():
    """Every corpus built once: {format: (module, manifest, problems)}."""
    out = {}
    for fmt, name in CORPORA:
        gen = _load(name)
        with tempfile.TemporaryDirectory(prefix=f"acp-inv-{fmt}-") as d:
            manifest, problems = gen.build_all(Path(d) / "docs")
        out[fmt] = (gen, manifest, problems)
    return out


def _roles(manifest) -> tuple[set[str], set[str]]:
    """(criteria with a violation fixture, criteria with a control fixture).

    A control is any fixture whose kind is not "violation" — see the module docstring. xlsx labels
    some of its controls `clean` and `edge`; pptx and pdf use `adversarial` throughout. Reading
    the role rather than the word is what lets one rule cover all three.
    """
    violation = {sc for r in manifest if r["kind"] == "violation" for sc in r["expect"]}
    control = {sc for r in manifest if r["kind"] != "violation" for sc in r["expect"]}
    return violation, control


@pytest.mark.parametrize("fmt", [f for f, _ in CORPORA])
def test_every_violation_has_a_control(built, fmt):
    """A corpus that grows a violation without a control has quietly stopped measuring false
    positives for that criterion, and nothing else in the suite would notice. A detector that
    fires on everything would still score full marks."""
    _gen, manifest, _problems = built[fmt]
    violation, control = _roles(manifest)
    assert not (violation - control), (
        f"{fmt}: violations with no clean counterpart: {sorted(violation - control)} — nothing "
        f"measures false positives for these")


@pytest.mark.parametrize("fmt", [f for f, _ in CORPORA])
def test_every_control_has_a_violation(built, fmt):
    """The other direction, and the weaker of the two but still worth pinning: a control on its
    own proves the detector CAN stay silent, not that it ever speaks. A criterion covered only by
    a clean fixture would count toward coverage while testing nothing that can fail."""
    _gen, manifest, _problems = built[fmt]
    violation, control = _roles(manifest)
    assert not (control - violation), (
        f"{fmt}: controls with no violation counterpart: {sorted(control - violation)} — these "
        f"criteria are only ever exercised clean")


@pytest.mark.parametrize("fmt", [f for f, _ in CORPORA])
def test_declared_matches_the_fixtures(built, fmt):
    """gen_fixture_coverage reads each corpus's DECLARED constant rather than building the
    fixtures, which is cheap and correct only while the constant is held honest. Without this the
    coverage report is a claim about a tuple somebody typed."""
    gen, manifest, _problems = built[fmt]
    actual = {sc for r in manifest for sc in r["expect"]}
    assert actual == set(gen.DECLARED), (
        f"{fmt}: DECLARED says {sorted(gen.DECLARED)} but the fixtures declare {sorted(actual)}")


@pytest.mark.parametrize("fmt", [f for f, _ in CORPORA])
def test_declared_sits_inside_the_shipped_preset(built, fmt):
    """A fixture may legitimately EXERCISE a criterion outside the preset — pdf's contrast
    violation also raises 1.4.6, and its heading fixtures brush 2.4.1 — but DECLARING one would
    inflate coverage against a denominator that does not contain it."""
    gen, _manifest, _problems = built[fmt]
    applicable = {sc for sc, fmts in ce.pol.SCOPE_PRESETS[PRESET].items() if fmt in fmts}
    assert set(gen.DECLARED) <= applicable, (
        f"{fmt}: declared but not applicable in {PRESET!r}: "
        f"{sorted(set(gen.DECLARED) - applicable)}")


@pytest.mark.parametrize("fmt", [f for f, _ in CORPORA])
def test_the_baseline_has_no_slack(built, fmt):
    """A BASELINE below actual coverage is a ratchet with give in it: a fixture could be deleted
    and `gen_fixture_coverage --check` would still pass. Pinned equal so the guard bites on the
    first loss rather than the second."""
    gen, _manifest, _problems = built[fmt]
    gfc = _load("gen_fixture_coverage")
    assert gfc.BASELINE[fmt] == len(gen.DECLARED), (
        f"BASELINE[{fmt!r}] is {gfc.BASELINE[fmt]} but the corpus declares {len(gen.DECLARED)}")


@pytest.mark.parametrize("fmt", [f for f, _ in CORPORA])
def test_no_expectation_the_engine_could_never_emit(built, fmt):
    """Each generator validates this itself; asserting it here too means a NEW corpus cannot ship
    without the check, rather than being trusted to have copied it.

    The failure it prevents is nasty because it inverts blame: a manifest expecting PASS on a
    review-lane pair reports a false failure on every run, and it reads as a product bug until
    somebody re-derives the lane by hand."""
    _gen, manifest, problems = built[fmt]
    assert not problems, f"{fmt}: {problems}"
    for row in manifest:
        for sc, verdict in row["expect"].items():
            allowed = ce.possible_verdicts(sc, fmt)
            assert verdict in allowed, (
                f"{fmt}/{row['name']} expects {sc}={verdict}, but ({sc}, {fmt}) can only emit "
                f"{sorted(allowed)}")
            if verdict == "PASS":
                assert ce.can_ever_pass(sc, fmt), (
                    f"{fmt}/{row['name']} claims PASS on {sc}, which this format cannot certify")


# ── the taxonomy difference itself, pinned so the rule above keeps its reason ─────

def test_the_corpora_do_not_agree_on_fixture_kinds_and_that_is_fine(built):
    """Pins the fact the module docstring turns on: xlsx uses four kinds, the others two. If they
    are ever unified, the role-based `_roles` helper stops being load-bearing and this test is the
    reminder that the reasoning behind it changed — not a regression to fix by editing the
    corpora back apart.

    Asserted loosely, on the one property that matters: every corpus has a `violation` kind, and
    at least one corpus uses a control label other than `adversarial`."""
    kinds = {fmt: {r["kind"] for r in manifest} for fmt, (_g, manifest, _p) in built.items()}
    for fmt, ks in kinds.items():
        assert "violation" in ks, f"{fmt} has no violation fixtures at all"
    controls = {k for ks in kinds.values() for k in ks} - {"violation"}
    assert controls - {"adversarial"}, (
        "every corpus now labels its controls 'adversarial' — the role-based reading in _roles is "
        f"no longer load-bearing (kinds seen: {kinds})")


def test_every_corpus_in_the_coverage_report_is_covered_by_these_rules():
    """The rules are only worth anything if they apply to every corpus that counts toward the
    number. A new format added to gen_fixture_coverage.GENERATORS but not to CORPORA here would
    raise coverage while inheriting none of the discipline above."""
    gfc = _load("gen_fixture_coverage")
    counted = set(gfc.GENERATORS) - {"docx"}      # docx: see the CORPORA comment
    assert counted == {f for f, _ in CORPORA}, (
        f"corpora counted by gen_fixture_coverage but not checked here: "
        f"{sorted(counted - {f for f, _ in CORPORA})}")
