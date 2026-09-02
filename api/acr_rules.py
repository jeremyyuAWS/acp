"""Conformance decision rules (PRD §10, §13, §21.4/21.6/21.7/21.8).

This is the module that keeps the ACR honest. Everything here answers one of two questions:

  may_draft(...)               — what may ACP SUGGEST, from evidence alone?
  may_select_final_status(...) — what may a HUMAN choose, given that evidence?

and the answers are deliberately different. ACP may never select or approve a final status
(PRD §20); a human may never select "Supports" over an unresolved failure (PRD §21.8).

THE CENTRAL RULE, AND WHY IT IS BORROWED RATHER THAN INVENTED
--------------------------------------------------------------
PRD §4.3: "An automated pass must never automatically produce a 'Supports' result."

This codebase already solved that, on the right axis, and the reasoning is written up in
ADR 0031 ("Certification is gated by coverage, not confidence"). `assessment.CAN_CERTIFY_PASS` is
exactly `{Coverage.FULL}`: a clean automated result certifies a pass IFF the technique that
produced it reaches the WHOLE criterion. Not if the tool is accurate — accuracy and completeness
are different properties, and a perfect score on the subset a detector examines says nothing about
the part it never looked at.

So this module imports that frozenset rather than re-deriving the idea. Two consequences worth
stating plainly, because both look like bugs from the outside:

  * axe-core's coverage is never FULL for any criterion. It is PARTIAL where it has rules and
    DECLARED/UNSUPPORTED where it has none — axe's own documentation is explicit that automated
    testing finds a minority of accessibility issues. Under this rule, therefore, NO criterion ever
    auto-drafts "Supports" from automation alone. That is PRD §4.3 working, not a missing feature.
  * The draft-suggestion path (PRD §7.11) fires only once HUMAN evidence supplies the remainder.
    A criterion sitting at "needs_review" with a green axe run is the correct resting state.

WHAT "EXPLICITLY RESOLVED BY NEWER EVIDENCE" MEANS (PRD §21.8)
--------------------------------------------------------------
A known unresolved failure blocks "Supports". The escape hatch is not a checkbox — it is newer
evidence that actually contradicts the failure. Concretely, a failing row is superseded only by a
passing row for the same criterion that is BOTH newer AND not stale (same product version, inside
its validity window). Anything weaker would let a "Supports" claim rest on a pass recorded against
a build that no longer exists, which is the §12 staleness problem wearing a different hat.
"""
from __future__ import annotations

from assessment import CAN_CERTIFY_PASS, Coverage
from acr_catalog import (DOES_NOT_SUPPORT, FINAL_STATUSES, NOT_APPLICABLE, PARTIALLY_SUPPORTS,
                         REMARKS_REQUIRED, SUPPORTS)
from acr_model import RESULT_BLOCKED, RESULT_FAIL, RESULT_PASS


class Verdict:
    """Why a status is or is not permitted. Carries the reason so the UI and the validation screen
    render the SAME sentence — a gate whose refusal a user cannot read gets worked around."""

    __slots__ = ("allowed", "reason")

    def __init__(self, allowed: bool, reason: str = "") -> None:
        self.allowed = allowed
        self.reason = reason

    def __bool__(self) -> bool:
        return self.allowed

    def __repr__(self) -> str:  # pragma: no cover — debugging aid
        return f"Verdict({self.allowed}, {self.reason!r})"


ALLOWED = Verdict(True)


def _coverage_of(ev) -> Coverage | None:
    """An evidence row's declared coverage as a Coverage member, or None when unparseable.

    None is NOT treated as permissive anywhere below. acr_model refuses to construct automated
    evidence without a coverage value at all, so None here means a stored row predating that
    guard or carrying a value the enum has since dropped — in either case "we do not know what
    this technique reached", which can never certify.
    """
    raw = getattr(ev, "coverage", None)
    if not raw:
        return None
    try:
        return Coverage(raw)
    except ValueError:
        return None


def _live(evidence, stale_ids: set[str] | None = None):
    """Evidence that may support a publication claim: everything not marked stale.

    PRD §12: a stale record "remains visible for audit history but cannot independently support
    publication". So staleness filters the DECISION inputs, never the display list.
    """
    stale = stale_ids or set()
    return [e for e in evidence if e.id not in stale and not getattr(e, "stale_reason", None)]


