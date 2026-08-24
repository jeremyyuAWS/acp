"""1.4.11 Non-text Contrast — PDF.

Detects non-text elements (shapes, borders, icons) whose contrast ratio against their
background falls below the WCAG 3:1 threshold. Scope: solid-colour fills on sampled pages;
gradient fills and bitmap images are outside scope. Never raises.
"""
from __future__ import annotations

from pathlib import Path


def detect(path: Path) -> list[dict]:
    """REVIEW findings for 1.4.11 on this PDF."""
    from office_structure import pdf_nontext_contrast_checks
    return pdf_nontext_contrast_checks(path)
