"""1.4.12 Text Spacing — pptx.

Advisory: paragraphs that use exact (fixed) line spacing block the user's line-height
override, which can clip text. The exact-spacing attribute is a deterministic structural
read; whether text actually clips when the override is applied is a rendered outcome,
so findings are REVIEW.
"""
from __future__ import annotations

from pathlib import Path


def detect(path: Path) -> list[dict]:
    """REVIEW findings for 1.4.12 on this presentation. Never raises."""
    from office_structure import office_text_spacing_checks
    return office_text_spacing_checks(path, ".pptx")