def open_failures(evidence, stale_ids: set[str] | None = None) -> list:
    """Failing evidence not superseded by newer, non-stale passing evidence for the same criterion.

    This is PRD §21.8's "known unresolved failure", computed rather than tracked as a flag — a
    stored flag drifts the moment a new row lands, and the drift is invisible.
    """
    live = _live(evidence, stale_ids)
    passes = [e for e in live if e.result == RESULT_PASS]
    out = []
    for fail in (e for e in live if e.result == RESULT_FAIL):
        superseded = any(
            p.criterion_num == fail.criterion_num and p.tested_at > fail.tested_at
            for p in passes)
        if not superseded:
            out.append(fail)
    return out


def has_human_evaluation(evidence, stale_ids: set[str] | None = None) -> bool:
    """Did a person actually exercise this criterion? (PRD §10 "Supports" bullet 5.)"""
    return any(not e.is_automated for e in _live(evidence, stale_ids))


def has_human_pass(evidence, stale_ids: set[str] | None = None) -> bool:
    """Did a person exercise this criterion and RECORD A PASS?

    Distinct from has_human_evaluation, and the distinction is the whole point. A tester who
    opened the screen and marked the test `blocked` has evaluated it; they have not established
    that it conforms. The automated row's own `pass` must not stand in for the positive result
    they declined to give — which is exactly what "is there any passing row?" would let it do,
    since the automated row is usually a pass.

    Found by test_a_blocked_human_test_is_not_a_pass: the first version of this module asked
    "human evaluation exists AND some row passed", and an axe-core pass beside a blocked keyboard
    test drafted Supports.
    """
    return any((not e.is_automated) and e.result == RESULT_PASS
               for e in _live(evidence, stale_ids))


def may_draft(criterion_num: str, evidence, stale_ids: set[str] | None = None) -> tuple[str | None, str]:
    """What ACP may SUGGEST as a draft status, and why. Never a decision (PRD §4.2, §20).

    Returns (draft_status_or_None, reason). None means "no draft — this needs a human", which is
    the honest default and by far the most common answer.
    """
    live = _live(evidence, stale_ids)
    if not live:
        return None, "no evidence attached yet"

    failures = open_failures(evidence, stale_ids)
    if failures:
        # A failure is the one thing automation CAN establish on its own: it found a real defect.
        # Whether that makes the criterion "Partially Supports" or "Does Not Support" is a scope
        # judgement about how much of the product is affected — a human's call, so this drafts the
        # weaker of the two and says why.
        return PARTIALLY_SUPPORTS, (
            f"{len(failures)} unresolved failure(s) recorded; a human must judge whether the "
            f"criterion is partially or wholly unsupported")

    if not has_human_evaluation(evidence, stale_ids):
        # Everything here is automated and clean. This is the PRD §4.3 case.
        best = max((c for c in (_coverage_of(e) for e in live) if c is not None),
                   key=lambda c: list(Coverage).index(c), default=None)
        if best in CAN_CERTIFY_PASS:
            return SUPPORTS, (
                "an automated technique declaring FULL coverage of this criterion returned no "
                "findings")
        reached = best.value if best else "undeclared"
        return None, (
            f"automated evidence only, coverage={reached} — a clean result from a technique that "
            f"does not reach the whole criterion is not evidence of conformance (ADR 0031). "
            f"Manual evaluation is required before a status can be drafted.")

    # A human looked, and nothing failed — but "nothing failed" is not "something passed". A
    # criterion whose only human evidence is `blocked` (the tester could not complete the test) or
    # `not_applicable` has no positive result behind it, and drafting Supports there would invent
    # the very conclusion the tester declined to reach. The automated row's own pass does not
    # substitute: see has_human_pass.
    if not has_human_pass(evidence, stale_ids):
        recorded = sorted({e.result for e in live if not e.is_automated})
        return None, (
            f"human evaluation recorded, but no passing human result ({', '.join(recorded)}) — a "
            f"criterion with no positive result has nothing to support a conformance claim")

    return SUPPORTS, "human evaluation recorded with a passing result and no unresolved failures"


