"""Contract: the WCAG matrix's two ceilings are derived from two independent axes.

`scripts/gen_matrix_coverage.py` emits, per grid cell, the strongest tier the code could
honestly claim on each axis. The axes answer different questions:

    assessment  — what does the DETECTOR examine? (coverage: full / partial / heuristic / …)
    remediation — does the FIXER write? (lane: auto / assisted / human)

Neither answers the other's question. A detector that examines part of a criterion says nothing
about whether a fixer writes, and vice versa. This file asserts the generator keeps them apart.

The bug it exists to prevent
----------------------------
`R_CEILING[None] = "N"` used to turn "the lane table does not mention this pair" into R1
"No Remediation" — a positive claim that nothing remediates it, which nothing in the code had
proven. pdf 4.1.2 is where it did real damage: the pair is migrated to the capability registry
with `coverage=partial` (an ASSESSMENT-side statement — AcroForm fields are examined, tagged
structure components are not), that registry entry also suppressed the undeclared-coverage
warning, and the remediation axis was left holding an unexamined default. The result was R1
"No Remediation" for `_fix_pdf_form_fields`, a fixer that runs unattended and demonstrably
writes /TU. The matrix's drift guard reported the MATRIX for over-claiming on that basis, and
the report was rejected as a derivation bug — correctly, but by hand, which is why this file
now holds the line mechanically.

The fix is not "make the fallback smarter". A missing lane is a GAP, and a gap has no ceiling:
the cell emits `ceiling_r: null` plus a loud note, the drift consumer skips a null rather than
ranking against it, and the gap shows up as a gap.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def gen():
    return _load("acp_gen_matrix_coverage_axes", ACP / "scripts" / "gen_matrix_coverage.py")


@pytest.fixture(scope="module")
def data(gen):
    return gen.build()


def _cells(data):
    for sc, fmts in data["cells"].items():
        for fmt, cell in fmts.items():
            yield sc, fmt, cell


# ══ the structural guard ═══════════════════════════════════════════════════════
def test_remediation_ceiling_map_has_no_missing_lane_default(gen):
    """`R_CEILING[None]` is the bug in one line — it must not come back.

    Every key here has to be a real lane, so that a missing lane cannot pick up a ceiling by
    dictionary lookup. `A_CEILING` legitimately keeps its None entry: an unassessed pair really
    does top out at "a human does it", which is a statement about the assessment axis made from
    assessment-axis evidence.
    """
    assert None not in gen.R_CEILING, (
        "R_CEILING grew a None entry — a missing remediation lane must not resolve to a tier "
        "by fallback. See _remediation_ceiling.")
    assert set(gen.R_CEILING) == {"auto", "assisted", "human"}


def test_missing_lane_yields_no_ceiling_whatever_the_assessment_axis_says(gen):
    """The unit form: no lane -> None, and no assessment-side evidence can change that.

    Each call below varies only the surrounding evidence — does ACP assess this pair, does an
    applier write it back. None of it is allowed to manufacture a remediation tier, because
    none of it is a statement about whether a fixer runs.
    """
    for has_applier in (True, False):
        for covered in (True, False):
            ceiling, notes, _gap = gen._remediation_ceiling(
                None, has_applier=has_applier, covered=covered)
            assert ceiling is None, (
                f"missing lane produced ceiling {ceiling!r} with applier={has_applier} "
                f"covered={covered} — the gap was filled from the wrong axis")
            assert notes, "a missing lane must say so; got no note at all"

    # …and a declared lane still maps straight through, unchanged.
    for lane, tier in (("auto", "A"), ("assisted", "AI"), ("human", "M")):
        assert gen._remediation_ceiling(
            lane, has_applier=False, covered=False) == (tier, [], False)


def test_a_missing_lane_is_only_LOUD_where_acp_actually_touches_the_pair(gen):
    """`is_gap` separates "the lane table is incomplete" from "ACP never claimed this pair".

    Both get a null ceiling — silence is not proof either way — but only the first is a defect.
    Marking all of them would bury the real ones, which is its own kind of dishonest reporting.
    """
    # A fixer that writes with no lane recorded: the pdf 4.1.2 shape, the loudest case there is.
    ceiling, notes, gap = gen._remediation_ceiling(None, has_applier=True, covered=False)
    assert (ceiling, gap) == (None, True)
    assert "NO REMEDIATION LANE" in notes[0] and "write-back applier" in notes[0]

    # Assessed but never remediated — still a gap, worded from what is actually known.
    ceiling, notes, gap = gen._remediation_ceiling(None, has_applier=False, covered=True)
    assert (ceiling, gap) == (None, True)
    assert "NO REMEDIATION LANE" in notes[0]

    # Nothing anywhere: not a gap in the lane table, so not reported as one.
    ceiling, notes, gap = gen._remediation_ceiling(None, has_applier=False, covered=False)
    assert (ceiling, gap) == (None, False)
    assert "NO REMEDIATION LANE" not in notes[0]
    assert "makes no claim here" in notes[0]


# ══ the same property over the real, built table ═══════════════════════════════
def test_no_cell_has_a_remediation_ceiling_without_a_remediation_lane(data):
    """Over every shipped cell: a remediation ceiling exists exactly when a lane does.

    This is the invariant the per-cell branches must preserve. The ground-rule-2 (model in the
    decision path) and no-applier downgrades both ADJUST a ceiling, and neither may create one.
    """
    wrong = [(sc, fmt, cell["remediation_lane"], cell["ceiling_r"])
             for sc, fmt, cell in _cells(data)
             if (cell["ceiling_r"] is None) != (cell["remediation_lane"] is None)]
    assert not wrong, (
        "cells whose remediation ceiling and lane disagree about whether a claim exists "
        f"(sc, fmt, lane, ceiling): {wrong}")


def test_every_missing_lane_is_flagged_and_explained(data):
    """A missing lane must be machine-readable AND readable. Silence is the failure mode here."""
    for sc, fmt, cell in _cells(data):
        if cell["remediation_lane"] is not None:
            assert cell["remediation_lane_missing"] is False, f"{sc}/{fmt}"
            assert cell["remediation_gap"] is False, f"{sc}/{fmt}"
            continue
        assert cell["remediation_lane_missing"] is True, f"{sc}/{fmt}: absence not flagged"
        assert cell["notes"], (
            f"{sc}/{fmt}: remediation lane missing with no note saying so — this is the silent "
            f"fallback the file exists to prevent")
        if cell["remediation_gap"]:
            assert any("NO REMEDIATION LANE" in n for n in cell["notes"]), (
                f"{sc}/{fmt}: flagged as a gap but nothing in the notes says so: {cell['notes']}")


def test_a_write_back_applier_without_a_lane_is_always_a_flagged_gap(data):
    """The pdf 4.1.2 bug class, asserted over the whole table rather than one cell.

    handlers.py writing an approved value back into the file for a pair is proof that ACP
    remediates it. If the lane table does not mention that pair, the ceiling must be null and
    the cell must be flagged — never the old confident "N". As it happens the class is empty
    right now (pdf 4.1.2 was the only member and it has a lane), so this also guards against a
    future applier landing without one.
    """
    for sc, fmt, cell in _cells(data):
        if cell["applier"] and cell["remediation_lane"] is None:
            assert cell["ceiling_r"] is None and cell["remediation_gap"] is True, (
                f"{sc}/{fmt}: an approved value is written back into the file, but the cell "
                f"claims ceiling_r={cell['ceiling_r']!r} with gap={cell['remediation_gap']} — "
                f"this is exactly the wrong answer pdf 4.1.2 used to give")


def test_registry_coverage_never_caps_a_remediation_ceiling(data, gen):
    """The specific cross-axis inference: a registry `coverage` value must not reach ceiling_r.

    Every registry-migrated pair is checked. Where the pair HAS a lane, its ceiling must be the
    lane's own tier (possibly adjusted by a remediation-axis rule) and never a translation of
    the coverage value; where it has none, the ceiling must be null rather than a coverage-
    derived tier.
    """
    registry = gen.load_registry()
    assert registry, "the capability registry loaded empty — this test would pass vacuously"

    for (sc, fmt), reg in registry.items():
        cell = data["cells"].get(sc, {}).get(fmt)
        if cell is None:                       # a pair the matrix has no row for
            continue
        lane = cell["remediation_lane"]
        if lane is None:
            assert cell["ceiling_r"] is None, (
                f"{sc}/{fmt}: no remediation lane, but ceiling_r is {cell['ceiling_r']!r} — the "
                f"only statement available for this pair is the registry's coverage="
                f"{reg['coverage']}, which is an assessment-axis fact")
        else:
            assert cell["ceiling_r"] == gen.R_CEILING[lane] or cell["ceiling_r"] in ("AI", "M"), (
                f"{sc}/{fmt}: ceiling_r {cell['ceiling_r']!r} is neither the {lane!r} lane's "
                f"tier nor a remediation-axis downgrade")


def test_pdf_4_1_2_is_the_pinned_regression(data):
    """The case that exposed the coupling, pinned on both axes at once.

    REMEDIATION is R4-eligible: `_fix_pdf_form_fields` copies a meaningful /T into /TU
    deterministically, unattended, and the finding clears on re-scan (proven in
    tests/test_remediation_capability.py). It used to read "N" — R1 "No Remediation".

    ASSESSMENT stays Guided: the detector reads AcroForm fields and not the tagged-structure
    tree, so a clean scan cannot certify the criterion. Asserting both together is the point —
    the fix had to raise one axis without dragging the other up with it.
    """
    cell = data["cells"]["4.1.2"]["pdf"]
    assert cell["remediation_lane"] == "auto"
    assert cell["ceiling_r"] == "A", (
        f"pdf 4.1.2 remediation ceiling is {cell['ceiling_r']!r}; the fixer writes /TU without a "
        f"human or a model, so the ceiling is 'A'")
    assert cell["remediation_lane_missing"] is False and cell["remediation_gap"] is False
    assert cell["ceiling_a"] == "Q", (
        f"pdf 4.1.2 assessment ceiling is {cell['ceiling_a']!r}, expected 'Q' — coverage is "
        f"PARTIAL (AcroForm fields only), so a clean scan cannot certify the criterion")
    assert cell["applier"] is True


def test_output_stays_serialisable_and_in_vocabulary(data, gen):
    """A null ceiling is a real value in the emitted JSON, not a crash or a stray sentinel.

    wcag-matrix/scripts/check_grid_drift.py skips a null ceiling (`if claimed is None or raw is
    None: continue`) and raises on any tier it cannot map, so the only two safe things to emit
    are null or a member of R_TIERS.
    """
    json.dumps(data)                                    # no non-serialisable sentinel crept in
    for sc, fmt, cell in _cells(data):
        assert cell["ceiling_r"] is None or cell["ceiling_r"] in gen.R_TIERS, (
            f"{sc}/{fmt}: ceiling_r {cell['ceiling_r']!r} is outside R_TIERS — the drift "
            f"consumer refuses to guess a mapping and would fail the run")
        assert cell["ceiling_a"] in gen.A_TIERS, f"{sc}/{fmt}: ceiling_a out of vocabulary"
