"""The single source of truth for *which WCAG criterion can be automated on which
file format* — and to what degree.

Three tables used to disagree about this:
  1. AssessRunner.jsx  SC_AUTO             — format-BLIND (derived from the HTML rule
                                             modules), so a docx that IS auto-fixable
                                             read as "0 auto-fixable, 34 need review".
  2. FileDrawer.jsx    REM_AUTOFIX_SC_BY_TYPE — format-aware but hand-maintained and
                                             wrong for docx (claimed 3.1.1, which is
                                             engine-blocked on docx; omitted 1.4.3,
                                             which the docx contrast remediator does fix).
  3. The remediators themselves (remediate.py / remediate_office.py / remediate_pdf.py)
                                           — what actually runs.

This module is (3) distilled into a declarative table, so (1) and (2) can consume ONE
answer instead of drifting from reality. `tests/test_remediation_capability.py` is a
contract test that fails if any "auto" entry here has no corresponding deterministic
remediator action, which pins the table to what the code genuinely does.

Modes (per criterion × format):
  "auto"     — a DETERMINISTIC remediator clears it with no human in the loop. Grounded
               in a `_rec(diffs, "SC", …)` record (office/pdf) or an `@_register(sc,
               "auto")` fixer (html). Conservatively scoped: over-claiming "auto" in a
               compliance tool is worse than under-claiming, so anything uncertain is
               NOT "auto".
  "assisted" — an AI proposes a value and a human approves it (image alt text 1.1.1,
               link purpose 2.4.4, PDF reading order 1.3.2). Never applied unreviewed.
  "human"    — no automation; a person must do it. This is the DEFAULT: any (criterion,
               format) absent from the table below is "human".

Grounding notes for the non-obvious calls (each verified against the remediators):
  * docx 3.1.1 is "human", NOT "auto": the partner engine's docx language rules are
    DOCX-LANG-001 (reads the document body's run/paragraph w:lang) AND DOCX-LANGPART-001
    (language of parts). remediate_office only writes the OPC core property (dc:language
    in docProps/core.xml), which does not satisfy either — so the fix does not clear the
    engine. pptx/xlsx have a single core-property language rule that the same write does
    satisfy, so they stay "auto".
  * Contrast (1.4.3) is "auto" on docx/xlsx/html (each has an engine-verified recolour
    remediator) but "human" on pptx and pdf: pdf has no contrast remediator at all, and
    the pptx recolour, while present, is not engine-round-trip verified — so it is treated
    as detect-only rather than claimed as auto.
  * Image alt text (1.1.1) is "assisted" everywhere: even a faithful-source alt is a
    guess about author intent, so it goes through review, not silent auto-apply.
"""
from __future__ import annotations

FORMATS: tuple[str, ...] = ("html", "docx", "pptx", "xlsx", "pdf")

# fmt -> {sc: mode}. Only "auto" and "assisted" are listed; any absent (fmt, sc) is "human".
CAPABILITY: dict[str, dict[str, str]] = {
    # HTML runs the full deterministic fixer registry (remediate.py FIXERS, mode "auto").
    "html": {
        "3.1.1": "auto",    # _fix_lang — <html lang>
        "2.4.2": "auto",    # _fix_title — <title> from <h1>
        "1.3.1": "auto",    # _fix_form_labels — aria-label on unlabeled controls
        "1.4.3": "auto",    # _fix_contrast — darken low-contrast inline text
        "1.4.10": "auto",   # _fix_reflow — responsive viewport
        "1.4.4": "auto",    # _fix_resize — un-block pinch-zoom
        "1.4.12": "auto",   # _fix_text_spacing — relax fixed line-height
        "1.4.2": "auto",    # _fix_autoplay — stop autoplaying media
        "1.3.4": "auto",    # _fix_orientation — un-lock orientation
        "1.3.5": "auto",    # _fix_input_purpose — autocomplete tokens
        "1.4.1": "auto",    # _fix_use_of_color — underline colour-only links
        "2.4.1": "auto",    # _fix_bypass_blocks — skip link + main landmark
        "2.4.3": "auto",    # _fix_focus_order — reset positive tabindex
        "2.4.6": "auto",    # _fix_heading_skip — close skipped heading levels
        "2.4.7": "auto",    # _fix_focus_visible — un-suppress focus outline
        "2.5.3": "auto",    # _fix_label_in_name — accessible name contains visible text
        "3.1.4": "auto",    # _fix_abbr — expand abbreviations
        "1.1.1": "assisted",  # image alt — AI proposes, human approves
        "2.4.4": "assisted",  # _propose_links — link text draft/derivation, human approves
    },
    # remediate_office: core-property language/title for all Office; docx-specific structure.
    "docx": {
        "2.4.2": "auto",    # remediate_office _ensure(title) — dc:title
        "1.3.1": "auto",    # _remediate_docx_structure — table headers + heading outline
        "2.4.6": "auto",    # _remediate_docx_structure — close skipped heading levels
        "1.4.3": "auto",    # _remediate_docx_structure — recolour low-contrast runs (engine-verified)
        "1.1.1": "assisted",  # _fix_image_alt — faithful/vision alt, human approves
        # 3.1.1 is deliberately absent -> "human": engine-blocked (see module docstring).
    },
    "pptx": {
        "3.1.1": "auto",    # remediate_office _ensure(language) — dc:language (single pptx lang rule)
        "2.4.2": "auto",    # _remediate_pptx_slides — programmatic slide title
        "1.3.2": "auto",    # _remediate_pptx_slides — reading order (visual top-to-bottom)
        "1.1.1": "assisted",  # _fix_image_alt — faithful/vision alt, human approves
        # 1.4.3 absent -> "human": recolour exists but is not engine-round-trip verified.
    },
    "xlsx": {
        "3.1.1": "auto",    # remediate_office _ensure(language) — dc:language (single xlsx lang rule)
        "2.4.2": "auto",    # remediate_office _ensure(title) — dc:title
        "1.4.3": "auto",    # _remediate_xlsx_contrast — recolour low-contrast cell styles
        "1.3.1": "auto",    # _remediate_xlsx_structure — table header rows
        "1.3.2": "auto",    # _remediate_xlsx_structure — unhide rows/cols holding data
        "1.1.1": "assisted",  # _fix_image_alt — faithful/vision alt, human approves
    },
    "pdf": {
        "3.1.1": "auto",    # remediate_pdf PdfLanguageFixer — catalog /Lang
        "2.4.2": "auto",    # remediate_pdf PdfDisplayTitleFixer + filename-derived /Title
        "1.1.1": "assisted",  # _fix_pdf_figure_alt — vision alt on tagged figures, human approves
        "1.3.2": "assisted",  # _propose_reading_order — vision reading-order proposal (untagged)
        # 1.4.3 absent -> "human": no PDF contrast remediator exists.
    },
}


def mode_for(fmt: str | None, sc: str | None) -> str:
    """The automation mode for one (format, criterion). Unknown/absent -> "human"."""
    return CAPABILITY.get(fmt or "", {}).get(sc or "", "human")


def auto_scs(fmt: str | None) -> set[str]:
    """The set of SCs that are deterministically auto-fixable for this format."""
    return {sc for sc, mode in CAPABILITY.get(fmt or "", {}).items() if mode == "auto"}


def as_dict() -> dict[str, dict[str, str]]:
    """A JSON-serialisable copy for the /capability route (defensive deep copy so a
    caller can't mutate the module-level table)."""
    return {fmt: dict(scs) for fmt, scs in CAPABILITY.items()}
