"""1.4.1 Use of Color — PDF.

Detects hyperlinks that rely on colour alone to distinguish them from surrounding text —
no underline or other non-colour cue is present. Scope: all pages; inline and annotation
links. Never raises.
"""
from __future__ import annotations

from pathlib import Path


def detect(path: Path) -> list[dict]:
    """REVIEW findings for 1.4.1 on this PDF."""
    from office_structure import pdf_use_of_color_checks
    return pdf_use_of_color_checks(path)
