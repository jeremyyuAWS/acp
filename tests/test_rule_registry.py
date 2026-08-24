"""Contract: the capability registry may not contradict the tables it is migrating away from.

The registry is the fifth place that has an opinion about which (criterion, format) pairs ACP
covers — after `store.RULE_FORMATS`, `store.REVIEW_FORMATS`, `remediation_capability`, and
`config/rule-catalog.json`. Those four already disagree with each other; that disagreement is
what `CLAUDE.md` ground rule 4 tracks, and it is the reason 4.1.2-on-PDF was broken.

Adding a fifth opinion with no binding between them would make the problem worse, not better.
So during the migration the registry is allowed to be a *stricter* statement of what the legacy
tables already imply, and never a contradiction of one. These tests are that binding. When one
fails, one of the two sides is wrong — fix it rather than exempting the pair, because an
exemption is exactly how the original four drifted apart.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import assessment  # noqa: E402
import capabilities  # noqa: E402
import rule_registry  # noqa: E402
import store  # noqa: E402

rule_registry.load()
REGS = rule_registry.all_registrations()


def test_registry_is_not_empty():
    """A silently empty registry would make every other test here vacuously pass."""
    assert REGS, "no registrations loaded — did formats/__init__.py stop importing a package?"


@pytest.mark.parametrize("reg", REGS, ids=lambda r: f"{r.rule}-{r.fmt}")
def test_declared_capabilities_are_reachable_for_the_format(reg):
    """A rule may not require a capability its format never advertises.

    This is the check that keeps `requires` honest. Declaring `requires={TAG_TREE}` for PDF
    today would make the pair permanently unsupported at runtime while still LOOKING covered
    in the registry — a silent no-op, which is the failure mode this whole layer exists to
    prevent. The pair should be Coverage.DECLARED until the capability actually exists.
    """
    baseline = capabilities.BASELINE.get(reg.fmt, frozenset())
    unreachable = sorted(c.value for c in reg.requires - baseline)
    assert not unreachable, (
        f"{reg.rule} × {reg.fmt} requires {unreachable}, which {reg.fmt} does not advertise. "
        f"Either the format adapter should advertise it, or this pair is Coverage.DECLARED.")


@pytest.mark.parametrize("reg", REGS, ids=lambda r: f"{r.rule}-{r.fmt}")
def test_a_technique_is_backed_by_a_detector(reg):
    """Anything above DECLARED claims work is done, so something must actually run."""
    if reg.coverage is assessment.Coverage.DECLARED:
        assert reg.detector is None, (
            f"{reg.rule} × {reg.fmt} is DECLARED but has a detector — if it runs, its coverage "
            f"is at least HEURISTIC.")
    else:
        assert callable(reg.detector), f"{reg.rule} × {reg.fmt} claims coverage with no detector"


@pytest.mark.parametrize("reg", REGS, ids=lambda r: f"{r.rule}-{r.fmt}")
def test_partial_coverage_never_certifies_a_pass(reg):
    """The core invariant. Only FULL coverage may report PASS on a clean scan (ADR 0016).

    Asserted through `store._rule_outcome`, the function the rest of the product actually
    calls, rather than through the registry's own helper — a rule that certifies correctly in
    the registry but leaks a PASS through the outcome path would still be the bug.
    """
    clean = store._rule_outcome(reg.rule, reg.fmt, 0, 0)
    if reg.coverage is assessment.Coverage.FULL:
        assert clean in ("PASS", store.REVIEW), clean
    else:
        assert clean != "PASS", (
            f"{reg.rule} × {reg.fmt} has {reg.coverage.value} coverage but a clean scan reads "
            f"PASS — partial work may never certify conformance.")


@pytest.mark.parametrize("reg", REGS, ids=lambda r: f"{r.rule}-{r.fmt}")
def test_a_blocking_finding_still_outranks_coverage(reg):
    """Coverage limits what a CLEAN result claims. It must never soften a real failure —
    the same guarantee `test_no_silent_gaps` makes for the legacy lanes."""
    assert store._rule_outcome(reg.rule, reg.fmt, 1, 0) == "FAIL"


@pytest.mark.parametrize("reg", REGS, ids=lambda r: f"{r.rule}-{r.fmt}")
def test_registry_does_not_contradict_the_legacy_scope_tables(reg):
    """A registered pair may not be one the legacy tables say is a certified pass/fail lane.

    The migration only ever moves pairs whose coverage the old tables UNDER-stated (a detector
    ran but no table admitted it). A pair sitting in `RULE_FORMATS` is already claiming a full
    pass/fail lane, so registering it as PARTIAL would be a genuine contradiction — two tables
    disagreeing about the same cell, which is the thing this contract exists to catch.
    """
    if reg.coverage is assessment.Coverage.FULL:
        return                       # a FULL pair agreeing with RULE_FORMATS is consistent
    in_passfail_lane = reg.fmt in store.RULE_FORMATS.get(reg.rule, frozenset())
    assert not in_passfail_lane, (
        f"{reg.rule} × {reg.fmt} is registered as {reg.coverage.value} but RULE_FORMATS lists "
        f"it as a full pass/fail lane. One of the two is wrong — reconcile, don't exempt.")


def test_the_three_undeclared_xlsx_pairs_are_now_declared():
    """The regression this work closed for xlsx (R8 quick-fixes).

    `office_color_only_checks`, `xlsx_nontext_contrast_checks`, and `office_control_review_checks`
    all shipped and ran on every xlsx file, but none of the three pairs appeared in RULE_FORMATS
    or REVIEW_FORMATS, so findings surfaced as FAIL while a clean file read NOT_EVALUATED — the
    scan under-reporting work it had actually done. All three are now registered as PARTIAL /
    MEDIUM and return REVIEW on a clean scan (confirmed by R10 CI fixtures, PR #673).
    """
    for rule in ("1.4.1", "1.4.11", "4.1.2"):
        reg = rule_registry.get(rule, "xlsx")
        assert reg is not None, f"{rule} × xlsx lost its registration"
        assert reg.reason, "a partial technique must say what it does not cover"
        assert store._rule_outcome(rule, "xlsx", 0, 0) == store.REVIEW
        assert store._rule_outcome(rule, "xlsx", 1, 0) == "FAIL"


def test_the_two_undeclared_pdf_pairs_are_now_declared():
    """The regression this work closed.

    `pdf_form_field_checks` and `pdf_focus_order_checks` both shipped and ran on every PDF, but
    neither pair appeared in RULE_FORMATS or REVIEW_FORMATS, so findings surfaced as FAIL while
    a clean file read NOT_EVALUATED — the scan under-reporting work it had actually done. The
    matrix's drift check independently flagged both as "undeclared coverage".
    """
    for rule in ("4.1.2", "2.4.3"):
        reg = rule_registry.get(rule, "pdf")
        assert reg is not None, f"{rule} × pdf lost its registration"
        assert reg.reason, "a partial technique must say what it does not cover"
        assert store._rule_outcome(rule, "pdf", 0, 0) == store.REVIEW
        assert store._rule_outcome(rule, "pdf", 1, 0) == "FAIL"


def test_duplicate_registration_is_rejected():
    """Two modules owning one pair would let import order pick the winner."""
    with pytest.raises(ValueError, match="already registered"):
        rule_registry.register(
            rule="4.1.2", fmt="pdf", detector=lambda p: [],
            requires={capabilities.Capability.FORMS},
            coverage=assessment.Coverage.FULL,
            confidence=assessment.Confidence.HIGH)


def test_unsupported_result_states_the_missing_capability():
    """A rule that cannot run must say which capability was absent, not just decline.

    "We did not check" is only an acceptable answer when it carries the reason — that is the
    distinction `test_rule_formats` draws between "we did not check" and "does not apply".
    """
    missing = capabilities.missing({capabilities.Capability.TAG_TREE},
                                   capabilities.BASELINE["pdf"])
    assert missing == [capabilities.Capability.TAG_TREE]
    result = assessment.unsupported(f"needs {capabilities.describe(missing)}")
    assert result.status == "NOT_EVALUATED"
    assert result.coverage is assessment.Coverage.UNSUPPORTED
    assert "semantic tag tree" in result.reason
