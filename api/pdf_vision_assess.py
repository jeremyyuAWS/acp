"""Scanned / untagged PDF assessment --- ADR 0027 Tier A."""
from __future__ import annotations
import os
from pathlib import Path
from swallowed import swallowed

_TEXT_FLOOR_PER_PAGE = 30
MAX_PAGES = 8
_LAYOUT_CONTEXT = (
    "This is one page of a scanned document. Describe its full content: identify any headings, "
    "body text paragraphs, tables, and figures or images. Note the reading order and the "
    "apparent language of the text."
)

def enabled() -> bool:
    return os.environ.get("ACP_SCANNED_PDF_TIER_A", "").strip().lower() in ("1", "true", "yes", "on")

def is_scanned_pdf(path: Path) -> bool:
    try:
        import pikepdf
        with pikepdf.open(str(path)) as pdf:
            root = pdf.Root
            has_tag_tree = "/MarkInfo" in root or "/StructTreeRoot" in root
            if not has_tag_tree:
                return True
            try:
                import pdfplumber
                with pdfplumber.open(str(path)) as plumb:
                    sampled = plumb.pages[:min(5, len(plumb.pages))]
                    total_chars = sum(len((p.extract_text() or "").strip()) for p in sampled)
                    if total_chars < _TEXT_FLOOR_PER_PAGE * len(sampled):
                        return True
            except Exception:
                pass
    except Exception:
        pass
    return False

def extract_layout(
    pdf_bytes: bytes,
    *,
    scan_id: str | None = None,
    file: str | None = None,
    max_pages: int = MAX_PAGES,
) -> list[dict]:
    if not pdf_bytes:
        return []
    try:
        import io as _io
        import pikepdf
        with pikepdf.open(_io.BytesIO(pdf_bytes)) as pdf:
            n_pages = len(pdf.pages)
    except Exception:
        return []
    try:
        import ai as _ai
        import render as _render
    except Exception:
        return []
    results: list[dict] = []
    for page_num in range(1, min(n_pages, max_pages) + 1):
        try:
            png = _render.render_page_png(pdf_bytes, ".pdf", page_num)
            if not png:
                continue
            description = _ai.describe_image(
                png,
                filename=file or "",
                context=_LAYOUT_CONTEXT,
                scan_id=scan_id,
                file=file,
            )
            if description:
                results.append(
                    {"page": page_num, "description": description, "evidence": "vision-layout-v1"}
                )
        except Exception:
            swallowed(f"pdf_vision_assess.extract_layout: page {page_num} failed")
    return results
