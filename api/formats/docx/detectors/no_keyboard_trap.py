"""2.1.2 No Keyboard Trap for .docx — the controls a reviewer has to try with a keyboard.

WHAT CAN AND CANNOT BE READ. Whether keyboard focus can move AWAY from a control is runtime
behaviour: it depends on the control's own implementation and on how Word handles it, neither of
which is in the file. No static read settles it, and no amount of better parsing would.

So this detector answers the question it CAN answer — does this document embed interactive
controls at all — and hands the reviewer the list. A document with none is not "passing"; it has
nothing to trap focus in, so the criterion never arises and the outcome stays NOT_EVALUATED. A
document with controls gets a REVIEW finding naming them.

That is the whole technique, and it is deliberately small. The alternative — trying to infer
trap-ness from control properties — would produce a confident answer to a question the file does
not contain, which is the failure mode ACP is built to avoid.

WHY THIS IS A WRAPPER. `office_structure.office_control_review_checks` has shipped since ADR 0023
and its findings already reach users; what was missing was the DECLARATION, so a document with no
controls read NOT_EVALUATED ("we did not look") for a check that had in fact run. Same gap docx
4.1.2 had before #144, and 1.4.1 / 1.4.11 before #202.

It also emits the 4.1.2 half, which docx already declares separately via name_role_value. Only
the 2.1.2 findings are returned here — declaring one criterion must not smuggle in another's.
"""
from __future__ import annotations

from pathlib import Path


def detect(path: Path) -> list[dict]:
    """REVIEW findings for 2.1.2 on this Word document. Never raises."""
    from office_structure import office_control_review_checks
    return [f for f in office_control_review_checks(path, ".docx")
            if str(f.get("wcag", "")).startswith("2.1.2")]
