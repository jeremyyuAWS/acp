"""A shipped detector must be DECLARED — shipping one silently is the gap nothing was watching.

There is already a no-silent-gaps test (tests/test_no_silent_gaps.py). It guards the OUTCOME
contract: every (criterion, format, signal) resolves to PASS / FAIL / REVIEW / NOT_EVALUATED,
never None and never a raise. That is necessary and it is not sufficient, because
`NOT_EVALUATED` is a perfectly legal answer for a pair nobody declared — and it is the WRONG
answer for a pair whose detector is running. The scan finds things; the manifest says "we did
not look". That exact shape is what `_rule_outcome`'s blocking-finding hoist exists to paper
over:

    A recorded blocking finding is a FACT: it must surface as FAIL no matter what the format
    bookkeeping says. Before this hoist, a fail on a (rule, format) pair missing from
    RULE_FORMATS was silently reclassified NOT_EVALUATED — the exact detector/catalog-drift
    hazard the no-silent-gaps contract test exists to catch.

The hoist rescues a pair that FIRES. It cannot rescue a pair that runs and finds nothing: that
still reports NOT_EVALUATED, which reads as "not checked" when the truth is "checked, clean".
A clean document is then indistinguishable from an unexamined one, and the coverage denominators
that the whole Assessment Coverage surface is built on are quietly wrong.

WHAT THIS TEST IS, HONESTLY. The property already holds — as of 2026-07-29 all 85 pairs with a
shipped detector are declared, and the measured gap is zero. This is a ratchet, not a repair: it
pins that at zero so the next detector cannot arrive undeclared. Writing it was cheap precisely
because there was nothing to clean up first; the value is entirely in tomorrow.

DECLARED means any of the three authorities knows the pair:
  - store.RULE_FORMATS    the pass/fail lane
  - store.REVIEW_FORMATS  the review lane (ADR 0023) — assessed, never certified
  - rule_registry         the migration target (api/rule_registry.py), currently 4 pairs

Three authorities rather than one is not the end state — the registry docstring is explicit that
a big-bang cutover of ~40 detectors would have to be trusted all at once, and that the round-trip
proofs are worth more than a tidy diff. Until that migration finishes, "declared" means declared
SOMEWHERE, and this test is agnostic about which.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))
sys.path.insert(0, str(ROOT / "scripts"))

import store  # noqa: E402


def _detected() -> set[tuple[str, str]]:
    """(criterion, format) pairs with a detector shipped in the catalog.

    Uses the same inventory the WCAG matrix's ceiling derivation uses
    (scripts/gen_matrix_coverage.py:load_detectors), so this test and that pipeline cannot
    disagree about what "has a detector" means. Note its shape is {fmt: {sc: [rules]}} — the
    reverse of every other table here, which is worth stating because reading it the other way
    round yields a tidy-looking 85 gaps that are all phantom.
    """
    import gen_matrix_coverage as cov
    out: set[tuple[str, str]] = set()
    for fmt, per_sc in cov.load_detectors().items():
        for sc, rules in per_sc.items():
            if rules:
                out.add((sc, fmt))
    return out


def _declared() -> set[tuple[str, str]]:
    import formats  # noqa: F401 — importing the package is what performs the registrations
    import rule_registry

    out: set[tuple[str, str]] = set()
    for table in (store.RULE_FORMATS, store.REVIEW_FORMATS):
        for sc, fmts in table.items():
            for f in fmts:
                out.add((sc, f))
    for reg in rule_registry.all_registrations():
        out.add((reg.rule, reg.fmt))
    return out


def test_every_shipped_detector_is_declared_somewhere():
    undeclared = sorted(_detected() - _declared())
    assert not undeclared, (
        "these (criterion, format) pairs have a shipped detector but appear in no scope table:\n  "
        + "\n  ".join(f"{sc} / {fmt}" for sc, fmt in undeclared)
        + "\n\nA detector that runs while no table declares the pair reports NOT_EVALUATED on a "
          "clean file — 'we did not look' about work that was done. Add the pair to "
          "store.RULE_FORMATS (pass/fail lane), store.REVIEW_FORMATS (assessed-for-review, never "
          "certified), or register it in api/rule_registry.py."
    )


def test_the_inventory_and_the_tables_are_both_non_trivial():
    """Guards the guard. If load_detectors() ever returns {} — a moved file, a changed catalog
    shape — the assertion above passes vacuously and this contract silently stops holding, which
    is the same class of failure it exists to prevent."""
    detected, declared = _detected(), _declared()
    assert len(detected) > 50, f"detector inventory looks broken: only {len(detected)} pairs"
    assert len(declared) > 50, f"scope tables look broken: only {len(declared)} pairs"


def test_the_inventory_is_read_in_the_right_orientation():
    """load_detectors() is {fmt: {sc: ...}}, the reverse of the scope tables. Reading it the other
    way round produces a set of (fmt, sc) tuples that overlaps the declared set at zero and looks
    exactly like 85 real gaps. It is not a hypothetical: it is what the first run of this check
    reported."""
    import gen_matrix_coverage as cov
    outer = set(cov.load_detectors().keys())
    assert outer <= {"docx", "xlsx", "pptx", "pdf", "html"}, (
        f"load_detectors() outer keys are not formats ({sorted(outer)[:5]}) — its shape changed, "
        "and _detected() is now building tuples the wrong way round"
    )


@pytest.mark.parametrize("sc,fmt", [("4.1.2", "pdf"), ("2.4.3", "pdf")])
def test_the_registry_backed_pairs_count_as_declared(sc, fmt):
    """These two are declared ONLY in the registry — absent from both legacy tables (that absence
    is why the registry exists; see _rule_outcome's registry section). If `import formats` ever
    stops performing the registrations, they vanish from _declared() and this contract would start
    demanding they be added to a legacy table, which is the opposite of the migration's direction."""
    assert (sc, fmt) in _declared()
    for table in (store.RULE_FORMATS, store.REVIEW_FORMATS):
        assert fmt not in table.get(sc, frozenset()), (
            f"{sc}/{fmt} is now in a legacy table too — if that is deliberate, this test's premise "
            "changed and the registry section of _rule_outcome should be re-read"
        )
