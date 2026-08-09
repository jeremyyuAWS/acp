"""1.4.1 Use of Color for .docx — a hyperlink distinguished from body text by colour alone.

WHAT IT READS. `<w:u w:val="none"/>` on a hyperlink's run: the underline has been explicitly
removed, so the only thing setting the link apart from the surrounding text is its colour. A
reader who cannot distinguish that colour cannot find the link.

WHY THIS IS A WRAPPER RATHER THAN A MOVE. The implementation has shipped in
`office_structure.office_color_only_checks` since ADR 0023 Phase 1b and is called from
`checks_for`, so its findings already reach users. What was missing was a REGISTRATION — the
pair was undeclared, so a clean document resolved to NOT_EVALUATED ("we did not look") for work
that had in fact been done. That is the same gap docx 4.1.2 had before #144, and the registry
exists to close it.

Pointing at the existing function rather than relocating it keeps this change to what it
actually is: a declaration. Moving working detector code at the same time would put a real
behaviour risk inside a metadata fix, and the two would be indistinguishable if something broke.
"""
from __future__ import annotations

from pathlib import Path


def detect(path: Path) -> list[dict]:
    """REVIEW findings for 1.4.1 on this Word document. Never raises."""
    from office_structure import office_color_only_checks
    return office_color_only_checks(path, ".docx")
