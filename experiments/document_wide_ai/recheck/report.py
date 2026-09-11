"""The final per-finding outcome report (PRD §6, acceptance criterion 10). Separates
proposals, applied edits, detector outcomes, semantic-review requirements, and rejected
candidates — never claims full document conformance.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from experiments.document_wide_ai.application.applier import ApplicationResult
from experiments.document_wide_ai.contracts.v1 import DocumentContextManifest, EditResponseEnvelope
from experiments.document_wide_ai.recheck.rechecker import RecheckResult
from experiments.document_wide_ai.validation.validator import UNSUPPORTED_OPERATION as _VALIDATOR_UNSUPPORTED
from experiments.document_wide_ai.validation.validator import ValidationResult


class Outcome(str, Enum):
    APPLIED_DETECTOR_PASSED = "applied_detector_passed"
    APPLIED_SEMANTIC_REVIEW_NEEDED = "applied_semantic_review_needed"
    STILL_DETECTED = "still_detected"
    UNSUPPORTED_OPERATION = "unsupported_operation"
    INVALID_OR_CONFLICTING = "invalid_or_conflicting"
    MISSING_CONTEXT = "missing_context"
    MODEL_OMITTED = "model_omitted"
    VERIFICATION_UNAVAILABLE = "verification_unavailable"
    CANDIDATE_REJECTED = "candidate_rejected"


@dataclass(frozen=True)
class FindingOutcome:
    finding_id: str
    outcome: Outcome
    detail: str = ""


@dataclass(frozen=True)
class OutcomeReport:
    document_id: str
    candidate_rejected_reason: str | None
    outcomes: tuple[FindingOutcome, ...]

    def summary(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for o in self.outcomes:
            counts[o.outcome.value] = counts.get(o.outcome.value, 0) + 1
        return counts


def build_report(
    manifest: DocumentContextManifest,
    envelope: EditResponseEnvelope | None,
    validation: ValidationResult,
    application: ApplicationResult | None,
    recheck: RecheckResult | None,
) -> OutcomeReport:
    finding_ids = [f.finding_id for f in manifest.findings]

    if application is not None and application.candidate_rejected:
        outcomes = tuple(
            FindingOutcome(fid, Outcome.CANDIDATE_REJECTED, application.candidate_rejected_reason or "")
            for fid in finding_ids
        )
        return OutcomeReport(manifest.document_id, application.candidate_rejected_reason, outcomes)

    if recheck is not None and recheck.reopened_ok and (
        recheck.new_failure_locators or recheck.unexpected_changes or not recheck.text_preserved
    ):
        reason = "saved candidate changed unrelated content or introduced new failures"
        return OutcomeReport(manifest.document_id, reason, tuple(
            FindingOutcome(fid, Outcome.CANDIDATE_REJECTED, reason) for fid in finding_ids
        ))

    edit_by_finding: dict[str, str] = {}
    for edit in (envelope.edits if envelope else ()):
        for fid in edit.finding_ids:
            edit_by_finding[fid] = edit.edit_id

    rejected_by_edit = {r.edit_id: r for r in validation.rejected_edits}
    unresolved_by_finding = {u.finding_id: u for u in validation.unresolved}
    applied_by_edit = {a.edit_id: a for a in (application.applied if application else ())}
    not_applied_by_edit = dict(application.not_applied) if application else {}

    outcomes = []
    for fid in finding_ids:
        if fid in validation.model_omitted_finding_ids:
            outcomes.append(FindingOutcome(fid, Outcome.MODEL_OMITTED))
            continue

        edit_id = edit_by_finding.get(fid)
        if edit_id is None:
            u = unresolved_by_finding.get(fid)
            outcomes.append(FindingOutcome(fid, Outcome.MISSING_CONTEXT, u.reason if u else ""))
            continue

        rejected = rejected_by_edit.get(edit_id)
        if rejected is not None:
            if rejected.reason in (_VALIDATOR_UNSUPPORTED,):
                outcomes.append(FindingOutcome(fid, Outcome.UNSUPPORTED_OPERATION, rejected.reason))
            else:
                outcomes.append(FindingOutcome(fid, Outcome.INVALID_OR_CONFLICTING, rejected.reason))
            continue

        if application is None or recheck is None or not recheck.reopened_ok:
            outcomes.append(FindingOutcome(fid, Outcome.VERIFICATION_UNAVAILABLE))
            continue

        applied = applied_by_edit.get(edit_id)
        if applied is None:
            reason = not_applied_by_edit.get(edit_id, "not_applied")
            outcomes.append(FindingOutcome(fid, Outcome.STILL_DETECTED, reason))
            continue

        if applied.locator in recheck.still_failing_locators:
            outcomes.append(FindingOutcome(fid, Outcome.STILL_DETECTED, "detector still fails after apply"))
        else:
            # A detector accepting a non-empty value never establishes the AI-authored text
            # is CORRECT (PRD §6) — both allowlisted operations write free-text human-facing
            # content, so a detector pass always routes to semantic review, never straight
            # to APPLIED_DETECTOR_PASSED (reserved for a future non-semantic operation, of
            # which the allowlist currently has none).
            outcomes.append(FindingOutcome(fid, Outcome.APPLIED_SEMANTIC_REVIEW_NEEDED))

    return OutcomeReport(manifest.document_id, None, tuple(outcomes))
