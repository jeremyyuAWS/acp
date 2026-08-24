"""1.4.11 Non-text Contrast — pptx.

Scope: shapes with a solid outline on a solid fill, measured by WCAG contrast ratio.
The worst shape below 3:1 is reported with the measured ratio. Gradients, image fills,
theme-colour indirection, and non-shape non-text elements (focus indicators, icon
glyphs, control borders) are outside this scope.

WHY THIS EXISTS AS A WRAPPER — see use_of_color.py next door (docx). Same pattern:
the implementation lives in office_structure; what was missing was the registry
declaration, so a clean deck read NOT_EVALUATED for a check that had already run.
"""
from __future__ import annotations

from pathlib import Path


def detect(path: Path) -> list[dict]:
    """REVIEW findings for 1.4.11 on this presentation. Never raises."""
    from office_structure import pptx_nontext_contrast_checks
    return pptx_nontext_contrast_checks(path)
