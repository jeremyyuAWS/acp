"""Every DECLARED pair is actually swept by its corpus's violation and control lists.

THE HOLE THIS CLOSES. Each corpus counts coverage from its `DECLARED` tuple, but the tests that
prove a declaration — `test_each_violation_fixture_is_actually_detected` and
`test_each_adversarial_fixture_stays_silent` — are parametrised from lists typed by hand. The two
are not connected. Adding a criterion to `DECLARED` therefore raises the number
`gen_fixture_coverage.py` reports whether or not anything checks it, which is the exact failure
those corpora's own docstrings warn about: "an undetected fixture would raise the number the
report gives without raising what it measures."

FOUND BY A BITE CHECK, not by reading. While adding the 1.4.5 pairs, both fixtures were
deliberately broken — the violation image swapped for a two-word logo (under `ocr._MIN_WORDS`),
then the control swapped for the image of prose. The suite stayed green both times, because the
new pairs were in `DECLARED` and in neither sweep list. Three formats would have gained a
declared pair and no assertion. The guard that would have caught it did not exist, so it is this
file.

WHY NOT DERIVE THE LISTS INSTEAD. Because the mapping from a criterion to the fixture that seeds
it is real information the corpus author has and the machine does not — several criteria share a
fixture (xlsx `form-control` seeds both 4.1.2 and 2.1.2) and several fixtures deliberately seed
none. Deriving would either guess or force a naming convention. Asserting COVERAGE of a
hand-written list keeps the author's mapping and removes only the failure mode where they forget
to add one.

PAIRS PROVEN SOMEWHERE ELSE still have to say so, by name, with a reason — see PROVEN_ELSEWHERE.
An escape hatch that needs a sentence is one somebody reads; a silent omission is not.
"""
from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))
sys.path.insert(0, str(ROOT / "scripts"))

CORPORA = {
    "xlsx": ("gen_xlsx_corpus", "test_xlsx_corpus.py"),
    "pptx": ("gen_pptx_corpus", "test_pptx_corpus.py"),
    "pdf": ("gen_pdf_corpus", "test_pdf_corpus.py"),
}

# A declared pair whose proof lives outside its corpus's own two sweeps. Each entry names WHERE,
# so the claim is checkable rather than merely excused.
PROVEN_ELSEWHERE = {
    ("xlsx", "1.3.3"): "tests/test_sensory_corpus.py — one shared file for all three formats, "
                       "because 1.3.3 is decided by the prose rather than the container",
    ("pptx", "1.3.3"): "tests/test_sensory_corpus.py — same shared file",
    ("pdf", "1.3.3"): "tests/test_sensory_corpus.py — same shared file",
    ("xlsx", "2.4.2"): "DECLARED_ENGINE — proven by the .NET analyser in "
                       "test_the_engine_confirms_the_declared_pairs, skipped on a bare checkout",
    ("xlsx", "3.1.1"): "DECLARED_ENGINE — same .NET-gated sweep",
}


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _swept(test_file: str) -> dict[str, set[str]]:
    """The (criterion) sets named in each parametrised sweep, read from the SOURCE rather than by
    importing — importing a corpus test module builds every fixture, and this file only needs to
    know which names were typed into the decorators.

    Keyed by the decorated function's name so a renamed sweep fails loudly here instead of
    silently contributing nothing."""
    tree = ast.parse((ROOT / "tests" / test_file).read_text())
    out: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for dec in node.decorator_list:
            if not (isinstance(dec, ast.Call) and len(dec.args) == 2):
                continue
            argnames = dec.args[0]
            if not (isinstance(argnames, ast.Constant) and argnames.value.startswith("name,sc")):
                continue
            scs: set[str] = set()
            for elt in getattr(dec.args[1], "elts", []):
                parts = getattr(elt, "elts", [])
                # ("fixture-name", "1.4.5") and ("fixture-name", "1.4.5", True) both appear
                if len(parts) >= 2 and isinstance(parts[1], ast.Constant):
                    scs.add(parts[1].value)
            out.setdefault(node.name, set()).update(scs)
    return out


