"""pptx format package — capability declarations and the (rule × format) registrations.

Everything this package knows about PowerPoint accessibility is declared here, in one readable
block. Adding a criterion to pptx is a `register()` call plus a detector module; it is not an
edit to a shared dispatch table, a scope frozenset, and a catalog JSON that must be kept in
agreement.
"""
from __future__ import annotations

from assessment import Confidence, Coverage
from capabilities import Capability
from rule_registry import register


def _nontext_contrast(path):
    """1.4.11 for pptx — the worst solid srgbClr outline-on-fill shape below 3:1.

    Imported lazily so this package stays importable by tooling that only reads the registry;
    office_structure pulls in the whole OOXML surface.
    """
    from office_structure import pptx_nontext_contrast_checks
    return pptx_nontext_contrast_checks(path)


def _control_name_role(path):
    """4.1.2 for pptx — an embedded control (ActiveX/OLE) whose name and role cannot be proven
    statically. office_control_review_checks emits BOTH 2.1.2 and 4.1.2, so this MUST filter to
    4.1.2 — evaluate() attributes every returned finding to the registered rule (see result_for).
    2.1.2 keeps its own review lane (REVIEW_FORMATS).
    """
    from office_structure import office_control_review_checks
    return [f for f in office_control_review_checks(path, ".pptx")
            if str(f.get("wcag", "")).startswith("4.1.2")]


# ── 1.4.11 Non-text Contrast ──────────────────────────────────────────────────────────
# pptx_nontext_contrast_checks shipped as part of the same office-contrast family as
# docx_nontext_contrast_checks and xlsx_nontext_contrast_checks (all share the OOXML
# solid srgbClr measurement). What was missing was the pptx registry declaration — so a
# presentation with no faint-bordered shape resolved to NOT_EVALUATED, "we did not look",
# for work that had in fact been done. The registration closes that gap.
#
# PARTIAL: the technique reaches DrawingML shapes with an explicit solid srgbClr outline
# on an explicit solid srgbClr fill, measured in the slide XML. Theme-coloured shapes,
# gradient or image fills, and every non-shape non-text element WCAG covers (focus
# indicators, control affordances) are outside.
#
# MEDIUM confidence: the contrast MEASUREMENT is exact (the true WCAG formula, same as
# 1.4.3), but the CONCLUSION is not — WCAG requires 3:1 only for non-text content that
# conveys meaning, and nothing in the file records whether a shape is informational or
# decorative. That human judgement is why the finding is advisory and the pair cannot
# certify a pass. Compare pptx 4.1.2 below, which is also PARTIAL but MEDIUM for a
# different reason (runtime behaviour, not measurement uncertainty).
register(
    rule="1.4.11",
    fmt="pptx",
    detector=_nontext_contrast,
    requires={Capability.COLOR},
    coverage=Coverage.PARTIAL,
    confidence=Confidence.MEDIUM,
    reason=("DrawingML shapes with a solid srgbClr outline on a solid srgbClr fill are "
            "measured with the true WCAG contrast ratio; theme-coloured shapes, gradient "
            "or image fills, and non-shape non-text elements such as focus indicators are "
            "not examined, and whether a shape conveys meaning is left to a human"),
)


# ── 4.1.2 Name, Role, Value ───────────────────────────────────────────────────────────
# An embedded ActiveX/OLE control in a presentation exposes its name and role through code
# no static read can see, so the finding is advisory and asks a human to confirm the
# control is named and its role is exposed. office_control_review_checks emits both 2.1.2
# and 4.1.2 findings; this wrapper filters to 4.1.2 so evaluate() attributes the finding
# to the registered rule (the same discipline as xlsx 4.1.2 next door).
#
# PARTIAL: the technique reaches embedded-control parts (activeX/oleObject) that appear as
# foreign objects inside slide XML — it does not reach every interactive affordance a
# presentation can hold, and it reports "we cannot confirm name/role" rather than a proven
# defect. MEDIUM confidence: the control is structurally present (HIGH certainty), but its
# accessibility properties live in code (LOW certainty) — MEDIUM reflects that combination.
#
# requires is EMPTY, and deliberately NOT {FORMS}: FORMS is not in pptx's BASELINE because
# PowerPoint's interactive controls are a fundamentally different mechanism from docx content
# controls or PDF AcroForm widgets — the capability was never declared because no detector
# HERE reads pptx form fields as named/typed fields. This detector confirms exactly that: it
# finds a control present and reports that its name/role cannot be read statically. It is
# self-gating (no control parts → [] → pair reports clean), so no declared capability is
# needed for it to be reachable.
register(
    rule="4.1.2",
    fmt="pptx",
    detector=_control_name_role,
    requires=frozenset(),
    coverage=Coverage.PARTIAL,
    confidence=Confidence.MEDIUM,
    reason=("embedded ActiveX/OLE controls are flagged for a human to confirm an accessible "
            "name and role; the name and role live in code that no static read can examine"),
)
