"""2.4.3 Focus Order — pptx.

Scope: slides whose title placeholder is not the first placeholder in document order.
A screen reader (and keyboard Tab) visits placeholders in their XML order; a title
placeholder that comes after content placeholders announces the slide heading last,
not first — the wrong focus sequence. The placeholder order is a structural read;
whether the resulting sequence is actually disorienting is a human call.
"""
from __future__ import annotations

from pathlib import Path


def detect(path: Path) -> list[dict]:
    """REVIEW findings for 2.4.3 on this presentation. Never raises."""
    from office_structure import pptx_focus_order_checks
    return pptx_focus_order_checks(path)