VIOLATION_SWEEP = "test_each_violation_fixture_is_actually_detected"
CONTROL_SWEEP = "test_each_adversarial_fixture_stays_silent"


@pytest.mark.parametrize("fmt", sorted(CORPORA))
@pytest.mark.parametrize("sweep", [VIOLATION_SWEEP, CONTROL_SWEEP])
def test_every_declared_pair_is_named_in_both_sweeps(fmt, sweep):
    """BOTH lists, checked SEPARATELY — and that separation is the point.

    The first version of this guard unioned every sweep together and asked only whether the
    criterion appeared somewhere. Its own bite check found the hole: deleting a row from the
    violation list left the criterion in the control list, the union was unchanged, and the guard
    stayed green while half the proof was gone. A pair needs both halves — a violation that fires
    and a counterpart that does not — or it demonstrates a detector that fires on everything, or
    one that fires on nothing."""
    gen_name, test_file = CORPORA[fmt]
    gen = _load(gen_name)
    declared = set(gen.DECLARED) | set(getattr(gen, "DECLARED_ENGINE", ()))
    sweeps = _swept(test_file)
    assert sweep in sweeps, (
        f"{test_file} has no sweep named {sweep} — this guard would be reading nothing, which is "
        f"worse than absent because it looks like a check")

    missing = sorted(sc for sc in declared
                     if sc not in sweeps[sweep] and (fmt, sc) not in PROVEN_ELSEWHERE)
    assert not missing, (
        f"{gen_name}.DECLARED claims {missing}, but {sweep} in {test_file} does not name those "
        f"criteria — so declaring them raised the coverage number without adding that assertion. "
        f"Add the fixture to this list, or name the pair in PROVEN_ELSEWHERE with the file that "
        f"does prove it")


@pytest.mark.parametrize("fmt", sorted(CORPORA))
def test_every_swept_criterion_is_actually_declared(fmt):
    """The other direction. A sweep naming a criterion the corpus does not declare is either a
    stale row left behind by a deleted fixture or a pair somebody forgot to declare — and the
    second costs real coverage, silently, which is the same currency as the first."""
    gen_name, test_file = CORPORA[fmt]
    gen = _load(gen_name)
    declared = set(gen.DECLARED) | set(getattr(gen, "DECLARED_ENGINE", ()))
    covered = set().union(*_swept(test_file).values())
    # Criteria outside the preset legitimately appear (pdf sweeps 1.4.6 alongside 1.4.3, which is
    # inherent and deliberately not declared), so compare only against the preset's own pairs.
    import assessment_policy as ap
    in_preset = {sc for sc, fmts in ap.SCOPE_PRESETS["acp-core-17"].items() if fmt in fmts}
    stray = sorted((covered & in_preset) - declared)
    assert not stray, (
        f"{test_file} sweeps {stray}, which {gen_name}.DECLARED does not claim — either the "
        f"fixtures were removed and the rows are stale, or the pairs are real coverage nobody "
        f"is counting")


def test_the_reader_actually_finds_the_sweeps():
    """This guard's own bite check. If `_swept` silently returned nothing — a renamed decorator,
    a changed argument string, an ast shape it does not handle — both assertions above would pass
    vacuously for every format, and the hole would be exactly as open as before with a green test
    sitting on top of it."""
    for fmt, (_gen, test_file) in sorted(CORPORA.items()):
        sweeps = _swept(test_file)
        assert sweeps, f"{test_file}: no parametrised sweeps found at all"
        total = set().union(*sweeps.values())
        assert len(total) >= 7, (
            f"{test_file}: only {sorted(total)} were read out of the sweeps — the parser is "
            f"missing rows, so the coverage assertions above are weaker than they look")
