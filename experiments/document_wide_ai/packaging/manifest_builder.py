"""Freeze the input (PRD §1): turn packaged document facts into a
`DocumentContextManifest` binding document identity, selected criteria, and every
remaining finding in that selection. Only facts that are actually deficient (a form
field with no accessible name, an image with no alt text) become findings — a
already-fixed target is not re-proposed.
"""
from __future__ import annotations

from experiments.document_wide_ai.application.allowlist import (
    SET_OFFICE_IMAGE_ALT_TEXT,
    SET_PDF_FIELD_ACCESSIBLE_NAME,
    allowed_operations_for_manifest,
)
from experiments.document_wide_ai.contracts.v1 import (
    CONTRACT_VERSION,
    DocumentContextManifest,
    DocumentFormat,
    Finding,
    Locator,
)
from experiments.document_wide_ai.packaging.docx_packager import (
    EXTRACTOR_VERSION as DOCX_EXTRACTOR_VERSION,
)
from experiments.document_wide_ai.packaging.docx_packager import (
    fingerprint_missing,
    package_docx,
)
from experiments.document_wide_ai.packaging.limits import ExtractionLimits, check_limits
from experiments.document_wide_ai.packaging.pdf_packager import (
    EXTRACTOR_VERSION as PDF_EXTRACTOR_VERSION,
)
from experiments.document_wide_ai.packaging.pdf_packager import (
    fingerprint_value,
    package_pdf,
)
from experiments.document_wide_ai.contracts.v1 import sha256_hex

ADAPTER_VERSION = "document-wide-ai-adapter.v1"

PDF_FIELD_RULE_ID = "pdf.form-field-missing-accessible-name"
DOCX_IMAGE_RULE_ID = "office.missing-alt-text"


def build_pdf_manifest(
    source_bytes: bytes,
    *,
    document_id: str,
    assessment_revision: str,
    selected_criteria: tuple[str, ...] = ("4.1.2",),
    limits: ExtractionLimits = ExtractionLimits(),
) -> DocumentContextManifest:
    packaged = package_pdf(source_bytes, max_text_chars=limits.max_text_chars)

    findings = []
    if "4.1.2" in selected_criteria:
        for i, fld in enumerate(packaged.form_fields):
            if fld.current_tu:
                continue
            findings.append(
                Finding(
                    finding_id=f"pdf-field-{i}",
                    rule_id=PDF_FIELD_RULE_ID,
                    success_criterion="4.1.2",
                    locator=Locator(
                        format=DocumentFormat.PDF,
                        page_index=None,
                        part_name=None,
                        element_ref=fld.locator,
                        fingerprint=fingerprint_value(fld.current_tu),
                    ),
                )
            )

    check_limits(
        text_chars=len(packaged.text_context),
        page_count=packaged.page_count,
        image_count=0,
        finding_count=len(findings),
        limits=limits,
    )

    return DocumentContextManifest(
        contract_version=CONTRACT_VERSION,
        extractor_version=PDF_EXTRACTOR_VERSION,
        adapter_version=ADAPTER_VERSION,
        document_id=document_id,
        document_format=DocumentFormat.PDF,
        source_sha256=sha256_hex(source_bytes),
        assessment_revision=assessment_revision,
        selected_criteria=selected_criteria,
        findings=tuple(findings),
        allowed_operations=tuple(
            op for op in allowed_operations_for_manifest() if op.op == SET_PDF_FIELD_ACCESSIBLE_NAME
        ),
        text_context=packaged.text_context,
        extraction_issues=packaged.extraction_issues,
    )


def build_docx_manifest(
    source_bytes: bytes,
    *,
    document_id: str,
    assessment_revision: str,
    selected_criteria: tuple[str, ...] = ("1.1.1",),
    limits: ExtractionLimits = ExtractionLimits(),
) -> DocumentContextManifest:
    packaged = package_docx(source_bytes, max_text_chars=limits.max_text_chars)

    findings = []
    if "1.1.1" in selected_criteria:
        for i, img in enumerate(packaged.undescribed_images):
            findings.append(
                Finding(
                    finding_id=f"docx-image-{i}",
                    rule_id=DOCX_IMAGE_RULE_ID,
                    success_criterion="1.1.1",
                    locator=Locator(
                        format=DocumentFormat.DOCX,
                        page_index=None,
                        part_name=img.part_name,
                        element_ref=img.name,
                        fingerprint=fingerprint_missing(),
                    ),
                )
            )

    check_limits(
        text_chars=len(packaged.text_context),
        page_count=0,
        image_count=len(packaged.undescribed_images),
        finding_count=len(findings),
        limits=limits,
    )

    return DocumentContextManifest(
        contract_version=CONTRACT_VERSION,
        extractor_version=DOCX_EXTRACTOR_VERSION,
        adapter_version=ADAPTER_VERSION,
        document_id=document_id,
        document_format=DocumentFormat.DOCX,
        source_sha256=sha256_hex(source_bytes),
        assessment_revision=assessment_revision,
        selected_criteria=selected_criteria,
        findings=tuple(findings),
        allowed_operations=tuple(
            op for op in allowed_operations_for_manifest() if op.op == SET_OFFICE_IMAGE_ALT_TEXT
        ),
        text_context=packaged.text_context,
        extraction_issues=packaged.extraction_issues,
    )
