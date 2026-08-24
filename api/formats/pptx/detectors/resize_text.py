"""1.4.4 Resize Text — pptx.

Advisory: fixed-size text boxes (auto-fit off) that hold a lot of text may clip when
the user enlarges text to 200%. The no-autofit attribute is a deterministic structural
read; whether the text actually clips is a rendered outcome, so findings are REVIEW.
"""
from __future__ import annotations

from pathlib import Path


def detect(path: Path) -> list[dict]:
    """REVIEW findings for 1.4.4 on this presentation. Never raises."""
    from office_structure import pptx_resize_text_checks
    return pptx_resize_text_checks(path)
