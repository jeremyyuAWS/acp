"""1.4.1 Use of Color — PPTX.

Detects hyperlinks whose underline is explicitly suppressed (u="none"), leaving colour as the
only cue that distinguishes the link from surrounding text. Scope: every slide part; shapes,
tables and text frames all use the same DrawingML run structure. Never raises.
"""
from __future__ import annotations

from pathlib import Path


def detect(path: Path) -> list[dict]:
    """REVIEW findings for 1.4.1 on this presentation."""
    from office_structure import office_color_only_checks
    return office_color_only_checks(path, ".pptx")
