"""1.4.12 Text Spacing — DOCX.

Detects paragraphs using exact (fixed) line spacing, which blocks the user's line-height
override and can clip text. The spacing element is read directly from the paragraph properties;
whether text clips when the WCAG 1.4.12 overrides are applied is a rendered outcome not in
the file. Never raises.
"""
from __future__ import annotations

from pathlib import Path


def detect(path: Path) -> list[dict]:
    """REVIEW findings for 1.4.12 on this document."""
    from office_structure import office_text_spacing_checks
    return office_text_spacing_checks(path, ".docx")
