"""Strict, structural + semantic validation of a model's edit-response envelope against
the frozen manifest it was generated from (PRD §4). Nothing is applied until every check
here passes; document content is treated as untrusted — nothing in `manifest.text_context`
or `evidence` can expand what an edit is allowed to do, because every check below is
against the manifest's own structured fields, never against free text.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from experiments.document_wide_ai.application.allowlist import operation_spec, value_ok
from experiments.document_wide_ai.contracts.v1 import (
    DocumentContextManifest,
    EditResponseEnvelope,
    Finding,
    ProposedEdit,
    UnresolvedEntry,
)

# Reasons a proposed edit can be rejected before application.
STALE_SOURCE_HASH = "stale_source_hash"
UNKNOWN_FINDING_ID = "unknown_finding_id"
LOCATOR_MISMATCH = "locator_mismatch"
OUT_OF_SCOPE_CRITERION = "out_of_scope_criterion"
UNSUPPORTED_OPERATION = "unsupported_operation"
INVALID_VALUE = "invalid_value"
STALE_PRECONDITION = "stale_precondition"
CONFLICT = "conflict"


@dataclass(frozen=True)
class RejectedEdit:
    edit_id: str
    reason: str
    detail: str = ""


@dataclass(frozen=True)
class ValidationResult:
    valid_edits: tuple[ProposedEdit, ...]
    rejected_edits: tuple[RejectedEdit, ...]
    model_omitted_finding_ids: tuple[str, ...]
    unresolved: tuple[UnresolvedEntry, ...]


def _findings_by_id(manifest: DocumentContextManifest) -> dict[str, Finding]:
    return {f.finding_id: f for f in manifest.findings}


def _check_single_edit(edit: ProposedEdit, manifest: DocumentContextManifest, by_id: dict[str, Finding]) -> str | None:
    """Returns a rejection reason, or None if the edit passes every per-edit check."""
    if not edit.finding_ids or any(fid not in by_id for fid in edit.finding_ids):
        return UNKNOWN_FINDING_ID

    findings = [by_id[fid] for fid in edit.finding_ids]
    target_key = findings[0].locator.key()
    if any(f.locator.key() != target_key for f in findings) or edit.locator.key() != target_key:
        return LOCATOR_MISMATCH

    if any(f.success_criterion not in manifest.selected_criteria for f in findings):
        return OUT_OF_SCOPE_CRITERION

    spec = operation_spec(edit.operation, manifest.document_format)
    if spec is None:
        return UNSUPPORTED_OPERATION
    if spec.locator_prefix is not None and not edit.locator.element_ref.startswith(spec.locator_prefix):
        return UNSUPPORTED_OPERATION

    ok, _reason = value_ok(edit.operation, edit.proposed_value)
    if not ok:
        return INVALID_VALUE

    if edit.locator.fingerprint != findings[0].locator.fingerprint:
        return STALE_PRECONDITION

    return None


def validate_edit_response(manifest: DocumentContextManifest, envelope: EditResponseEnvelope) -> ValidationResult:
    by_id = _findings_by_id(manifest)

    covered = set(u.finding_id for u in envelope.unresolved)
    for e in envelope.edits:
        covered.update(e.finding_ids)
    model_omitted = tuple(sorted(manifest.finding_ids() - covered))

    if envelope.source_sha256 != manifest.source_sha256:
        rejected = tuple(
            RejectedEdit(edit_id=e.edit_id, reason=STALE_SOURCE_HASH, detail="response source hash does not match manifest")
            for e in envelope.edits
        )
        return ValidationResult((), rejected, model_omitted, envelope.unresolved)

    rejected: list[RejectedEdit] = []
    provisional: list[ProposedEdit] = []
    for edit in envelope.edits:
        reason = _check_single_edit(edit, manifest, by_id)
        if reason is not None:
            rejected.append(RejectedEdit(edit_id=edit.edit_id, reason=reason))
        else:
            provisional.append(edit)

    by_target: dict[tuple, list[ProposedEdit]] = defaultdict(list)
    for edit in provisional:
        by_target[edit.locator.key()].append(edit)

    valid: list[ProposedEdit] = []
    for target, group in by_target.items():
        if len(group) > 1:
            rejected.extend(
                RejectedEdit(edit_id=e.edit_id, reason=CONFLICT, detail=f"{len(group)} edits target the same locator")
                for e in group
            )
        else:
            valid.append(group[0])

    return ValidationResult(tuple(valid), tuple(rejected), model_omitted, envelope.unresolved)