def may_select_final_status(status: str, *, criterion_num: str, evidence, remarks: str | None,
                            stale_ids: set[str] | None = None) -> Verdict:
    """May a human select `status` for this criterion right now? (PRD §10, §21.6-21.8.)

    The gate a person passes through, distinct from may_draft above. It is deliberately permissive
    about human judgement (a person may record "Does Not Support" with no evidence at all — the
    limitation is the finding) and strict about the one claim that over-claims: "Supports".
    """
    if status not in FINAL_STATUSES:
        return Verdict(False, f"{status!r} is not a VPAT conformance level")

    if status in REMARKS_REQUIRED and not (remarks or "").strip():
        return Verdict(False, f"{status} requires remarks (PRD §10)")

    if status == NOT_APPLICABLE:
        # PRD §10: requires an explanation of why the criterion does not apply. That is the remarks
        # check above; there is nothing further to prove, and requiring evidence that something is
        # absent would be incoherent.
        return ALLOWED

    if status == DOES_NOT_SUPPORT:
        return ALLOWED

    live = _live(evidence, stale_ids)

    if status == PARTIALLY_SUPPORTS:
        if not live:
            return Verdict(False,
                           "Partially Supports describes evaluated behaviour — attach the evidence "
                           "that establishes what does and does not support the criterion")
        return ALLOWED

    # ── Supports: every bullet of PRD §10's first block ────────────────────────────────────────
    if not live:
        return Verdict(False, "Supports requires supporting evidence (PRD §10, §21.6)")

    failures = open_failures(evidence, stale_ids)
    if failures:
        newest = max(f.tested_at for f in failures)
        return Verdict(False, (
            f"{len(failures)} unresolved failure(s) contradict a Supports claim (most recent "
            f"{newest}). Record newer passing evidence for this criterion, against this product "
            f"version, to resolve the contradiction (PRD §21.8)."))

    if not has_human_evaluation(evidence, stale_ids):
        best = max((c for c in (_coverage_of(e) for e in live) if c is not None),
                   key=lambda c: list(Coverage).index(c), default=None)
        if best not in CAN_CERTIFY_PASS:
            reached = best.value if best else "undeclared"
            return Verdict(False, (
                f"Supports cannot rest on automated evidence alone at coverage={reached}. An "
                f"automated pass proves nothing tripped the part the tool examines; it is silent "
                f"about the rest of the criterion (PRD §4.3, ADR 0031). Record a manual "
                f"evaluation."))

    # Where a person has evaluated the criterion, THEIR result is the one that has to be a pass.
    # An automated pass beside a blocked or not-applicable human test is not a conformance claim
    # (see has_human_pass); where no person has evaluated it, the FULL-coverage branch above is
    # the only way through, and it already required a clean automated result.
    if has_human_evaluation(evidence, stale_ids) and not has_human_pass(evidence, stale_ids):
        recorded = sorted({e.result for e in live if not e.is_automated})
        return Verdict(False, (
            f"no passing human result ({', '.join(recorded)}) — Supports requires a recorded "
            f"result, not the absence of a failure. A blocked test is not a pass."))

    if not any(e.result == RESULT_PASS for e in live):
        return Verdict(False,
                       "no passing evidence — Supports requires a recorded result, not the absence "
                       "of a failure")

    return ALLOWED


def contradicts_approved_decision(final_status: str, evidence, stale_ids: set[str] | None = None) -> str | None:
    """Does newer evidence contradict an already-approved decision? (PRD §13 last bullet.)

    Returns a human-readable reason, or None. Deliberately does NOT mutate anything: PRD §13 is
    explicit that ACP must "never change a final conformance status automatically after approval",
    only "flag approved decisions when newer evidence contradicts them".
    """
    if final_status not in (SUPPORTS, PARTIALLY_SUPPORTS):
        return None
    failures = open_failures(evidence, stale_ids)
    if not failures:
        return None
    if final_status == SUPPORTS:
        return (f"{len(failures)} unresolved failure(s) recorded since this criterion was approved "
                f"as Supports — the decision needs re-review")
    return None


def summarize(criterion_num: str, evidence, stale_ids: set[str] | None = None) -> dict:
    """Everything the criterion-detail screen needs to explain itself, in one call.

    One function so the screen, the validation report and the export preview cannot disagree about
    whether a criterion is decidable — the same failure mode assessment_policy documents at length
    for scores vs. completeness.
    """
    live = _live(evidence, stale_ids)
    draft, why = may_draft(criterion_num, evidence, stale_ids)
    permitted = {
        s: may_select_final_status(s, criterion_num=criterion_num, evidence=evidence,
                                   # Remarks are supplied at decision time; for the "what could I
                                   # pick" summary, assume they will be, so the screen explains the
                                   # EVIDENCE gate rather than nagging about an empty text box.
                                   remarks="(pending)", stale_ids=stale_ids)
        for s in sorted(FINAL_STATUSES)
    }
    return {
        "criterion_num": criterion_num,
        "evidence_total": len(evidence),
        "evidence_live": len(live),
        "evidence_stale": len(evidence) - len(live),
        "automated_only": bool(live) and not has_human_evaluation(evidence, stale_ids),
        "open_failures": [e.id for e in open_failures(evidence, stale_ids)],
        "draft_status": draft,
        "draft_reason": why,
        "permitted_statuses": {s: v.allowed for s, v in permitted.items()},
        "refusals": {s: v.reason for s, v in permitted.items() if not v.allowed},
    }
