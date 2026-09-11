"""The small, explicit set of supported (format, operation) pairs this prototype can
apply to a local copy — PRD §5: "Start with a small allowlist chosen from existing
adapters that can run safely and have demonstrable saved-file behavior."

The operations here are backed by a genuine, isolated production adapter (see
`production_adapters.py` and `docs/ADAPTER_INVENTORY.md`), not a fixer written for this
prototype. Any operation not listed here is `unsupported_operation` — see
`validation/validator.py`.
"""
from __future__ import annotations

from dataclasses import dataclass

from experiments.document_wide_ai.contracts.v1 import AllowedOperation, DocumentFormat

SET_PDF_FIELD_ACCESSIBLE_NAME = "set_pdf_field_accessible_name"
SET_PDF_FIGURE_ALT_TEXT = "set_pdf_figure_alt_text"
SET_OFFICE_IMAGE_ALT_TEXT = "set_office_image_alt_text"

MAX_VALUE_LEN = 500


@dataclass(frozen=True)
class OperationSpec:
    op: str
    format: DocumentFormat
    locator_prefix: str | None  # PDF locators are prefixed; DOCX locators are "part#name"
    success_criterion: str
    description: str


SUPPORTED_OPERATIONS: tuple[OperationSpec, ...] = (
    OperationSpec(SET_PDF_FIGURE_ALT_TEXT, DocumentFormat.PDF, "pdf:fig:", "1.1.1",
                  "Set existing tagged PDF Figure alt text using the isolated production writer."),
    OperationSpec(
        op=SET_PDF_FIELD_ACCESSIBLE_NAME,
        format=DocumentFormat.PDF,
        locator_prefix="pdf:field:",
        success_criterion="4.1.2",
        description=(
            "Set an AcroForm text field's accessible name (/TU) via the existing, isolated "
            "api.remediate_pdf.apply_pdf_field_name adapter."
        ),
    ),
    OperationSpec(
        op=SET_OFFICE_IMAGE_ALT_TEXT,
        format=DocumentFormat.DOCX,
        locator_prefix=None,
        success_criterion="1.1.1",
        description=(
            "Set an image's alt text (descr=) via the existing, isolated "
            "api.apply_alt.apply_alt_text adapter."
        ),
    ),
)

_BY_OP_FORMAT = {(s.op, s.format): s for s in SUPPORTED_OPERATIONS}


def operation_spec(op: str, fmt: DocumentFormat) -> OperationSpec | None:
    return _BY_OP_FORMAT.get((op, fmt))


def is_supported(op: str, fmt: DocumentFormat) -> bool:
    return (op, fmt) in _BY_OP_FORMAT


def value_ok(op: str, value: object) -> tuple[bool, str | None]:
    """Structural + content constraints on a proposed value, independent of locator
    resolution. Returns (ok, reason_if_not_ok).
    """
    if not isinstance(value, str) or not value.strip():
        return False, "value must be a non-empty string"
    if len(value) > MAX_VALUE_LEN:
        return False, f"value exceeds {MAX_VALUE_LEN} chars"
    if op in (SET_OFFICE_IMAGE_ALT_TEXT, SET_PDF_FIGURE_ALT_TEXT):
        from experiments.document_wide_ai.application.production_adapters import office_is_junk_descr

        if office_is_junk_descr(value):
            return False, "value reads as a filename/generic placeholder, not a real description"
    return True, None


def allowed_operations_for_manifest() -> tuple[AllowedOperation, ...]:
    return tuple(AllowedOperation(op=s.op, format=s.format) for s in SUPPORTED_OPERATIONS)
