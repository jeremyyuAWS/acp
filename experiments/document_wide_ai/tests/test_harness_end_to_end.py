from pathlib import Path

from experiments.document_wide_ai.application.allowlist import SET_OFFICE_IMAGE_ALT_TEXT, SET_PDF_FIELD_ACCESSIBLE_NAME
from experiments.document_wide_ai.evaluation.cost import compare_document_wide_vs_repeated
from experiments.document_wide_ai.evaluation.harness import run_pipeline
from experiments.document_wide_ai.fixtures.make_fixtures import make_docx, make_pdf
from experiments.document_wide_ai.packaging.manifest_builder import build_docx_manifest, build_pdf_manifest
from experiments.document_wide_ai.recheck.report import Outcome
from experiments.document_wide_ai.request.mock_provider import MockProvider, edit_dict, raw_envelope


def test_one_package_produces_exactly_one_generation_call(tmp_path: Path):
    data = make_pdf(field_names=("Text1", "Text2"))
    manifest = build_pdf_manifest(data, document_id="doc-1", assessment_revision="rev-1")
    f0, f1 = manifest.findings
    provider = MockProvider(
        responses={
            f"req-{manifest.document_id}": raw_envelope(
                source_sha256=manifest.source_sha256,
                edits=[
                    edit_dict(
                        edit_id="e1", finding_ids=[f0.finding_id], locator_format="pdf",
                        element_ref=f0.locator.element_ref, fingerprint=f0.locator.fingerprint,
                        page_index=f0.locator.page_index,
                        operation=SET_PDF_FIELD_ACCESSIBLE_NAME, proposed_value="First name",
                    )
                ],
                unresolved=[{"finding_id": f1.finding_id, "reason": "insufficient_evidence"}],
            )
        }
    )
    result = run_pipeline(data, manifest, provider, tmp_path)
    assert provider.call_count == 1
    ids = {o.finding_id for o in result.report.outcomes}
    assert ids == {f0.finding_id, f1.finding_id}  # every selected finding appears in the final report
    outcome_by_id = {o.finding_id: o.outcome for o in result.report.outcomes}
    assert outcome_by_id[f0.finding_id] == Outcome.APPLIED_SEMANTIC_REVIEW_NEEDED
    assert outcome_by_id[f1.finding_id] == Outcome.MISSING_CONTEXT


def test_docx_end_to_end_applies_and_verifies_real_saved_file(tmp_path: Path):
    data = make_docx(image_count=1)
    manifest = build_docx_manifest(data, document_id="doc-2", assessment_revision="rev-1")
    finding = manifest.findings[0]
    provider = MockProvider(
        responses={
            f"req-{manifest.document_id}": raw_envelope(
                source_sha256=manifest.source_sha256,
                edits=[
                    edit_dict(
                        edit_id="e1", finding_ids=[finding.finding_id], locator_format="docx",
                        element_ref=finding.locator.element_ref, part_name=finding.locator.part_name,
                        fingerprint=finding.locator.fingerprint,
                        operation=SET_OFFICE_IMAGE_ALT_TEXT,
                        proposed_value="A small red square used as a placeholder graphic.",
                    )
                ],
            )
        }
    )
    result = run_pipeline(data, manifest, provider, tmp_path)
    assert result.application is not None and not result.application.candidate_rejected
    assert result.recheck is not None and result.recheck.reopened_ok
    assert result.recheck.still_failing_locators == frozenset()
    assert result.report.outcomes[0].outcome == Outcome.APPLIED_SEMANTIC_REVIEW_NEEDED


def test_cost_comparison_shows_document_wide_sends_prefix_once(tmp_path: Path):
    data = make_pdf(field_names=("Text1", "Text2", "Text3"))
    manifest = build_pdf_manifest(data, document_id="doc-3", assessment_revision="rev-1")
    provider = MockProvider(default_response_fn=lambda req: raw_envelope(
        source_sha256=manifest.source_sha256,
        unresolved=[{"finding_id": f.finding_id, "reason": "insufficient_evidence"} for f in manifest.findings],
    ))
    result = run_pipeline(data, manifest, provider, tmp_path)
    comparison = compare_document_wide_vs_repeated(manifest, result.request)
    assert comparison.document_wide_requests == 1
    assert comparison.repeated_per_finding_requests == len(manifest.findings) == 3
    assert comparison.repeated_per_finding_prefix_chars_sent == comparison.document_wide_prefix_chars_sent * 3
    assert result.cost is not None and result.cost.provider_cost_usd is None  # mock: never a real charge
