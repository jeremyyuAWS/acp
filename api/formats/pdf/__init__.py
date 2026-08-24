"""PDF format package — capability declarations and the (rule × format) registrations.

Everything this package knows about PDF accessibility is declared here, in one readable block.
Adding a criterion to PDF is a `register()` call plus a detector module; it is not an edit to
a shared dispatch table, a scope frozenset, and a catalog JSON that must be kept in agreement.
"""
from __future__ import annotations

from assessment import Confidence, Coverage
from capabilities import Capability
from rule_registry import register

from formats.pdf.detectors import focus_order, name_role_value, nontext_contrast, text_spacing, use_of_color

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

# ── 1.4.1 Use of Color ────────────────────────────────────────────────────────────────
# Hyperlinks whose only distinguishing cue from surrounding text is colour — no underline or
# other non-colour marker is present. PARTIAL: the detector reads annotation link objects and
# inline link text for underline presence; other ways colour can be the sole carrier of meaning
# in a PDF (colour-keyed legends, status indicators, chart series) are outside scope. HIGH
# confidence within that: the underline check is a direct structural read of each link object.
# No write-back exists for PDF link styling, so the remediation lane is human.
register(
    rule="1.4.1",
    fmt="pdf",
    detector=use_of_color.detect,
    requires={Capability.LINKS},
    coverage=Coverage.PARTIAL,
    confidence=Confidence.HIGH,
    reason=("annotation links and inline link text are checked for the presence of an underline "
            "or other non-colour distinguishing cue; colour used as the sole carrier of meaning "
            "elsewhere — colour-keyed legends, chart series, status indicators — is not examined"),
)

# ── 1.4.11 Non-text Contrast ──────────────────────────────────────────────────────────
# Non-text elements (shapes, borders) whose contrast ratio against their background falls below
# 3:1. PARTIAL: the detector samples solid-colour fills on a capped number of pages and measures
# the ratio using the WCAG formula; gradient fills, bitmap images, and most icon glyphs are
# outside scope. MEDIUM confidence: the measurement is exact within scope, but whether a low-
# contrast element conveys meaning or is decorative is a judgement not made by the detector.
register(
    rule="1.4.11",
    fmt="pdf",
    detector=nontext_contrast.detect,
    requires={Capability.COLOR},
    coverage=Coverage.PARTIAL,
    confidence=Confidence.MEDIUM,
    reason=("solid-colour non-text elements are measured with the WCAG contrast formula on sampled "
            "pages; gradient fills, bitmap images and most icon glyphs are not examined, and "
            "whether a low-contrast element conveys meaning is left to a human"),
)

# ── 1.4.12 Text Spacing ───────────────────────────────────────────────────────────────
# Pages whose line pitch is tight enough that the WCAG 1.4.12 line-height override (1.5× the
# font size) would clip text. The pitch is measured from page content streams; whether clipping
# actually occurs at the override setting is a rendered outcome not recorded in the file. PARTIAL
# because only sampled pages are examined; HIGH confidence within scope because the pitch is a
# direct measurement, not an estimate.
register(
    rule="1.4.12",
    fmt="pdf",
    detector=text_spacing.detect,
    requires={Capability.FONTS},
    coverage=Coverage.PARTIAL,
    confidence=Confidence.HIGH,
    reason=("line pitch is measured from page content streams and compared to the 1.5× font-size "
            "threshold; whether text actually clips when the override is applied is a rendered "
            "outcome not recorded in the file, and only sampled pages are examined"),
)
