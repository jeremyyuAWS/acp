"""PDF document-context packaging.

Scope, deliberately small: this prototype extracts page text plus the one structural
fact its allowlisted operation needs — AcroForm field accessible names (/TU), WCAG
4.1.2 — using the *same* locator-minting helpers `api/remediate_pdf.py` uses at apply
time (`_collect_form_fields`, `_form_field_locators`), so a locator built here always
resolves at application time (see `application/applier.py`). This is not a general PDF
structure-tree extractor. Per the PRD, prefer extracted text over submitting a native
PDF; images are out of scope for this packager (no allowlisted operation needs them).

Extraction failures are recorded as `ExtractionIssue`s, never silently dropped.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO

import pikepdf
import pypdf

from experiments.document_wide_ai.application.production_adapters import (
    collect_pdf_form_fields,
    pdf_form_field_locators,
)
from experiments.document_wide_ai.contracts.v1 import ExtractionIssue, sha256_hex

EXTRACTOR_VERSION = "pdf-extractor.v1"


@dataclass(frozen=True)
class PdfFormField:
    locator: str  # "pdf:field:{page}:{seq}"
    current_tu: str | None  # None means no accessible name set


@dataclass(frozen=True)
class PackagedPdf:
    extractor_version: str
    page_count: int
    text_context: str
    form_fields: tuple[PdfFormField, ...]
    extraction_issues: tuple[ExtractionIssue, ...] = field(default_factory=tuple)

    def field_by_locator(self, locator: str) -> PdfFormField | None:
        for f in self.form_fields:
            if f.locator == locator:
                return f
        return None


def fingerprint_value(current_value: str | None) -> str:
    return sha256_hex((current_value or "<missing>").encode("utf-8"))


def package_pdf(source_bytes: bytes, *, max_text_chars: int) -> PackagedPdf:
    issues: list[ExtractionIssue] = []
    text_parts: list[str] = []
    page_count = 0

    try:
        reader = pypdf.PdfReader(BytesIO(source_bytes))
        page_count = len(reader.pages)
        for i, page in enumerate(reader.pages):
            try:
                text_parts.append(page.extract_text() or "")
            except Exception as exc:  # pragma: no cover - defensive, pypdf-internal failures
                issues.append(
                    ExtractionIssue(
                        kind="extraction_failed",
                        detail=f"page {i} text extraction failed: {exc}",
                    )
                )
    except Exception as exc:
        issues.append(ExtractionIssue(kind="extraction_failed", detail=f"pypdf open failed: {exc}"))

    text_context = "\n".join(text_parts)
    if len(text_context) > max_text_chars:
        text_context = text_context[:max_text_chars]
        issues.append(
            ExtractionIssue(kind="extraction_truncated", detail=f"text truncated to {max_text_chars} chars")
        )

    form_fields: list[PdfFormField] = []
    try:
        with pikepdf.open(BytesIO(source_bytes)) as pdf:
            fields = collect_pdf_form_fields(pdf)
            locators = pdf_form_field_locators(fields, pdf)
            for fld in fields:
                loc = locators[id(fld)]
                tu = fld.get("/TU")
                current_tu = str(tu).strip() if tu is not None else None
                form_fields.append(PdfFormField(locator=loc, current_tu=current_tu or None))
    except Exception as exc:
        issues.append(ExtractionIssue(kind="extraction_failed", detail=f"form-field extraction failed: {exc}"))

    return PackagedPdf(
        extractor_version=EXTRACTOR_VERSION,
        page_count=page_count,
        text_context=text_context,
        form_fields=tuple(form_fields),
        extraction_issues=tuple(issues),
    )
