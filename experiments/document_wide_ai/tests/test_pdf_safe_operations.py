"""Real saved PDF fixtures for scope enforcement and figure writeback."""
from dataclasses import replace
from io import BytesIO

import pikepdf

from experiments.document_wide_ai.application.applier import apply_edits
from experiments.document_wide_ai.contracts.v1 import DocumentFormat, Locator, ProposedEdit, parse_edit_response
from experiments.document_wide_ai.fixtures.make_fixtures import make_pdf
from experiments.document_wide_ai.packaging.pdf_packager import package_pdf
from experiments.document_wide_ai.recheck.rechecker import recheck_pdf
from experiments.document_wide_ai.tests.test_validator import _manifest, _edit
from experiments.document_wide_ai.request.mock_provider import raw_envelope
from experiments.document_wide_ai.validation.validator import validate_edit_response


def test_manifest_can_disable_a_globally_supported_operation():
    manifest = _manifest(allowed_operations=())
    envelope = parse_edit_response(raw_envelope(source_sha256=manifest.source_sha256, edits=[_edit()]))
    result = validate_edit_response(manifest, envelope)
    assert not result.valid_edits
    assert result.rejected_edits[0].reason == 'unsupported_operation'


def test_operation_cannot_borrow_an_unrelated_selected_criterion():
    manifest = _manifest()
    manifest = replace(manifest, selected_criteria=('1.1.1',), findings=(replace(manifest.findings[0], success_criterion='1.1.1'),))
    envelope = parse_edit_response(raw_envelope(source_sha256=manifest.source_sha256, edits=[_edit()]))
    result = validate_edit_response(manifest, envelope)
    assert not result.valid_edits
    assert result.rejected_edits[0].reason == 'out_of_scope_criterion'


def test_disappeared_pdf_target_is_failure_not_pass(tmp_path):
    original = make_pdf(field_names=('Text1',))
    baseline = package_pdf(original, max_text_chars=10000)
    with pikepdf.open(BytesIO(original)) as pdf:
        pdf.Root.AcroForm.Fields = pikepdf.Array()
        pdf.pages[0].Annots = pikepdf.Array()
        output = BytesIO(); pdf.save(output)
    result = recheck_pdf(tmp_path, output.getvalue(), baseline, frozenset({'pdf:field:1:0'}), max_text_chars=10000)
    assert 'pdf:field:1:0' in result.still_failing_locators
    assert 'pdf:field:1:0' in result.new_failure_locators
    assert 'pdf:field:1:0' in result.unexpected_changes


def test_unreadable_candidate_cannot_be_a_successful_recheck(tmp_path):
    baseline = package_pdf(make_pdf(), max_text_chars=10000)
    result = recheck_pdf(tmp_path, b'not a PDF', baseline, frozenset({'pdf:field:1:0'}), max_text_chars=10000)
    assert not result.reopened_ok


def tagged_pdf():
    with pikepdf.open(BytesIO(make_pdf(field_names=('Text1',)))) as pdf:
        root = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name('/StructTreeRoot')))
        figures = []
        for alt in (None, 'Existing description'):
            fig = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name('/StructElem'), S=pikepdf.Name('/Figure'), Pg=pdf.pages[0].obj, P=root, K=0))
            if alt:
                fig.Alt = pikepdf.String(alt)
            figures.append(fig)
        root.K = pikepdf.Array(figures)
        pdf.Root.StructTreeRoot = root
        output = BytesIO(); pdf.save(output)
        return output.getvalue()


def edit(operation, locator, value):
    return ProposedEdit(locator, ('finding',), Locator(DocumentFormat.PDF, None, None, locator, 'missing'), operation, value, None)


def test_figure_and_field_saved_together_without_changing_sibling(tmp_path):
    original = tagged_pdf()
    from formats.pdf.detectors import non_text_content
    source_path = tmp_path / 'original.pdf'; source_path.write_bytes(original)
    assert len(non_text_content.detect(source_path)) == 1
    edits = [edit('set_pdf_figure_alt_text', 'pdf:fig:1:0', 'Red parking sign'),
             edit('set_pdf_field_accessible_name', 'pdf:field:1:0', 'Patient name')]
    result = apply_edits(original, DocumentFormat.PDF, edits)
    assert not result.candidate_rejected
    assert len(result.applied) == 2
    saved = tmp_path / 'corrected.pdf'; saved.write_bytes(result.candidate_bytes)
    assert non_text_content.detect(saved) == []
    with pikepdf.open(saved) as pdf:
        assert str(pdf.Root.StructTreeRoot.K[0].Alt) == 'Red parking sign'
        assert str(pdf.Root.StructTreeRoot.K[1].Alt) == 'Existing description'
        assert str(pdf.Root.AcroForm.Fields[0].TU) == 'Patient name'
        assert len(pdf.pages) == 1
    with pikepdf.open(BytesIO(original)) as pdf:
        assert '/Alt' not in pdf.Root.StructTreeRoot.K[0]
        assert '/TU' not in pdf.Root.AcroForm.Fields[0]


def test_unknown_figure_cannot_record_applied():
    result = apply_edits(tagged_pdf(), DocumentFormat.PDF,
                         [edit('set_pdf_figure_alt_text', 'pdf:fig:1:99', 'Parking sign')])
    assert not result.applied
    assert result.not_applied == (('pdf:fig:1:99', 'locator_not_resolved'),)


def test_report_rejects_regressions_in_saved_candidate():
    from experiments.document_wide_ai.recheck.rechecker import RecheckResult
    from experiments.document_wide_ai.recheck.report import build_report, Outcome
    manifest = _manifest()
    envelope = parse_edit_response(raw_envelope(source_sha256=manifest.source_sha256, edits=[_edit()]))
    validation = validate_edit_response(manifest, envelope)
    regression = RecheckResult(True, frozenset(), frozenset({'pdf:field:1:1'}), True, ())
    report = build_report(manifest, envelope, validation, None, regression)
    assert report.candidate_rejected_reason
    assert report.outcomes[0].outcome == Outcome.CANDIDATE_REJECTED
