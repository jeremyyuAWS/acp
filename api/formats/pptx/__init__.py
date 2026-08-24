"""PPTX format package — capability declarations and the (rule × format) registrations.

Parallel to formats/docx/__init__.py: everything this package knows about PowerPoint
accessibility is declared here. Adding a criterion to pptx is a `register()` call plus
a detector module.
"""
from __future__ import annotations

from assessment import Confidence, Coverage
from capabilities import Capability
from rule_registry import register

from formats.pptx.detectors import (
    focus_order, name_role_value, no_keyboard_trap, nontext_contrast,
    reflow, resize_text, text_spacing, use_of_color,
)


# ── 1.4.1 Use of Color ───────────────────────────────────────────────────────────────
# Hyperlinks whose underline is explicitly suppressed (u="none"), leaving colour as the only
# cue distinguishing the link from surrounding text. PARTIAL: the detector reaches DrawingML
# runs with a hlinkClick target and u="none" rPr exactly; other ways colour can carry meaning
# in a presentation (colour-keyed chart series, shaded table cells, icon-less status markers)
# are outside scope. HIGH confidence within that: the underline suppression is a direct
# structural read. A clean result means no such links were found, not that the deck has no
# colour-only information anywhere else.
register(
    rule="1.4.1",
    fmt="pptx",
    detector=use_of_color.detect,
    requires={Capability.LINKS, Capability.FONTS},
    coverage=Coverage.PARTIAL,
    confidence=Confidence.HIGH,
    reason=("hyperlinks are checked exactly for an explicitly removed underline (u=\"none\" on "
            "the run's rPr), which leaves colour as the only cue; colour used as the sole "
            "carrier of meaning elsewhere — chart series, shaded table cells, status markers "
            "without an icon — is not examined"),
)


# ── 1.4.4 Resize Text ────────────────────────────────────────────────────────────────
# Fixed-size text boxes (auto-fit off) that hold a lot of text may clip when a user
# enlarges text to 200%. The no-autofit property is an exact structural read; whether
# the text actually clips is a rendered outcome — PARTIAL, not FULL, and REVIEW not
# PASS, because the clipping judgement is not in the file.
register(
    rule="1.4.4",
    fmt="pptx",
    detector=resize_text.detect,
    requires={Capability.TEXT},
    coverage=Coverage.PARTIAL,
    confidence=Confidence.HIGH,
    reason=("fixed-size text boxes with auto-fit disabled are identified exactly from the "
            "shape's body properties; whether the contained text visually clips when the "
            "user enlarges to 200% is a rendered outcome not recorded in the file"),
)


# ── 1.4.10 Reflow ────────────────────────────────────────────────────────────────────
# Tables too wide to reflow at 320px without two-dimensional scrolling. Column count
# is an exact structural read; whether the table actually needs horizontal scrolling at
# that width is a rendered outcome — PARTIAL, REVIEW.
register(
    rule="1.4.10",
    fmt="pptx",
    detector=reflow.detect,
    requires={Capability.TABLES},
    coverage=Coverage.PARTIAL,
    confidence=Confidence.HIGH,
    reason=("tables are measured for column count and narrowest-column width exactly from "
            "the grid-column declarations in slide XML; whether the widest table actually "
            "requires horizontal scrolling at 320px is a rendered outcome not recorded in "
            "the file"),
)


# ── 1.4.11 Non-text Contrast ─────────────────────────────────────────────────────────
# Shapes with a solid outline on a solid fill, measured by WCAG contrast ratio.
# Gradients, image fills, theme-colour indirection, and non-shape non-text elements
# (focus indicators, icon glyphs, control borders) are outside this scope.
# HIGH confidence within that: the ratio is computed from the two resolved colours by
# the same WCAG formula used for text contrast.
register(
    rule="1.4.11",
    fmt="pptx",
    detector=nontext_contrast.detect,
    requires={Capability.COLOR},
    coverage=Coverage.PARTIAL,
    confidence=Confidence.HIGH,
    reason=("shapes with a solid outline on a solid fill are measured exactly, by the same "
            "WCAG contrast formula used for text; gradient or image fills, theme-colour "
            "indirection, and non-shape non-text elements such as focus indicators and "
            "control borders are not examined"),
)


