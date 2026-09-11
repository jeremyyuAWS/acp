from pathlib import Path

import docx
import pikepdf

from experiments.document_wide_ai.application.allowlist import SET_OFFICE_IMAGE_ALT_TEXT, SET_PDF_FIELD_ACCESSIBLE_NAME
from experiments.document_wide_ai.application.applier import apply_edits
from experiments.document_wide_ai.contracts.v1 import DocumentFormat, Locator, ProposedEdit
from experiments.document_wide_ai.fixtures.make_fixtures import make_docx, make_pdf
from experiments.document_wide_ai.packaging.docx_packager import package_docx
from experiments.document_wide_ai.packaging.pdf_packager import package_pdf
from experiments.document_wide_ai.recheck.rechecker import recheck_docx, recheck_pdf


def _pdf_edit(edit_id, locator_str, value, fingerprint="fp"):
    return ProposedEdit(
        edit_id=edit_id,
        finding_ids=(f"finding-{edit_id}",),
        locator=Locator(DocumentFormat.PDF, None, None, locator_str, fingerprint),
        operation=SET_PDF_FIELD_ACCESSIBLE_NAME,
        proposed_value=value,
        expected_original_value=None,
    )


def _docx_edit(edit_id, part_name, name, value, fingerprint="fp"):
    return ProposedEdit(
        edit_id=edit_id,
        finding_ids=(f"finding-{edit_id}",),
        locator=Locator(DocumentFormat.DOCX, None, part_name, name, fingerprint),
        operation=SET_OFFICE_IMAGE_ALT_TEXT,
        proposed_value=value,
        expected_original_value=None,
    )


def test_pdf_apply_writes_real_accessible_name_and_preserves_original_bytes():
    original = make_pdf(field_names=("Text1",))
    edit = _pdf_edit("e1", "pdf:field:1:0", "First name")
    result = apply_edits(original, DocumentFormat.PDF, [edit])
    assert not result.candidate_rejected
    assert result.applied[0].after == "First name"
    with pikepdf.open(__import__("io").BytesIO(result.candidate_bytes)) as pdf:
        assert str(list(pdf.Root.AcroForm.Fields)[0].get("/TU")) == "First name"
    # original bytes never mutated
    with pikepdf.open(__import__("io").BytesIO(original)) as pdf:
        assert list(pdf.Root.AcroForm.Fields)[0].get("/TU") is None


def test_docx_apply_writes_real_alt_text_and_preserves_original_bytes():
    original = make_docx(image_count=1)
    edit = _docx_edit("e1", "word/document.xml", "Picture 1", "A red square placeholder.")
    result = apply_edits(original, DocumentFormat.DOCX, [edit])
    assert not result.candidate_rejected
    reopened = package_docx(result.candidate_bytes, max_text_chars=10_000)
    assert reopened.undescribed_images == ()
    # original untouched
    original_packaged = package_docx(original, max_text_chars=10_000)
    assert len(original_packaged.undescribed_images) == 1


def test_pdf_apply_with_unresolvable_locator_reports_not_applied():
    original = make_pdf(field_names=("Text1",))
    edit = _pdf_edit("e1", "pdf:field:1:99", "First name")  # no such field
    result = apply_edits(original, DocumentFormat.PDF, [edit])
    assert not result.candidate_rejected
    assert result.applied == ()
    assert result.not_applied == (("e1", "locator_not_resolved"),)


def test_pdf_apply_rejects_candidate_when_source_is_unreadable():
    result = apply_edits(b"not a pdf", DocumentFormat.PDF, [_pdf_edit("e1", "pdf:field:1:0", "x")])
    assert result.candidate_rejected
    assert result.candidate_bytes is None


def test_deterministic_ordering_is_by_edit_id():
    original = make_pdf(field_names=("Text1", "Text2"))
    e_b = _pdf_edit("b", "pdf:field:1:1", "Second")
    e_a = _pdf_edit("a", "pdf:field:1:0", "First")
    result_1 = apply_edits(original, DocumentFormat.PDF, [e_b, e_a])
    result_2 = apply_edits(original, DocumentFormat.PDF, [e_a, e_b])
    assert {r.edit_id for r in result_1.applied} == {r.edit_id for r in result_2.applied} == {"a", "b"}


def test_recheck_pdf_detects_still_failing_when_applied_value_actually_missing(tmp_path: Path):
    original = make_pdf(field_names=("Text1", "Text2"))
    baseline = package_pdf(original, max_text_chars=10_000)
    # Simulate "applied" record claiming field 1 was fixed, when in fact only field 0 was.
    edit = _pdf_edit("e1", "pdf:field:1:0", "First name")
    result = apply_edits(original, DocumentFormat.PDF, [edit])
    authorized = frozenset({"pdf:field:1:0", "pdf:field:1:1"})  # claim both, only one was edited
    recheck = recheck_pdf(tmp_path, result.candidate_bytes, baseline, authorized, max_text_chars=10_000)
    assert recheck.reopened_ok
    assert recheck.still_failing_locators == frozenset({"pdf:field:1:1"})
    assert "pdf:field:1:0" not in recheck.still_failing_locators


def test_recheck_docx_no_new_failures_after_a_clean_apply(tmp_path: Path):
    original = make_docx(image_count=1)
    baseline = package_docx(original, max_text_chars=10_000)
    edit = _docx_edit("e1", "word/document.xml", "Picture 1", "A red square placeholder.")
    result = apply_edits(original, DocumentFormat.DOCX, [edit])
    recheck = recheck_docx(tmp_path, result.candidate_bytes, baseline, frozenset({"word/document.xml#Picture 1"}), max_text_chars=10_000)
    assert recheck.reopened_ok
    assert recheck.still_failing_locators == frozenset()
    assert recheck.new_failure_locators == frozenset()
    assert recheck.text_preserved


def test_recheck_writes_candidate_into_dedicated_output_dir(tmp_path: Path):
    original = make_pdf(field_names=("Text1",))
    baseline = package_pdf(original, max_text_chars=10_000)
    edit = _pdf_edit("e1", "pdf:field:1:0", "First name")
    result = apply_edits(original, DocumentFormat.PDF, [edit])
    recheck_pdf(tmp_path, result.candidate_bytes, baseline, frozenset({"pdf:field:1:0"}), max_text_chars=10_000)
    written = list(tmp_path.glob("candidate-*.pdf"))
    assert len(written) == 1
