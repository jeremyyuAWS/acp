"""Explicit extraction limits (PRD §2: "If the full package exceeds configured limits,
return `document_too_large` without dispatch. Automatic chunking is deferred.")
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExtractionLimits:
    max_text_chars: int = 200_000
    max_pages: int = 200
    max_images: int = 20
    max_findings: int = 500


class DocumentTooLarge(Exception):
    """Raised in place of dispatch when a package exceeds configured limits."""

    def __init__(self, reason: str, measured: dict[str, int], limits: ExtractionLimits):
        self.reason = reason
        self.measured = measured
        self.limits = limits
        super().__init__(f"document_too_large: {reason} (measured={measured})")


def check_limits(
    *,
    text_chars: int,
    page_count: int,
    image_count: int,
    finding_count: int,
    limits: ExtractionLimits = ExtractionLimits(),
) -> None:
    measured = {
        "text_chars": text_chars,
        "page_count": page_count,
        "image_count": image_count,
        "finding_count": finding_count,
    }
    if text_chars > limits.max_text_chars:
        raise DocumentTooLarge("text_chars", measured, limits)
    if page_count > limits.max_pages:
        raise DocumentTooLarge("page_count", measured, limits)
    if image_count > limits.max_images:
        raise DocumentTooLarge("image_count", measured, limits)
    if finding_count > limits.max_findings:
        raise DocumentTooLarge("finding_count", measured, limits)
