"""1.4.10 Reflow — pptx.

Advisory: a table too wide to reflow at 320px without two-dimensional scrolling.
Column count is a structural fact; whether the table needs horizontal scrolling at
that width is a rendered outcome, so findings are REVIEW.
"""
from __future__ import annotations

from pathlib import Path


def detect(path: Path) -> list[dict]:
    """REVIEW findings for 1.4.10 on this presentation. Never raises."""
    from office_structure import office_reflow_checks
    return office_reflow_checks(path, ".pptx")
