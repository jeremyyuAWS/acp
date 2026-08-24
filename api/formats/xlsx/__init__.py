"""XLSX format package — (rule × format) registrations.

REGISTERED IN PLACE. Unlike the PDF detectors, 1.4.11's implementation stays in
office_structure.py rather than moving under this package. It shares its regex primitives and
contrast maths with the docx and pptx non-text-contrast checks — one family, three formats — and
extracting only the xlsx member would either duplicate those helpers or leave the family split
across two trees. Moving it is worth doing when docx and pptx move with it; moving it alone
would be worse than leaving it.

The registration is the point regardless: coverage becomes declared, testable, and visible in
the matrix whether or not the code has been relocated. Physical layout and honest declaration
are separable concerns, and saying so here keeps this package from implying the migration is
further along than it is.
"""
from __future__ import annotations

from assessment import Confidence, Coverage
from capabilities import Capability
from rule_registry import register


def _nontext_contrast(path):
    """1.4.11 for xlsx — the worst solid outline-on-fill DrawingML shape below 3:1.

    Imported lazily so this package stays importable by tooling that only reads the registry;
    office_structure pulls in the whole OOXML surface.
    """
    from office_structure import xlsx_nontext_contrast_checks
    return xlsx_nontext_contrast_checks(path)


# ── 1.4.11 Non-text Contrast ──────────────────────────────────────────────────────────
# The last of the three pairs the matrix's drift check flagged as undeclared coverage: the
# detector shipped in PR #4, but xlsx appears in neither RULE_FORMATS nor REVIEW_FORMATS for
# 1.4.11 (docx, pptx and pdf all do), so a clean workbook read "not evaluated" for a check that
# had genuinely run.
#
# PARTIAL, not HEURISTIC: where it applies, the maths is exact — the true WCAG contrast ratio
# between an outline and its fill, not a proxy. But it applies only to solid `srgbClr`
# outline-on-fill shapes, so theme-coloured shapes, gradients, images, icons and control
# affordances all fall outside. Sound over a strict subset is the definition of PARTIAL.
#
# MEDIUM confidence, and the distinction is worth stating: the MEASUREMENT is certain, the
# CONCLUSION is not. WCAG requires 3:1 only for non-text content that conveys meaning, and
# nothing in the file distinguishes a meaningful shape from a decorative one — which is why the
# finding is advisory and asks a human to confirm the shape isn't decorative. Compare PDF 4.1.2,
# which is also PARTIAL but HIGH: an unnamed form field is a defect with no such caveat.
register(
    rule="1.4.11",
    fmt="xlsx",
    detector=_nontext_contrast,
    requires={Capability.COLOR},
    coverage=Coverage.PARTIAL,
    confidence=Confidence.MEDIUM,
    reason=("solid outline-on-fill DrawingML shapes are measured with the true WCAG contrast "
            "ratio; theme-coloured shapes, gradients, images and control affordances are not "
            "examined, and whether a shape conveys meaning is left to a human"),
)


def _color_only(path):
    """1.4.1 for xlsx — colour-only status conveyed by a conditional-format colour scale.

    Filtered to 1.4.1: office_color_only_checks is single-criterion for xlsx, but the filter keeps
    the registration honest if that ever changes. Lazy import, as above.
    """
    from office_structure import office_color_only_checks
    return [f for f in office_color_only_checks(path, ".xlsx")
            if str(f.get("wcag", "")).startswith("1.4.1")]


def _control_name_role(path):
    """4.1.2 for xlsx — an embedded control (ActiveX/OLE) whose name and role cannot be proven
    statically. office_control_review_checks emits BOTH 2.1.2 and 4.1.2, so this MUST filter to
    4.1.2 — evaluate() attributes every returned finding to the registered rule (see result_for).
    2.1.2 keeps its own review lane (REVIEW_FORMATS).
    """
    from office_structure import office_control_review_checks
    return [f for f in office_control_review_checks(path, ".xlsx")
            if str(f.get("wcag", "")).startswith("4.1.2")]


# ── 1.4.1 Use of Color ────────────────────────────────────────────────────────────────
# The colour-scale conditional format shades cells by value — a status conveyed by colour alone,
# with no icon or text carrying the same meaning. PARTIAL: the detector reaches colour-scale CF
# rules, not every way a workbook can lean on colour (cell fills read by eye, chart series). MEDIUM
# for the 1.4.11 reason — the signal is certain, but whether colour is the SOLE cue is a judgement
# left to a human, which is why the finding is advisory (REVIEW) and the lane cannot certify a pass.
register(
    rule="1.4.1",
    fmt="xlsx",
    detector=_color_only,
    requires={Capability.COLOR},
    coverage=Coverage.PARTIAL,
    confidence=Confidence.MEDIUM,
    reason=("colour-scale conditional formats that convey status by colour alone are flagged; "
            "colour used in cell fills, charts and images is not examined, and whether colour is "
            "the sole cue is left to a human"),
)


