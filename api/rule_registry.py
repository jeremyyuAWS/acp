"""The (rule × format) registry — one declaration point for what we can assess, and how well.

Today the answer to "does ACP assess 4.1.2 on a PDF?" is spread across four places that were
never required to agree: `store.RULE_FORMATS`, `store.REVIEW_FORMATS`,
`remediation_capability.REMEDIATION`, and `config/rule-catalog.json`. They disagree right now —
that is the bug this module exists to make impossible, and `CLAUDE.md` ground rule 4 is the
running tally of what the disagreement has cost.

A registration is a single, checkable statement:

    registry.register(
        rule="4.1.2", fmt="pdf",
        detector=pdf_name_role_value,
        requires={Capability.FORMS},
        coverage=Coverage.PARTIAL,
        confidence=Confidence.HIGH,
        reason="AcroForm widget dictionaries only; tagged-PDF structure roles are not walked",
    )

`evaluate()` then needs no per-rule branching: it asks the format what it can do, compares that
to what the rule needs, and either runs the detector or reports precisely which capability was
missing. Adding a format to a rule is a `register()` call. Improving a technique is a one-word
change to `coverage`, which the WCAG matrix picks up on its next run.

MIGRATION POSTURE — read this before adding entries. The registry is authoritative ONLY for
pairs it knows about; everything else still flows through the legacy tables untouched. That is
deliberate: a big-bang cutover of ~40 detectors would have to be trusted all at once, and the
round-trip proofs in `tests/test_remediation_capability.py` are worth more than a tidy diff.
`tests/test_rule_registry.py` binds every registration to the legacy tables, so a migrated pair
cannot silently contradict them — the registry can only ever be a *stricter* statement of what
is already true. When a pair's registration and its legacy entry disagree, that test fails and
one of them is wrong; fix the wrong one rather than exempting the pair.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from assessment import (CAN_CERTIFY_PASS, NEEDS_REVIEW_ON_CLEAN, AssessmentResult,
                        Confidence, Coverage, unsupported)
from capabilities import Capability, capabilities_for, describe, missing

# A detector takes the file and returns raw finding dicts in the shape the rest of the pipeline
# already speaks (`ruleId`, `wcag`, `severity`, `detail`). Keeping that shape is what lets a
# migrated detector keep flowing through `office_structure.checks_for` unchanged.
Detector = Callable[[Path], list[dict]]


@dataclass(frozen=True)
class Registration:
    rule: str
    fmt: str
    detector: Detector | None
    requires: frozenset[Capability]
    coverage: Coverage
    confidence: Confidence
    reason: str = ""
    remediation: Callable[..., object] | None = None

    @property
    def key(self) -> tuple[str, str]:
        return (self.rule, self.fmt)


_REGISTRY: dict[tuple[str, str], Registration] = {}


def register(*, rule: str, fmt: str, detector: Detector | None,
             requires: Iterable[Capability], coverage: Coverage,
             confidence: Confidence, reason: str = "",
             remediation: Callable[..., object] | None = None) -> Registration:
    """Declare how one criterion is assessed for one format.

    Registering the same pair twice is an error rather than a silent overwrite: two modules
    each believing they own 4.1.2-on-PDF is precisely the ambiguity this table replaces, and
    import order should never decide which one wins.
    """
    key = (rule, fmt)
    if key in _REGISTRY:
        raise ValueError(
            f"{rule} × {fmt} is already registered by {_REGISTRY[key].detector!r} — two "
            f"registrations for one pair means import order picks the winner. Merge them.")
    if coverage is not Coverage.UNSUPPORTED and detector is None:
        raise ValueError(
            f"{rule} × {fmt}: coverage={coverage.value} claims a technique but no detector was "
            f"given. Use Coverage.DECLARED for a known-applicable pair with nothing built yet.")
    reg = Registration(rule=rule, fmt=fmt, detector=detector,
                       requires=frozenset(requires), coverage=coverage,
                       confidence=confidence, reason=reason, remediation=remediation)
    _REGISTRY[key] = reg
    return reg


def get(rule: str, fmt: str | None) -> Registration | None:
    """The registration for a pair, or None when the pair hasn't been migrated yet."""
    if fmt is None:
        return None
    return _REGISTRY.get((rule, fmt))


def is_registered(rule: str, fmt: str | None) -> bool:
    return get(rule, fmt) is not None


