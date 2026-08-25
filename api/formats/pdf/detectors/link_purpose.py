"""2.4.4 Link Purpose (In Context) — PDF.

Two complementary checks (P-21):

(a) PDF_LINK_RAW_URL — the annotation's /URI appears verbatim in the page text. The raw URL is
    the visible label: a screen-reader user hears the full URL string.

(b) PDF_LINK_PURPOSE_VAGUE — text cropped from the annotation's bounding box matches the same
    _VAGUE_LINK_TEXT predicate used for docx/pptx/xlsx ("click here", "here", "read more",
    etc.). pdfplumber's `page.crop(bbox)` extracts the glyphs visually overlaid on the link
    rectangle, which is the display text a screen-reader announces.

WHY coverage is PARTIAL. Both checks are exact, so a hit is a definite failure. But a clean
scan cannot certify that all link text is meaningful — "Annual Report" linking to the wrong
document passes both. PARTIAL + REVIEW encodes "we checked a real subset; we cannot prove the
full criterion" (ADR 0016 / 0031).
"""
from __future__ import annotations

from pathlib import Path


def detect(path: Path) -> list[dict]:
    """2.4.4 findings for a PDF. Never raises — a detector must not fail a scan."""
    from office_structure import pdf_link_purpose_check
    return pdf_link_purpose_check(path)
