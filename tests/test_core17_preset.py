"""ACP Core 17 must stay equal to SCOPE_UNIVERSE ∩ MOVA_TRACKED.

The preset is written out as a literal in assessment_policy.SCOPE_PRESETS rather than derived,
because SCOPE_PRESETS is read as a plain dict at module scope and deriving it would mean loading
the rule registry during import. That is a reasonable trade only if something recomputes the
intersection and fails when the literal drifts — which is this file.

Drift is not hypothetical. The universe moves whenever a detector, a review lane or a registry
entry is added: #149 removed docx from 4.1.2's tables and #150 had to regenerate behind it. A
stale preset would quietly scope OUT a pair the engine had just learned to judge, and the symptom
is a criterion reading NOT_EVALUATED on a scan the operator believes covered everything.
"""
from __future__ import annotations

import sys
from pathlib import Path

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))
sys.path.insert(0, str(ACP / "scripts"))

import assessment_policy as pol      # noqa: E402

CORE = "acp-core-17"
DOC_FORMATS = {"docx", "xlsx", "pptx", "pdf"}


def _universe() -> dict[str, set[str]]:
    """Every (criterion, format) pair the backend can reach a verdict on.

    The same three sources gen_scope_presets._universe() unions — a pass/fail validator, a review
    lane, or the capability registry — because `_rule_outcome` applies the scope before any lane
    branching, so a scope that knew about only one of them would be narrower than the gate.
    """
    import rule_registry as reg
    reg.load()
    registered: dict[str, set[str]] = {}
    for r in reg.all_registrations():
        registered.setdefault(r.rule, set()).add(r.fmt)

    out: dict[str, set[str]] = {}
    for sc in set(pol.RULE_FORMATS) | set(pol.REVIEW_FORMATS) | set(registered):
        fmts = (set(pol.RULE_FORMATS.get(sc, ()))
                | set(pol.REVIEW_FORMATS.get(sc, ()))
                | registered.get(sc, set())) & DOC_FORMATS
        if fmts:
            out[sc] = fmts
    return out


def test_the_preset_exists_and_is_the_default_shape():
    assert CORE in pol.SCOPE_PRESETS, "ACP Core 17 is gone"
    assert len(pol.SCOPE_PRESETS[CORE]) == 17


def test_it_covers_exactly_the_tracked_criteria():
    """Not 'the 17 we typed' — the 17 the product says it tracks, from the one definition."""
    assert set(pol.SCOPE_PRESETS[CORE]) == set(pol.MOVA_TRACKED)


def test_every_pair_is_one_the_engine_can_actually_judge():
    """The direction that would overstate the product: scoping IN a pair with no verdict behind it
    puts a criterion in the engagement that can only ever read NOT_EVALUATED."""
    uni = _universe()
    for sc, fmts in pol.SCOPE_PRESETS[CORE].items():
        assert sc in uni, f"{sc} is in Core 17 but the engine has no lane for it on any format"
        extra = set(fmts) - uni[sc]
        assert not extra, f"{sc} scopes in {sorted(extra)}, which the engine cannot judge"


def test_no_judgeable_pair_is_left_out():
    """The quieter direction, and the one a stale literal produces: the engine gains a lane and the
    default engagement silently keeps excluding it."""
    uni = _universe()
    for sc in pol.MOVA_TRACKED:
        assert sc in uni, f"tracked criterion {sc} has no lane at all — the universe shrank"
        missing = uni[sc] - set(pol.SCOPE_PRESETS[CORE].get(sc, ()))
        assert not missing, (
            f"{sc}: the engine can judge {sorted(missing)} but Core 17 excludes it — regenerate "
            "the preset from SCOPE_UNIVERSE ∩ MOVA_TRACKED")


def test_it_covers_more_criteria_than_the_engagement_preset():
    """engagement-14 is 14 criteria agreed for one customer. If Core 17 ever became the narrower of
    the two, the default would be hiding work rather than describing the product."""
    assert set(pol.SCOPE_PRESETS["engagement-14"]) < set(pol.SCOPE_PRESETS[CORE])


def test_the_engagement_preset_names_two_pairs_the_engine_cannot_judge():
    """Two real gaps, pinned rather than tolerated silently — and the reason this file does NOT
    assert engagement-14 ⊆ Core 17 by format.

    The presets answer different questions. Core 17 is what the ENGINE can judge, so every pair in
    it is backed by a lane. engagement-14 mirrors what a CUSTOMER agreed to assess, and a customer can
    agree to something ACP cannot do. Both gaps verified against the tables directly:

        1.4.1 / pptx   RULE_FORMATS html-only, REVIEW_FORMATS docx+pdf+xlsx, registry empty
        2.1.1 / pdf    RULE_FORMATS pptx-only, REVIEW_FORMATS empty,         registry empty

    Each can only ever read NOT_EVALUATED. That is honest behaviour — the scope says in-scope and
    the engine says not-evaluated — but it is a coverage gap someone should be able to find rather
    than rediscover.

    Compared as a SET, not per criterion. The first version of this asserted pair-by-pair and
    stopped at 1.4.1, reporting one gap when there were two; collecting them all and comparing
    once is what surfaced the second. A third would fail here instead of joining them unnoticed,
    and closing either fails here too — the discrepancy has to be looked at either way.
    """
    core = pol.SCOPE_PRESETS[CORE]
    eng = pol.SCOPE_PRESETS["engagement-14"]
    beyond = {sc: sorted(set(f) - set(core.get(sc, ())))
              for sc, f in eng.items() if set(f) - set(core.get(sc, ()))}
    assert beyond == {"1.4.1": ["pptx"], "2.1.1": ["pdf"]}, (
        f"the engagement scope's unjudgeable pairs changed: {beyond}. If a pair was ADDED, the "
        "engagement now claims coverage ACP cannot deliver; if one was fixed, drop it from this "
        "expectation.")


def test_the_asymmetries_are_real_and_not_flattened():
    """A flat 17 × 4 grid would claim eleven pairs the engine cannot judge. These four are the
    ones a well-meaning 'tidy-up' would most likely square off."""
    core = pol.SCOPE_PRESETS[CORE]
    assert set(core["2.1.1"]) == {"pptx"}
    assert set(core["2.4.3"]) == {"pdf", "pptx"}
    assert "pptx" not in core["1.4.1"]
    assert "pdf" not in core["2.1.2"]
