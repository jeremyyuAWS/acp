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


def _use_of_color(path):
    """1.4.1 for PDF — a hyperlink whose text is chromatic with no drawn underline."""
    from office_structure import pdf_use_of_color_checks
    return pdf_use_of_color_checks(path)


def _nontext_contrast(path):
    """1.4.11 for PDF — the worst solid stroke-on-fill rect below 3:1."""
    from office_structure import pdf_nontext_contrast_checks
    return pdf_nontext_contrast_checks(path)


def _link_purpose(path):
    """2.4.4 for PDF — a link annotation whose visible text is the raw URL."""
    from office_structure import pdf_link_purpose_check
    return pdf_link_purpose_check(path)


# ── 1.4.1 Use of Color ────────────────────────────────────────────────────────────────
# The same detector ships since the ADR 0025 Tier A pass: pdf_use_of_color_checks reads
# pdfplumber link annotations and character colours. What was missing was the registry
# declaration — so a PDF with no colour-only links resolved to NOT_EVALUATED, "we did
# not look", for a check that had in fact run. Same gap docx 1.4.1 had before its
# migration, and the same fix: the declaration makes a clean scan read REVIEW.
#
# PARTIAL: the technique reaches hyperlink annotations with chromatic text and no drawn
# underline. Every other way colour can carry meaning solo — a red callout box, a green
# tick glyph, a chart keyed only by hue — is not examined. Claiming FULL here would
# assert we had looked at all of them.
#
# MEDIUM confidence, for the same reason as xlsx 1.4.1: the signal is structurally
# certain (a chromatic link colour and no drawn underline ARE present or they are not),
# but whether colour is the SOLE distinguishing cue is a judgement left to a human —
# which is why the finding is advisory (REVIEW) and the pair cannot certify a pass.
# Contrast PDF 4.1.2 above, which is PARTIAL but HIGH: a missing /TU is a defect with
# no such caveat.
register(
    rule="1.4.1",
    fmt="pdf",
    detector=_use_of_color,
    requires={Capability.LINKS, Capability.FONTS},
    coverage=Coverage.PARTIAL,
    confidence=Confidence.MEDIUM,
    reason=("hyperlink annotations are checked for chromatic text colour with no drawn "
            "underline — colour alone set apart from body text; colour used as the sole "
            "carrier of meaning anywhere else — a red callout, a chart series keyed by hue "
            "— is not examined, and whether colour is the sole cue is left to a human"),
)


# ── 1.4.11 Non-text Contrast ──────────────────────────────────────────────────────────
# Same story as 1.4.1 above: shipped detector (pdf_nontext_contrast_checks, ADR 0025),
# findings already surfaced, pair undeclared, so a clean PDF read NOT_EVALUATED for work
# that had been done. The registration closes the gap: a clean scan now reads REVIEW.
#
# PARTIAL: only rects that declare BOTH a stroke colour AND a fill are measured — real
# measurement or nothing (ADR 0016). Gradient fills, images, opaque overlays, and every
# non-rect non-text element WCAG covers (focus indicators, control borders) are outside.
#
# MEDIUM confidence: the contrast ratio between the stroke and fill is the true WCAG
# formula — the MEASUREMENT is exact. But whether the rect conveys meaning (vs being
# a decorative rule line or page ornament) is a human judgement, which is why the finding
# is advisory and the pair cannot certify a pass. Same reasoning as xlsx 1.4.11.
register(
    rule="1.4.11",
    fmt="pdf",
    detector=_nontext_contrast,
    requires={Capability.COLOR},
    coverage=Coverage.PARTIAL,
    confidence=Confidence.MEDIUM,
    reason=("rects with both a stroke and a fill colour are measured with the true WCAG "
            "contrast ratio; gradient fills, image backgrounds, and non-rect non-text "
            "elements such as focus indicators are not examined, and whether a rect "
            "conveys meaning is left to a human"),
)


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


# ── 2.4.4 Link Purpose (In Context) ─────────────────────────────────────────────────
# Same gap as 1.4.1 and 1.4.11 above: pdf_link_purpose_check shipped (ADR 0025), findings
# surface, pair undeclared. With the declaration, a clean PDF reads REVIEW rather than
# NOT_EVALUATED.
#
# PARTIAL: the technique is narrow by design — it flags only links whose raw URI (e.g.
# "https://example.com/report.pdf") appears verbatim in the page text. Generic filler phrases
# ("click here", "read more") that are not raw URLs are NOT flagged. Claiming FULL would mean
# we checked all the ways a link can fail to describe its destination, which we have not.
#
# HIGH confidence within that narrow subset: the URL must literally appear as text — the same
# string used in the annotation's /URI action appears in pdfplumber's extracted page text.
# No estimation; a link with any descriptive text is never flagged (ADR 0016: real measurement
# or nothing). Contrast PDF 1.4.11, which is PARTIAL but MEDIUM because "conveys meaning"
# requires human confirmation; here the defect (raw URL as visible text) has no such caveat.
register(
    rule="2.4.4",
    fmt="pdf",
    detector=_link_purpose,
    requires={Capability.LINKS},
    coverage=Coverage.PARTIAL,
    confidence=Confidence.HIGH,
    reason=("link annotations are checked for a raw URI appearing verbatim as the link's "
            "visible text; whether otherwise-descriptive link text accurately names its "
            "destination is a content judgement not examined, and generic filler phrases "
            "('click here', 'read more') without a bare URL are not flagged"),
)
