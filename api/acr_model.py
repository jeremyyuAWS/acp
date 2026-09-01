"""ACR domain vocabulary and record shapes (PRD §11 evidence model, §9 criteria matrix).

Pure data + validation. No I/O, no store access, no policy decisions — those live in acr_rules.py
(what a piece of evidence permits) and acr_validation.py (what a report needs to publish). Split
that way so the decision rules can be tested against constructed records with no database.

TWO VOCABULARIES THAT MUST NOT MERGE, restated here because the merge is easy and silent:

  final_status    — the four VPAT terms, exactly (acr_catalog.FINAL_STATUSES). What a customer
                    reads in the exported report.
  workflow_state  — ACP's internal draft states (not_evaluated / needs_review / decided). Never
                    exported, never rendered as a conformance level.

PRD §9 permits the second only on the condition that it never appears as the first. Keeping them in
separate columns with separate constants is that condition expressed in code rather than in review
discipline.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

from acr_catalog import FINAL_STATUSES, REMARKS_REQUIRED

# ── Evidence source kinds (PRD §11) ────────────────────────────────────────────────────────────
# The full list the PRD names. Phase 1 produces AUTOMATED and MANUAL/KEYBOARD/SCREEN_READER rows;
# the rest are declared now so the column's vocabulary is fixed before data exists, rather than
# grown ad hoc once reports are live.
SRC_AUTOMATED = "automated"
SRC_MANUAL = "manual"
SRC_KEYBOARD = "keyboard"
SRC_SCREEN_READER = "screen_reader"
SRC_VISUAL = "visual"
SRC_CODE = "code"
SRC_USER = "user"
SRC_DOCUMENTATION = "documentation"
SRC_EXTERNAL = "external"
SRC_REMEDIATION_VERIFICATION = "remediation_verification"

SOURCE_KINDS: frozenset[str] = frozenset({
    SRC_AUTOMATED, SRC_MANUAL, SRC_KEYBOARD, SRC_SCREEN_READER, SRC_VISUAL, SRC_CODE, SRC_USER,
    SRC_DOCUMENTATION, SRC_EXTERNAL, SRC_REMEDIATION_VERIFICATION,
})

# Kinds produced by a machine with no human in the loop. The distinction is load-bearing, not
# cosmetic: acr_rules refuses to draft "Supports" from these alone (PRD §4.3). SRC_EXTERNAL is
# deliberately NOT here — an external assessor's report is human judgement ACP did not perform.
AUTOMATED_KINDS: frozenset[str] = frozenset({SRC_AUTOMATED})

# Kinds that record a person exercising the product. PRD §4.3 names the judgement types that must
# reach a human: keyboard, screen-reader, visual, cognitive, content, usability.
HUMAN_KINDS: frozenset[str] = SOURCE_KINDS - AUTOMATED_KINDS

# ── Evidence results ───────────────────────────────────────────────────────────────────────────
# PRD §14: "Each test must record Pass, Fail, Not Applicable, or Blocked."
RESULT_PASS = "pass"
RESULT_FAIL = "fail"
RESULT_NOT_APPLICABLE = "not_applicable"
RESULT_BLOCKED = "blocked"
RESULTS: frozenset[str] = frozenset({RESULT_PASS, RESULT_FAIL, RESULT_NOT_APPLICABLE,
                                     RESULT_BLOCKED})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class AcrValidationError(ValueError):
    """A record was constructed with a value outside its declared vocabulary."""


@dataclass
class Evidence:
    """One evidence record (PRD §11).

    APPEND-ONLY by contract. PRD §12 requires a stale record to remain "visible for audit history",
    and §17 requires evidence additions AND removals to be auditable — so nothing here is ever
    UPDATEd or DELETEd. A retraction is a tombstone in acr_decision_log plus a superseding row, not
    an edit. `stale_reason` is the one field the store may fill in later, and even that is only a
    cache of what acr_freshness derives (see that module on why staleness is computed, not stored,
    as the source of truth).

    `coverage` is the field the whole automated-evidence honesty rule turns on. It is an
    assessment.Coverage value — the SAME enum the document pipeline already gates certification on
    (assessment.CAN_CERTIFY_PASS, ADR 0031) — and it declares how much of the criterion the
    technique that produced this row actually reaches. It is REQUIRED for automated evidence and
    meaningless for human evidence, where a person judged the criterion as asked.

    `tool_name` / `tool_version` / `rule_id` / `tested_url` preserve the original automated result
    (PRD §13: "Preserve the original rule ID and result").
    """
    criterion_num: str
    source_kind: str
    result: str
    report_id: str
    # who / when / against what
    tester: str | None = None
    tested_at: str = field(default_factory=_now)
    product_version: str | None = None
    build_id: str | None = None
    environment: str | None = None
    workflow: str | None = None
    browser: str | None = None
    assistive_tech: str | None = None
    # automated provenance (PRD §13)
    tool_name: str | None = None
    tool_version: str | None = None
    rule_id: str | None = None
    tested_url: str | None = None
    coverage: str | None = None
    # narrative
    method: str | None = None
    notes: str | None = None
    attachments: list[str] = field(default_factory=list)
    related_finding_ids: list[str] = field(default_factory=list)
    # bookkeeping
    id: str = field(default_factory=lambda: _new_id("acrev"))
    created_at: str = field(default_factory=_now)
    stale_reason: str | None = None

    def __post_init__(self) -> None:
        if self.source_kind not in SOURCE_KINDS:
            raise AcrValidationError(
                f"source_kind {self.source_kind!r} is not one of {sorted(SOURCE_KINDS)}")
        if self.result not in RESULTS:
            raise AcrValidationError(f"result {self.result!r} is not one of {sorted(RESULTS)}")
        if self.source_kind in AUTOMATED_KINDS:
            # An automated row with no declared coverage would sail past acr_rules' coverage gate
            # as "unknown", which is exactly the state that must never silently mean "fine". Refuse
            # it at construction, where the caller can still say what its tool reaches.
            if not self.coverage:
                raise AcrValidationError(
                    "automated evidence must declare `coverage` (assessment.Coverage) — an "
                    "automated result with unknown coverage cannot be weighed against a criterion")
            if not self.tool_name:
                raise AcrValidationError(
                    "automated evidence must name its tool (PRD §11: preserve the tool name, "
                    "version, rule ID and original result)")

    @property
    def is_automated(self) -> bool:
        return self.source_kind in AUTOMATED_KINDS

    def to_row(self) -> dict:
        return asdict(self)


@dataclass
class CriterionDecision:
    """A human's final conformance decision for one criterion (PRD §9, §10).

    Constructing one does NOT mean it is permitted — acr_rules.may_select_final_status is the gate,
    and it needs the criterion's evidence to answer. This type only enforces the vocabulary and the
    remarks requirement, both of which are decidable from the decision alone.
    """
    report_id: str
    criterion_num: str
    final_status: str
    decided_by: str
    remarks: str | None = None
    decided_at: str = field(default_factory=_now)

    def __post_init__(self) -> None:
        if self.final_status not in FINAL_STATUSES:
            raise AcrValidationError(
                f"final_status {self.final_status!r} is not a VPAT conformance level "
                f"{sorted(FINAL_STATUSES)} — internal workflow states never go in this field")
        if self.final_status in REMARKS_REQUIRED and not (self.remarks or "").strip():
            raise AcrValidationError(
                f"{self.final_status!r} requires remarks (PRD §10, §21.7)")
        if not (self.decided_by or "").strip():
            raise AcrValidationError("a decision must record who made it (PRD §4.2)")
