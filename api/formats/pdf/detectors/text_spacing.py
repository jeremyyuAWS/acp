"""1.4.12 Text Spacing — PDF.

Detects pages whose line pitch is so tight that applying the WCAG 1.4.12 line-height override
(1.5× the font size) would cause text to clip. The pitch is read from page content streams;
whether clipping actually occurs is a rendered outcome not in the file. Never raises.
"""
from __future__ import annotations

from pathlib import Path


def detect(path: Path) -> list[dict]:
    """REVIEW findings for 1.4.12 on this PDF."""
    from office_structure import pdf_text_spacing_checks
    return pdf_text_spacing_checks(path)
