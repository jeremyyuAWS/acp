"""Bounded PDF page text and target facts using production writer locators.

Nearby text is candidate evidence, not an asserted field label. Figure context never
infers a relationship between an arbitrary page image and a structure-tree tag.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from io import BytesIO
import json
import math

import pikepdf
import pypdf
from experiments.document_wide_ai.application.production_adapters import (
    collect_pdf_form_fields, pdf_form_field_locators,
)
from experiments.document_wide_ai.contracts.v1 import ExtractionIssue, sha256_hex

EXTRACTOR_VERSION = "pdf-extractor.v2"


@dataclass(frozen=True)
class PdfFormField:
    locator: str
    current_tu: str | None
    page_index: int | None = None
    internal_name: str = ""
    field_type: str = ""
    rectangle: tuple[float, ...] = ()
    nearby_text: tuple[str, ...] = ()


@dataclass(frozen=True)
class PdfFigure:
    locator: str
    current_alt: str | None
    page_index: int | None = None


@dataclass(frozen=True)
class PackagedPdf:
    extractor_version: str
    page_count: int
    text_context: str
    form_fields: tuple[PdfFormField, ...]
    extraction_issues: tuple[ExtractionIssue, ...] = field(default_factory=tuple)
    figures: tuple[PdfFigure, ...] = ()
    page_text: str = ""

    def field_by_locator(self, locator: str) -> PdfFormField | None:
        return next((f for f in self.form_fields if f.locator == locator), None)


def fingerprint_value(current_value: str | None) -> str:
    return sha256_hex((current_value or "<missing>").encode("utf-8"))


def locator_page_index(locator: str) -> int | None:
    try:
        page = int(locator.split(":")[2])
        return page - 1 if page > 0 else None
    except (ValueError, IndexError):
        return None


def _rectangle(field):
    rect = field.get('/Rect')
    if rect is None:
        kids = field.get('/Kids', [])
        rect = kids[0].get('/Rect') if len(kids) == 1 else None
    try:
        values = tuple(float(v) for v in rect)
        return values if len(values) == 4 and all(math.isfinite(v) for v in values) else ()
    except (TypeError, ValueError):
        return ()


def package_pdf(source_bytes: bytes, *, max_text_chars: int) -> PackagedPdf:
    issues, text_parts, text_runs = [], [], {}
    page_count = 0
    try:
        reader = pypdf.PdfReader(BytesIO(source_bytes))
        page_count = len(reader.pages)
        for i, page in enumerate(reader.pages):
            try:
                runs = []
                def visitor(text, cm, tm, font, size):
                    value = text.strip()
                    if value:
                        x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
                        y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
                        if math.isfinite(x) and math.isfinite(y):
                            runs.append((float(x), float(y), value))
                text = page.extract_text(visitor_text=visitor) or ""
                text_parts.append(f"[Page {i + 1}]\n{text}")
                text_runs[i] = runs
            except Exception as exc:
                issues.append(ExtractionIssue('extraction_failed', f'page {i + 1} text extraction failed: {type(exc).__name__}'))
    except Exception as exc:
        issues.append(ExtractionIssue('extraction_failed', f'pypdf open failed: {type(exc).__name__}'))

    form_fields, figures, metadata = [], [], {}
    try:
        with pikepdf.open(BytesIO(source_bytes)) as pdf:
            from experiments.document_wide_ai.application.production_adapters import (
                collect_pdf_figures, pdf_figure_locators, pdf_figure_alt,
            )
            metadata = {'page_count': page_count, 'title': str(pdf.docinfo.get('/Title', '')),
                        'language': str(pdf.Root.get('/Lang', '')), 'encrypted': pdf.is_encrypted}
            fields = collect_pdf_form_fields(pdf)
            locators = pdf_form_field_locators(fields, pdf)
            for fld in fields:
                loc = locators[id(fld)]
                tu = fld.get('/TU')
                current_tu = str(tu).strip() if tu is not None else None
                page_index = locator_page_index(loc)
                rectangle, nearby = _rectangle(fld), ()
                if rectangle and page_index is not None:
                    x0, y0, x1, y1 = rectangle
                    candidates = [(abs(y-(y0+y1)/2) + abs(x-x0)/4, text)
                                  for x, y, text in text_runs.get(page_index, ())
                                  if y0-40 <= y <= y1+40 and x0-250 <= x <= x1+30]
                    nearby = tuple(text[:500] for _, text in sorted(candidates)[:4])
                form_fields.append(PdfFormField(loc, current_tu or None, page_index,
                    str(fld.get('/T', '')), str(fld.get('/FT', '')), rectangle, nearby))
            raw_figures = collect_pdf_figures(pdf.Root.get('/StructTreeRoot'))
            locators = pdf_figure_locators(raw_figures, pdf)
            figures = [PdfFigure(locators[id(fig)], pdf_figure_alt(fig),
                       locator_page_index(locators[id(fig)])) for fig in raw_figures]
    except Exception as exc:
        issues.append(ExtractionIssue('extraction_failed', f'target extraction failed: {type(exc).__name__}'))

    page_text = '\n'.join(text_parts)
    text_context = page_text + '\n[PDF target facts; nearby text is candidate evidence, not a confirmed label]\n' + json.dumps(
        {'document': metadata, 'form_fields': [asdict(f) for f in form_fields],
         'figures': [asdict(f) for f in figures]}, sort_keys=True)
    if len(text_context) > max_text_chars:
        text_context = text_context[:max_text_chars]
        issues.append(ExtractionIssue('extraction_truncated', f'text truncated to {max_text_chars} chars'))
    return PackagedPdf(EXTRACTOR_VERSION, page_count, text_context, tuple(form_fields), tuple(issues), tuple(figures), page_text)
