"""1.4.11 Non-text Contrast for .docx — a shape outline too faint against its own fill.

WHAT IT READS. Each `wps:spPr`: the solid outline colour (`a:ln`) against the solid fill it sits
on, as a WCAG contrast ratio. The worst shape below 3:1 is reported, with the measured ratio and
the required threshold carried on the finding — so a reviewer decides without re-measuring.

WHY ONE FINDING AND NOT ONE PER SHAPE. The judgement a human makes here is about the document's
visual design, not about an individual rectangle: if the faintest outline in the file is
deliberate decoration, so are the rest. Listing twelve shapes would be twelve copies of one
decision.

WHY THIS IS A WRAPPER RATHER THAN A MOVE — see use_of_color.py next door. The implementation has
shipped and its findings already reach users; what was missing was the registration, so a clean
document read NOT_EVALUATED for work that had been done.
"""
from __future__ import annotations

from pathlib import Path


def detect(path: Path) -> list[dict]:
    """REVIEW findings for 1.4.11 on this Word document. Never raises."""
    from office_structure import docx_nontext_contrast_checks
    return docx_nontext_contrast_checks(path)
