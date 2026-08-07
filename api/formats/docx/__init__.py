"""DOCX format package — capability declarations and the (rule × format) registrations.

Everything this package knows about Word accessibility is declared here, in one readable block.
Adding a criterion to docx is a `register()` call plus a detector module; it is not an edit to a
shared dispatch table, a scope frozenset, and a catalog JSON that must be kept in agreement.
"""
from __future__ import annotations

from assessment import Confidence, Coverage
from capabilities import Capability
from rule_registry import register

from formats.docx.detectors import name_role_value

# ── 4.1.2 Name, Role, Value ───────────────────────────────────────────────────────────
# PARTIAL, not FULL: sound over interactive content controls, silent on ActiveX, embedded OLE
# objects and anything else a Word form can hold. PARTIAL, not HEURISTIC: within that subset the
# technique is exact — w:alias is present and non-empty, or it is not, read straight from the
# control's properties. There is no guessing and no false-positive class.
#
# HIGH confidence follows from that exactness; it is not a claim about breadth. Same reasoning
# as the PDF registration next door, and deliberately the same shape: narrow but certain.
#
# WHAT THIS FIXES. docx 4.1.2 entered RULE_FORMATS in #144 when the w:alias check and its
# write-back applier landed, so a FAILING document reported FAIL correctly. But a CLEAN one fell
# through to NOT_EVALUATED — "we did not look" — for work that had in fact been done, because
# RULE_FORMATS cannot express that a detector reaches part of a criterion. That is the exact gap
# the registry was built for, and the exact wrong answer PDF 4.1.2 gave before it was migrated.
# With coverage declared, a clean file now reads REVIEW: we checked what our technique reaches,
# a human confirms the rest.
#
# It does NOT become a certified pass, and should not. Certifying 4.1.2 means asserting every
# interactive component exposes a name and a role, which no static read can claim for an
# arbitrary ActiveX or OLE control. When a detector for those lands, this coverage moves to FULL
# and clean scans start certifying — with no change to this file or to the outcome gate.
register(
    rule="4.1.2",
    fmt="docx",
    detector=name_role_value.detect,
    requires={Capability.FORMS},
    coverage=Coverage.PARTIAL,
    confidence=Confidence.HIGH,
    reason=("interactive content controls are checked exactly for a Title (w:alias), the "
            "attribute Word exposes to assistive technology as the accessible name; ActiveX "
            "controls, embedded OLE objects and other form content are not examined, which "
            "would need reading each control's own implementation"),
)