def coverage_for(rule: str, fmt: str | None) -> Coverage | None:
    reg = get(rule, fmt)
    return reg.coverage if reg else None


def all_registrations() -> list[Registration]:
    return sorted(_REGISTRY.values(), key=lambda r: (r.rule, r.fmt))


def rules() -> list[str]:
    return sorted({r.rule for r in _REGISTRY.values()})


def maturity_matrix() -> dict[str, dict[str, str]]:
    """{rule: {format: coverage}} — the support grid the WCAG matrix renders.

    Only registered pairs appear. An absent cell means "not migrated to the registry yet",
    which is a different statement from `UNSUPPORTED` ("migrated, and the format can't do it")
    and the matrix is careful to render them differently.
    """
    out: dict[str, dict[str, str]] = {}
    for reg in _REGISTRY.values():
        out.setdefault(reg.rule, {})[reg.fmt] = reg.coverage.value
    return out


def evaluate(rule: str, fmt: str, path: Path) -> AssessmentResult:
    """Assess one criterion against one document.

    The whole point of the indirection: no `if rule == ...` anywhere. Capability containment
    decides whether the technique can run at all, the detector decides what's in the file, and
    coverage decides how much a clean result is worth.
    """
    reg = get(rule, fmt)
    if reg is None:
        return unsupported(f"{rule} is not registered for {fmt}")

    available = capabilities_for(fmt, path)
    absent = missing(reg.requires, available)
    if absent:
        # Not a failure and not a pass — a statement about the document. A scanned PDF has no
        # form fields to name, so 4.1.2's form technique has nothing to say about it, and
        # saying so beats both a vacuous pass and an invented finding.
        return unsupported(
            f"this document does not expose {describe(absent)}, which {rule} needs on {fmt}")

    if reg.detector is None:               # Coverage.DECLARED — applicable, nothing built yet
        return AssessmentResult(status="NOT_EVALUATED", coverage=reg.coverage,
                                confidence=Confidence.LOW,
                                reason=reg.reason or "no technique implemented yet")

    findings = reg.detector(path) or []
    return result_for(reg, findings)


def result_for(reg: Registration, findings: list[dict]) -> AssessmentResult:
    """Turn a detector's raw findings into a verdict, applying the coverage rules.

    Split out from `evaluate()` so the legacy path can reuse it: `store._rule_outcome` already
    has counts in hand from findings gathered elsewhere in the pipeline and needs the same
    coverage logic applied to them.
    """
    blocking = [f for f in findings if str(f.get("severity", "")).upper() != "REVIEW"]
    advisory = [f for f in findings if str(f.get("severity", "")).upper() == "REVIEW"]

    if blocking:
        # A recorded finding is a fact and outranks every coverage consideration. Partial
        # coverage limits what a CLEAN result can claim; it never softens a real failure.
        for f in blocking:
            f.setdefault("confidence", "confirmed")
        return AssessmentResult(status="FAIL", coverage=reg.coverage,
                                confidence=reg.confidence, evidence=blocking,
                                reason=reg.reason)
    if advisory:
        for f in advisory:
            f.setdefault("confidence", "needs-review")
        return AssessmentResult(status="REVIEW", coverage=reg.coverage,
                                confidence=reg.confidence, evidence=advisory,
                                reason=reg.reason)

    # Clean scan. What that is worth depends entirely on how much we looked at.
    if reg.coverage in CAN_CERTIFY_PASS:
        return AssessmentResult(status="PASS", coverage=reg.coverage,
                                confidence=reg.confidence, reason=reg.reason)
    if reg.coverage in NEEDS_REVIEW_ON_CLEAN:
        return AssessmentResult(
            status="REVIEW", coverage=reg.coverage, confidence=reg.confidence,
            reason=reg.reason or "the technique covers only part of this criterion, so a clean "
                                 "result is not a certified pass")
    return AssessmentResult(status="NOT_EVALUATED", coverage=reg.coverage,
                            confidence=Confidence.LOW, reason=reg.reason)


def load() -> None:
    """Import the format packages so their registrations execute.

    Registration happens as an import side effect, which means something has to do the
    importing. Doing it in one named function — rather than at `rule_registry` import time —
    keeps the module importable by tooling that only wants to read the table (the WCAG matrix
    generator does exactly this) without dragging in pikepdf and friends.
    """
    import formats  # noqa: F401  — package __init__ imports each format's registrations
