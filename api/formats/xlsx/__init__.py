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