# ── 4.1.2 Name, Role, Value ───────────────────────────────────────────────────────────
# An embedded ActiveX/OLE control exposes its name and role through code no static read can see,
# so the finding is advisory and asks a human to confirm the control is named and its role exposed.
# PARTIAL (the technique reaches embedded-control parts, not every interactive affordance) and
# MEDIUM — compare PDF 4.1.2, which is PARTIAL but HIGH because a missing AcroForm /TU is a defect
# with no such caveat. No write-back can name an opaque control, so the remediation lane is 👤 human.
#
# requires is EMPTY, and deliberately NOT {FORMS}: BASELINE lists FORMS for docx/pdf and NOT for
# xlsx precisely because "a spreadsheet's form controls are a different object nothing here reads"
# (capabilities.py). This detector confirms that — it reads the raw activeX/oleObject parts to find
# a control PRESENT and then reports that its name/role CANNOT be read, which is the opposite of
# delivering FORMS ("interactive fields WITH names/types/values"). It self-gates: no control parts
# → [] → the pair simply reports clean. So it needs no declared capability to be reachable.
register(
    rule="4.1.2",
    fmt="xlsx",
    detector=_control_name_role,
    requires=frozenset(),
    coverage=Coverage.PARTIAL,
    confidence=Confidence.MEDIUM,
    reason=("embedded ActiveX/OLE controls are flagged for a human to confirm an accessible name "
            "and role; the name and role live in code that no static read can examine"),
)


def _no_keyboard_trap(path):
    """2.1.2 for xlsx — an embedded control (ActiveX/OLE) that may trap keyboard focus.

    office_control_review_checks emits BOTH 2.1.2 and 4.1.2; this filters to 2.1.2 so
    evaluate() attributes the finding to the registered rule. 4.1.2 keeps its own lane above.
    Same requires=frozenset() rationale: the detector self-gates on embedded-control parts.
    """
    from office_structure import office_control_review_checks
    return [f for f in office_control_review_checks(path, ".xlsx")
            if str(f.get("wcag", "")).startswith("2.1.2")]


def _language_parts(path):
    """3.1.2 for xlsx — foreign passages the workbook never identifies with a language mark.

    Delegates to the dedicated detector module so the docstring, rationale and test coverage
    all live in one place. Lazy import keeps this package importable by tooling that only
    reads the registry.
    """
    from formats.xlsx.detectors.language_parts import detect
    return detect(path)


# ── 3.1.2 Language of Parts ───────────────────────────────────────────────────────────
# PARTIAL: a passage must reach textchecks._MIN_SEG_WORDS (12) words in a language other than
# the document's own before langdetect is trusted, so a shorter foreign phrase or a single
# borrowed word is under the floor and unflagged. MEDIUM confidence: "which language a passage
# IS" is a statistical detection, not a certainty — and unlike docx/pptx this detector cannot
# supply a `marked` dict to cross-check (SpreadsheetML's rich-text run properties have no
# per-run language element at all). A clean result means "no unmarked foreign passage long
# enough for us to be sure", a real check over a strict subset.
#
# PERMANENTLY HUMAN for remediation: the format has no element to write a language mark into
# (see apply_text_values.py and remediation_capability.py). This does not affect detection.
# MECHANISM MIGRATION from RULE_FORMATS + _certify: verdict unchanged (a finding → FAIL,
# clean scan → REVIEW instead of the overclaiming PASS the legacy path returned).
register(
    rule="3.1.2",
    fmt="xlsx",
    detector=_language_parts,
    requires={Capability.TEXT},
    coverage=Coverage.PARTIAL,
    confidence=Confidence.MEDIUM,
    reason=("passages of at least 12 words in a language other than the workbook's own are "
            "flagged when no language mark is present; SpreadsheetML has no per-run language "
            "element, so shorter phrases and statistical uncertainty in langdetect's detection "
            "are both unflagged, and no write-back can ever clear this finding"),
)


# ── 2.1.2 No Keyboard Trap ────────────────────────────────────────────────────────────
# An embedded ActiveX/OLE control in a workbook may trap keyboard focus — whether focus can
# move away depends on the control's own implementation and on Excel's handling, which no static
# read settles. The detector names each control for a reviewer to test. PARTIAL: it reaches the
# raw activeX/oleObject package parts, not every interactive affordance. MEDIUM confidence for
# the same reason as 4.1.2: the control IS present and IS named exactly, but whether it traps
# is advisory (a judgement about runtime behaviour). requires is empty — same rationale as 4.1.2.
register(
    rule="2.1.2",
    fmt="xlsx",
    detector=_no_keyboard_trap,
    requires=frozenset(),
    coverage=Coverage.PARTIAL,
    confidence=Confidence.MEDIUM,
    reason=("embedded ActiveX/OLE controls are named for a reviewer to test with a keyboard; "
            "whether focus can actually move away from a control is runtime behaviour that "
            "depends on the control's own implementation and is not recorded in the file"),
)
