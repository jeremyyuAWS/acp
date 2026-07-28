"""PDF format package — capability declarations and the (rule × format) registrations.

Everything this package knows about PDF accessibility is declared here, in one readable block.
Adding a criterion to PDF is a `register()` call plus a detector module; it is not an edit to
a shared dispatch table, a scope frozenset, and a catalog JSON that must be kept in agreement.
"""
from __future__ import annotations

from assessment import Confidence, Coverage
from capabilities import Capability
from rule_registry import register

from formats.pdf.detectors import focus_order, name_role_value

# ── 4.1.2 Name, Role, Value ───────────────────────────────────────────────────────────
# PARTIAL, not FULL: sound over AcroForm fields, silent on tagged-structure components.
# PARTIAL, not HEURISTIC: within that subset the technique is exact — /TU, /FT and /V are
# read straight from the field dictionary, so there is no guessing and no false-positive class.
# HIGH confidence follows from that exactness; it is not a claim about breadth.
register(
    rule="4.1.2",
    fmt="pdf",
    detector=name_role_value.detect,
    requires={Capability.FORMS},
    coverage=Coverage.PARTIAL,
    confidence=Confidence.HIGH,
    reason=("interactive AcroForm fields are checked exactly (/TU name, /FT role, /V value); "
            "components expressed through the tagged-structure tree are not examined, which "
            "needs a /StructTreeRoot walker this codebase does not have yet"),
)

# ── 2.4.3 Focus Order ─────────────────────────────────────────────────────────────────
# HEURISTIC: /Tabs = /S is a proxy for correct tab sequence, not a proof of it — neither
# necessary (/R and /C are legitimate) nor sufficient (a page can declare /S and still tab
# nonsensically). MEDIUM confidence reflects a signal that correlates but can be wrong in both
# directions; contrast 4.1.2 above, which is narrow but exact.
register(
    rule="2.4.3",
    fmt="pdf",
    detector=focus_order.detect,
    requires={Capability.FORMS},
    coverage=Coverage.HEURISTIC,
    confidence=Confidence.MEDIUM,
    reason=("pages with form widgets are checked for /Tabs = /S, a proxy for tab order "
            "following reading order; actually comparing the widget order to the structure "
            "order needs a /StructTreeRoot walk that is not built"),
)
