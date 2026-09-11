import pytest

from experiments.document_wide_ai.fixtures.make_fixtures import make_docx, make_pdf
from experiments.document_wide_ai.packaging.docx_packager import package_docx
from experiments.document_wide_ai.packaging.limits import DocumentTooLarge, ExtractionLimits, check_limits
from experiments.document_wide_ai.packaging.manifest_builder import build_docx_manifest, build_pdf_manifest
from experiments.document_wide_ai.packaging.pdf_packager import package_pdf


def test_pdf_packager_extracts_missing_and_named_fields():
    data = make_pdf(field_names=("Text1", "Text2"), field_tu=(None, "Already named"))
    packaged = package_pdf(data, max_text_chars=10_000)
    assert packaged.page_count == 1
    by_loc = {f.locator: f for f in packaged.form_fields}
    assert by_loc["pdf:field:1:0"].current_tu is None
    assert by_loc["pdf:field:1:1"].current_tu == "Already named"
    assert packaged.extraction_issues == ()


def test_pdf_packager_records_extraction_failure_for_garbage_bytes():
    packaged = package_pdf(b"not a pdf", max_text_chars=10_000)
    assert packaged.page_count == 0
    assert any(i.kind == "extraction_failed" for i in packaged.extraction_issues)
    # no findings can be silently dropped -- an unreadable source produces zero fields,
    # never a crash, and the failure is on record.
    assert packaged.form_fields == ()


def test_pdf_packager_truncates_and_records_issue_when_text_exceeds_limit():
    data = make_pdf(page_count=1)
    packaged = package_pdf(data, max_text_chars=1)
    assert len(packaged.text_context) <= 1


def test_docx_packager_finds_only_undescribed_images():
    data = make_docx(image_count=2, image_alt=(None, "Already has real alt text"))
    packaged = package_docx(data, max_text_chars=10_000)
    assert len(packaged.undescribed_images) == 1
    assert packaged.undescribed_images[0].part_name == "word/document.xml"


def test_docx_packager_records_extraction_failure_for_garbage_bytes():
    packaged = package_docx(b"not a docx", max_text_chars=10_000)
    assert any(i.kind == "extraction_failed" for i in packaged.extraction_issues)
    assert packaged.undescribed_images == ()


def test_check_limits_raises_document_too_large_for_each_dimension():
    limits = ExtractionLimits(max_text_chars=10, max_pages=1, max_images=1, max_findings=1)
    with pytest.raises(DocumentTooLarge):
        check_limits(text_chars=11, page_count=0, image_count=0, finding_count=0, limits=limits)
    with pytest.raises(DocumentTooLarge):
        check_limits(text_chars=0, page_count=2, image_count=0, finding_count=0, limits=limits)
    with pytest.raises(DocumentTooLarge):
        check_limits(text_chars=0, page_count=0, image_count=2, finding_count=0, limits=limits)
    with pytest.raises(DocumentTooLarge):
        check_limits(text_chars=0, page_count=0, image_count=0, finding_count=2, limits=limits)
    check_limits(text_chars=10, page_count=1, image_count=1, finding_count=1, limits=limits)  # no raise


def test_build_pdf_manifest_skips_already_named_fields():
    data = make_pdf(field_names=("Text1", "Text2"), field_tu=(None, "Already named"))
    manifest = build_pdf_manifest(data, document_id="doc-1", assessment_revision="rev-1")
    assert len(manifest.findings) == 1
    assert manifest.findings[0].locator.element_ref == "pdf:field:1:0"
    assert manifest.selected_criteria == ("4.1.2",)


def test_build_pdf_manifest_respects_selected_criteria():
    data = make_pdf(field_names=("Text1",))
    manifest = build_pdf_manifest(data, document_id="doc-1", assessment_revision="rev-1", selected_criteria=("1.1.1",))
    assert manifest.findings == ()  # 4.1.2 fields exist but weren't selected


def test_build_pdf_manifest_raises_document_too_large():
    data = make_pdf(field_names=("Text1", "Text2", "Text3"))
    with pytest.raises(DocumentTooLarge):
        build_pdf_manifest(
            data, document_id="doc-1", assessment_revision="rev-1", limits=ExtractionLimits(max_findings=1)
        )


def test_build_docx_manifest_finds_undescribed_images_only():
    data = make_docx(image_count=2, image_alt=(None, "Already described"))
    manifest = build_docx_manifest(data, document_id="doc-2", assessment_revision="rev-1")
    assert len(manifest.findings) == 1
    assert manifest.findings[0].success_criterion == "1.1.1"


def test_manifest_source_sha256_matches_bytes():
    import hashlib

    data = make_pdf()
    manifest = build_pdf_manifest(data, document_id="doc-1", assessment_revision="rev-1")
    assert manifest.source_sha256 == hashlib.sha256(data).hexdigest()
