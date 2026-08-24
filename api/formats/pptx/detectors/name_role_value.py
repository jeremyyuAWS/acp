"""4.1.2 Name, Role, Value — pptx.

Scope: presentations that embed interactive controls (ActiveX, OLE objects, VBA macro
projects) whose accessible name and role live in code the static read never sees. A
clean result means no such controls were found — the criterion does not arise for a
static deck.

Unlike docx 4.1.2, there is no pptx-native form field whose accessible name ACP can
read and write back deterministically. Every pptx interactive control here requires a
human to verify the name and role.
"""
from __future__ import annotations

from pathlib import Path


def detect(path: Path) -> list[dict]:
    """REVIEW findings for 4.1.2 on this presentation. Never raises."""
    from office_structure import office_control_review_checks
    return [f for f in office_control_review_checks(path, ".pptx")
            if str(f.get("wcag", "")).startswith("4.1.2")]
