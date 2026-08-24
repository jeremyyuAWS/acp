"""1.4.10 Reflow — DOCX.

Detects tables too wide to reflow to a 320px viewport without two-dimensional scrolling.
Column count and narrowest-column width are read from the table grid; whether the table
actually requires horizontal scrolling at that width is a rendered outcome not in the file.
Never raises.
"""
from __future__ import annotations

from pathlib import Path


def detect(path: Path) -> list[dict]:
    """REVIEW findings for 1.4.10 on this document."""
    from office_structure import office_reflow_checks
    return office_reflow_checks(path, ".docx")
