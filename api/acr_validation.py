"""Publication validation (PRD §15 validation screen, §21.6/21.9/21.10, §16 "Publication must fail").

ONE function answers "can this publish", and the validation SCREEN calls the same one. That is the
whole design constraint. A separate "is it ready?" summary computed for display is how a screen
ends up green while the gate is red — the exact drift assessment_policy already documents at length
for scores vs. completeness, and the reason `derive_file_status` is a pure derivation over stored
facts rather than a second measurement.

So: `validate(report, criteria, evidence_by_criterion, ...)` returns a list of Blocker rows. The
publication endpoint refuses if any blocker is `blocking=True`. The screen renders the same rows,
grouped by category. There is no second opinion anywhere.

PRD §15's nine categories are the `CATEGORY_*` constants below, and every one is produced here.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import acr_freshness
import acr_rules
from acr_catalog import (DECIDED, FINAL_STATUSES, NOT_EVALUATED, REMARKS_REQUIRED, SUPPORTS)

# PRD §15's nine blocker categories, verbatim in intent.
CATEGORY_MISSING_DECISION = "missing_decision"
CATEGORY_MISSING_EVIDENCE = "missing_evidence"
CATEGORY_MISSING_REMARKS = "missing_remarks"
CATEGORY_CONTRADICTORY = "contradictory_evidence"
CATEGORY_STALE = "stale_evidence"
CATEGORY_UNRESOLVED_FAILURE = "unresolved_failure_behind_supports"
CATEGORY_INCOMPLETE_METADATA = "incomplete_metadata"
CATEGORY_INCOMPLETE_MANUAL_PLAN = "incomplete_manual_test_plan"
CATEGORY_UNAPPROVED = "unapproved_criterion"

CATEGORY_LABELS = {
    CATEGORY_MISSING_DECISION: "Missing decision",
    CATEGORY_MISSING_EVIDENCE: "Missing evidence",
    CATEGORY_MISSING_REMARKS: "Missing remarks",
    CATEGORY_CONTRADICTORY: "Contradictory evidence",
    CATEGORY_STALE: "Stale evidence",
    CATEGORY_UNRESOLVED_FAILURE: "Unresolved failure behind a Supports claim",
    CATEGORY_INCOMPLETE_METADATA: "Incomplete metadata",
    CATEGORY_INCOMPLETE_MANUAL_PLAN: "Incomplete manual test plan",
    CATEGORY_UNAPPROVED: "Unapproved criterion",
}

# PRD §8's report metadata. Every one of these must be present to publish — §21.15 ("The report
# identifies the product version, methods, tools, environments, and reviewers") and §16
# ("Publication must fail if required information is missing").
#
# `report_publication_date` is deliberately NOT here: it is stamped BY publication, so requiring it
# beforehand would make publishing impossible. Same for `approver`, which the sign-off supplies.
REQUIRED_METADATA = (
    "report_title", "product_name", "product_version", "build_id", "release_date",
    "vendor_name", "vendor_contact", "product_description", "evaluation_scope",
    "deployment_environment", "vpat_edition", "wcag_version", "wcag_levels",
    "evaluation_methods", "browsers_tested", "operating_systems_tested",
    "assistive_technologies_tested", "automated_tools", "testing_period_start",
    "testing_period_end", "evaluators",
)

# Metadata that may legitimately be empty, and is therefore reported as an ADVISORY rather than a
# blocker. "No excluded functionality" and "no third-party dependencies" are real, common answers;
# demanding prose for them would train users to type "n/a", which is worse than an empty field.
ADVISORY_METADATA = ("excluded_functionality", "known_dependencies", "general_notes")


@dataclass
class Blocker:
    category: str
    message: str
    criterion_num: str | None = None
    blocking: bool = True
    detail: dict = field(default_factory=dict)

    def to_row(self) -> dict:
        return {"category": self.category, "label": CATEGORY_LABELS.get(self.category, self.category),
                "message": self.message, "criterion_num": self.criterion_num,
                "blocking": self.blocking, "detail": self.detail}


def validate(report: dict, criteria: list[dict], evidence_by_criterion: dict[str, list], *,
             manual_plan_status: dict[str, bool] | None = None,
             changed_workflows: set[str] | None = None,
             reopened_criteria: set[str] | None = None) -> list[Blocker]:
    """Every reason this report cannot publish, worst-first. Empty list == publishable.

    `manual_plan_status` maps criterion -> "its required manual plan is complete". Injected rather
    than derived here because the plan catalog is Phase 3; Phase 1 passes {} and the category
    simply produces no rows, rather than this module pretending to know.
    """
    out: list[Blocker] = []
    plans = manual_plan_status or {}

    # ── Report metadata (PRD §8, §16) ─────────────────────────────────────────────────────────
    for fieldname in REQUIRED_METADATA:
        if not str(report.get(fieldname) or "").strip():
            out.append(Blocker(CATEGORY_INCOMPLETE_METADATA,
                               f"{fieldname.replace('_', ' ')} is required to publish"))
    for fieldname in ADVISORY_METADATA:
        if not str(report.get(fieldname) or "").strip():
            out.append(Blocker(CATEGORY_INCOMPLETE_METADATA,
                               f"{fieldname.replace('_', ' ')} is empty — confirm this is "
                               f"intentional",
                               blocking=False))

    all_evidence = [e for rows in evidence_by_criterion.values() for e in rows]
    stale_map = acr_freshness.evaluate(report, all_evidence, changed_workflows=changed_workflows,
                                       reopened_criteria=reopened_criteria)
    stale_ids = set(stale_map)

    for crit in criteria:
        num = crit["criterion_num"]
        if not crit.get("applicable", True):
            # Applicability is itself a decision needing an explanation (PRD §10), and that is
            # carried as a Not Applicable final status — so an inapplicable criterion is not
            # skipped here, it falls through to the status checks below like any other.
            pass

        evidence = evidence_by_criterion.get(num, [])
        live = [e for e in evidence if e.id not in stale_ids]
        final = crit.get("final_status")
        workflow_state = crit.get("workflow_state")

        # ── Missing decision (PRD §21.10: unevaluated applicable criteria block publication) ──
        if not final:
            if workflow_state == NOT_EVALUATED or workflow_state is None:
                out.append(Blocker(CATEGORY_MISSING_DECISION,
                                   f"{num} has not been evaluated", criterion_num=num))
            else:
                out.append(Blocker(CATEGORY_MISSING_DECISION,
                                   f"{num} has no final conformance status", criterion_num=num))
            continue

        if final not in FINAL_STATUSES:
            # Defence in depth. acr_model refuses to construct such a decision, and the store
            # constrains the column — but a value that reached the database another way must never
            # reach an exported VPAT table, so it is caught once more on the way out.
            out.append(Blocker(CATEGORY_MISSING_DECISION,
                               f"{num} carries {final!r}, which is not a VPAT conformance level",
                               criterion_num=num))
            continue

        # ── Missing remarks (PRD §21.7) ───────────────────────────────────────────────────────
        if final in REMARKS_REQUIRED and not str(crit.get("remarks") or "").strip():
            out.append(Blocker(CATEGORY_MISSING_REMARKS,
                               f"{num} is {final} and requires remarks", criterion_num=num))

        # ── Missing evidence (PRD §21.6: every final status has evidence or an explanation) ───
        if final == SUPPORTS and not live:
            out.append(Blocker(CATEGORY_MISSING_EVIDENCE,
                               f"{num} claims Supports with no live evidence", criterion_num=num))

        # ── Stale evidence (PRD §21.9) ────────────────────────────────────────────────────────
        stale_here = [e for e in evidence if e.id in stale_ids]
        if stale_here and not live:
            out.append(Blocker(
                CATEGORY_STALE,
                f"{num} has only stale evidence "
                f"({', '.join(sorted({stale_map[e.id] for e in stale_here}))}) — stale evidence "
                f"cannot independently support publication",
                criterion_num=num,
                detail={"stale_ids": [e.id for e in stale_here]}))
        elif stale_here:
            out.append(Blocker(
                CATEGORY_STALE,
                f"{num} has {len(stale_here)} stale evidence record(s), retained for audit history",
                criterion_num=num, blocking=False,
                detail={"stale_ids": [e.id for e in stale_here]}))

        # ── Unresolved failure behind a Supports claim (PRD §21.8) ────────────────────────────
        verdict = acr_rules.may_select_final_status(
            final, criterion_num=num, evidence=evidence, remarks=crit.get("remarks"),
            stale_ids=stale_ids)
        if not verdict.allowed:
            failures = acr_rules.open_failures(evidence, stale_ids)
            category = CATEGORY_UNRESOLVED_FAILURE if failures else CATEGORY_CONTRADICTORY
            out.append(Blocker(category, f"{num}: {verdict.reason}", criterion_num=num,
                               detail={"open_failures": [e.id for e in failures]}))

        # ── Contradiction with an approved decision (PRD §13 last bullet) ─────────────────────
        if crit.get("approval_state") == "approved":
            why = acr_rules.contradicts_approved_decision(final, evidence, stale_ids)
            if why:
                out.append(Blocker(CATEGORY_CONTRADICTORY, f"{num}: {why}", criterion_num=num))

        # ── Incomplete manual test plan (PRD §15) ─────────────────────────────────────────────
        if num in plans and not plans[num]:
            out.append(Blocker(CATEGORY_INCOMPLETE_MANUAL_PLAN,
                               f"{num} has an incomplete manual test plan", criterion_num=num))

        # ── Unapproved criterion (PRD §4.2: an approver signs off EVERY applicable criterion) ─
        if crit.get("approval_state") != "approved":
            out.append(Blocker(CATEGORY_UNAPPROVED,
                               f"{num} has not been approved by an authorized reviewer",
                               criterion_num=num))
        elif workflow_state != DECIDED:
            out.append(Blocker(CATEGORY_MISSING_DECISION,
                               f"{num} is approved but its workflow state is {workflow_state!r}",
                               criterion_num=num))

    return out


def blocking(blockers: list[Blocker]) -> list[Blocker]:
    return [b for b in blockers if b.blocking]


def may_publish(blockers: list[Blocker]) -> bool:
    return not blocking(blockers)


def group(blockers: list[Blocker]) -> dict[str, list[dict]]:
    """PRD §15: the validation screen "Groups blockers by category"."""
    out: dict[str, list[dict]] = {}
    for b in blockers:
        out.setdefault(b.category, []).append(b.to_row())
    return out


def summary(blockers: list[Blocker]) -> dict:
    hard = blocking(blockers)
    return {
        "may_publish": not hard,
        "blocking_count": len(hard),
        "advisory_count": len(blockers) - len(hard),
        "by_category": {cat: len(rows) for cat, rows in group(blockers).items()},
    }
