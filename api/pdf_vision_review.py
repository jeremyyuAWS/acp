"""ADR 0027 Tier B — WCAG REVIEW findings from scanned-PDF layout descriptions.

Scanned / untagged PDFs cannot be assessed for structure, alt text, or language
programmatically because the page content is a raster image with no tag tree.
This module maps the layout descriptions stored by Tier A into one advisory
REVIEW finding per criterion — the minimum signal needed to route the file to
human review, consistent with ADR 0016 (no fabricated passes) and ADR 0023
(review-lane semantics).
"""
from __future__ import annotations

# (rule_id, wcag, per-criterion rationale suffix)
_SCANNED_RULES: list[tuple[str, str, str]] = [
    (
        "PDF_SCANNED_NO_ALT",
        "1.1.1 Non-text Content",
        "every page is a raster image; no alt text or description is encoded "
        "in the file — visual content (figures, diagrams, photos) requires a "
        "written description for screen reader users",
    ),
    (
        "PDF_SCANNED_STRUCTURE",
        "1.3.1 Info and Relationships",
        "document structure (headings, lists, tables, form fields) must be "
        "programmatically determinable, but a scanned image carries no tag tree; "
        "verify that an accessible tagged version is available",
    ),
    (
        "PDF_SCANNED_READING_ORDER",
        "1.3.2 Meaningful Sequence",
        "reading order must be derivable from the document structure, but no "
        "structural tags are present; assistive technology cannot determine the "
        "intended sequence of content",
    ),
    (
        "PDF_SCANNED_HEADINGS",
        "2.4.6 Headings and Labels",
        "heading presence and descriptiveness cannot be verified programmatically "
        "without structural tags; review whether headings are correctly marked up "
        "in an accessible version of the document",
    ),
    (
        "PDF_SCANNED_LANGUAGE",
        "3.1.1 Language of Page",
        "the document language attribute is absent or unverifiable in a scanned "
        "PDF; assistive technology cannot determine the correct language for "
        "pronunciation without it",
    ),
]


def findings_from_layouts(pages: list[dict], *, filename: str = "") -> list[dict]:
    """Return one REVIEW finding per WCAG criterion for a scanned / untagged PDF.

    ``pages`` is the list of per-page dicts returned by
    ``pdf_vision_assess.extract_layout`` or by ``store.get_scanned_pdf_layouts``
    (keys: ``page``, ``description``, ``evidence``).

    Returns an empty list when ``pages`` is empty so callers can short-circuit.
    All returned findings carry ``severity="REVIEW"`` and ``advisory=True``; they
    are non-blocking (zero penalty weight) and signal that a human must verify the
    criterion — never that the document fails.
    """
    if not pages:
        return []

    page_count = len(pages)
    noun = "1 page" if page_count == 1 else f"{page_count} pages"
    preamble = (
        f"This document was identified as a scanned or untagged PDF "
        f"({noun} assessed by vision layout analysis). "
    )

    findings: list[dict] = []
    for rule_id, wcag, rationale in _SCANNED_RULES:
        findings.append(
            {
                "ruleId": rule_id,
                "wcag": wcag,
                "severity": "REVIEW",
                "advisory": True,
                "detail": preamble + rationale.capitalize() + ".",
            }
        )
    return findings