# ── 1.4.12 Text Spacing ──────────────────────────────────────────────────────────────
# Paragraphs using exact (fixed) line spacing block the user's line-height override,
# which can clip text. The exact-spacing attribute is an exact structural read; whether
# text clips when the override is applied is a rendered outcome — PARTIAL, REVIEW.
register(
    rule="1.4.12",
    fmt="pptx",
    detector=text_spacing.detect,
    requires={Capability.FONTS},
    coverage=Coverage.PARTIAL,
    confidence=Confidence.HIGH,
    reason=("paragraphs using exact (fixed) line spacing are identified from the spacing "
            "element in slide XML; whether the fixed box clips the text when a user "
            "applies the WCAG 1.4.12 overrides is a rendered outcome not recorded in "
            "the file"),
)


# ── 2.1.2 No Keyboard Trap ───────────────────────────────────────────────────────────
# Presentations that embed ActiveX controls, OLE objects, or VBA macro projects.
# Whether keyboard focus can move away from a control is runtime behaviour that depends
# on the control's own implementation and the slide viewer — it is not in the file.
# A clean result means no embedded interactive controls were found, so the criterion
# does not arise for a static deck. This cannot become a certified pass for a file that
# does carry controls: only runtime testing can confirm freedom from trapping.
register(
    rule="2.1.2",
    fmt="pptx",
    detector=no_keyboard_trap.detect,
    requires=set(),
    coverage=Coverage.PARTIAL,
    confidence=Confidence.HIGH,
    reason=("the presentation is read for embedded interactive controls (ActiveX, OLE "
            "objects, VBA macro projects) and each one is named for a reviewer to test "
            "with a keyboard; whether focus can actually move away from a control is "
            "runtime behaviour that depends on the control's own implementation and the "
            "slide viewer, which is not recorded in the file"),
)


# ── 2.4.3 Focus Order ────────────────────────────────────────────────────────────────
# Slides whose title placeholder is not the first placeholder in document order.
# Screen readers and keyboard Tab visit placeholders in XML order; a title that appears
# after content placeholders announces the heading last rather than first. The
# placeholder order is an exact structural read; whether the resulting sequence
# disorients a user is a human call — PARTIAL, REVIEW.
register(
    rule="2.4.3",
    fmt="pptx",
    detector=focus_order.detect,
    requires={Capability.STRUCTURE},
    coverage=Coverage.PARTIAL,
    confidence=Confidence.HIGH,
    reason=("slides are checked for a title placeholder that follows content placeholders "
            "in document order, which inverts the focus sequence a screen reader follows; "
            "other focus-order conditions (non-placeholder shape sequences, embedded "
            "control tab order) are not examined"),
)


# ── 4.1.2 Name, Role, Value ──────────────────────────────────────────────────────────
# Presentations that embed ActiveX controls, OLE objects, or VBA macro projects whose
# accessible name and role live in code the static read never sees. Unlike docx 4.1.2,
# there is no pptx-native form field whose accessible name ACP can read and write back
# deterministically. A clean result means no such controls were found.
register(
    rule="4.1.2",
    fmt="pptx",
    detector=name_role_value.detect,
    requires=set(),
    coverage=Coverage.PARTIAL,
    confidence=Confidence.HIGH,
    reason=("the presentation is read for embedded interactive controls (ActiveX, OLE "
            "objects, VBA macro projects) whose accessible name and role live in the "
            "control's own implementation and cannot be confirmed by a static read; a "
            "clean result means no such controls were found and the criterion does not "
            "arise for this deck"),
)
