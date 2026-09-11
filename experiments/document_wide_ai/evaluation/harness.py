"""Orchestrate the full pipeline — package → freeze manifest → one request → validate →
apply → recheck → report — for a repeatable evaluation run. One call to `run_pipeline`
is exactly one generation invocation against the mock provider (acceptance criterion 3).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from experiments.document_wide_ai.application.applier import ApplicationResult, apply_edits
from experiments.document_wide_ai.contracts.v1 import (
    ContractError,
    DocumentContextManifest,
    DocumentFormat,
    EditResponseEnvelope,
)
from experiments.document_wide_ai.evaluation.cost import CostRecord, record_cost, timed
from experiments.document_wide_ai.packaging.docx_packager import package_docx
from experiments.document_wide_ai.packaging.limits import ExtractionLimits
from experiments.document_wide_ai.packaging.pdf_packager import package_pdf
from experiments.document_wide_ai.recheck.rechecker import RecheckResult, recheck_docx, recheck_pdf
from experiments.document_wide_ai.recheck.report import FindingOutcome, Outcome, OutcomeReport, build_report
from experiments.document_wide_ai.request.builder import GenerationRequest, build_request
from experiments.document_wide_ai.request.mock_provider import MockProvider
from experiments.document_wide_ai.validation.validator import ValidationResult, validate_edit_response


@dataclass(frozen=True)
class RunResult:
    manifest: DocumentContextManifest
    request: GenerationRequest
    envelope: EditResponseEnvelope | None
    validation: ValidationResult | None
    application: ApplicationResult | None
    recheck: RecheckResult | None
    report: OutcomeReport
    cost: CostRecord | None


def run_pipeline(
    source_bytes: bytes,
    manifest: DocumentContextManifest,
    provider: MockProvider,
    output_dir: Path,
    *,
    limits: ExtractionLimits = ExtractionLimits(),
) -> RunResult:
    request = build_request(manifest, request_id=f"req-{manifest.document_id}")

    try:
        with timed() as t:
            envelope = provider.generate(request)
    except ContractError as exc:
        outcomes = tuple(
            FindingOutcome(f.finding_id, Outcome.INVALID_OR_CONFLICTING, f"malformed_response: {exc}")
            for f in manifest.findings
        )
        report = OutcomeReport(manifest.document_id, None, outcomes)
        return RunResult(manifest, request, None, None, None, None, report, None)

    cost = record_cost(request, envelope, latency_ms=t["latency_ms"])
    validation = validate_edit_response(manifest, envelope)
    application = apply_edits(source_bytes, manifest.document_format, list(validation.valid_edits))

    recheck: RecheckResult | None = None
    if not application.candidate_rejected:
        authorized = frozenset(a.locator for a in application.applied)
        if manifest.document_format == DocumentFormat.PDF:
            baseline = package_pdf(source_bytes, max_text_chars=limits.max_text_chars)
            recheck = recheck_pdf(
                output_dir, application.candidate_bytes, baseline, authorized, max_text_chars=limits.max_text_chars
            )
        else:
            baseline = package_docx(source_bytes, max_text_chars=limits.max_text_chars)
            recheck = recheck_docx(
                output_dir, application.candidate_bytes, baseline, authorized, max_text_chars=limits.max_text_chars
            )

    report = build_report(manifest, envelope, validation, application, recheck)
    return RunResult(manifest, request, envelope, validation, application, recheck, report, cost)
