"""2.1.2 No Keyboard Trap — pptx.

Scope: presentations that embed interactive controls (ActiveX, OLE objects, VBA macro
projects). Whether keyboard focus can move away from a control is runtime behaviour
that depends on the control's own implementation and the slide viewer; no static read
can settle it. A clean result means no interactive controls were found — the criterion
does not arise for a static deck.
"""
from __future__ import annotations

from pathlib import Path


def detect(path: Path) -> list[dict]:
    """REVIEW findings for 2.1.2 on this presentation. Never raises."""
    from office_structure import office_control_review_checks
    return [f for f in office_control_review_checks(path, ".pptx")
            if str(f.get("wcag", "")).startswith("2.1.2")]
