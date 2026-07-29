"""
Rule: pdf.missing-bookmarks — WCAG 2.4.2 (Page Titled)

For PDFs longer than a threshold number of pages, checks that a bookmark
outline (/Outlines) is present to aid navigation.
"""

from __future__ import annotations

from uuid import uuid4

import pikepdf
import pdfplumber

from models.manifest import (
    A11yIssue,
    IssueCategory,
    IssueEvidence,
    IssueLocation,
    IssueSeverity,
    RemediationType,
    WcagCriterion,
)

RULE_ID = "pdf.missing-bookmarks"
_MIN_PAGES = 10


class BookmarksRule:
    rule_id = RULE_ID

    def check(self, pdf: pikepdf.Pdf, plumber_pdf: pdfplumber.PDF) -> list[A11yIssue]:
        page_count = len(pdf.pages)
        if page_count < _MIN_PAGES:
            return []

        has_bookmarks = False
        try:
            outlines = pdf.Root.get("/Outlines")
            if outlines is not None and isinstance(outlines, pikepdf.Dictionary):
                has_bookmarks = "/First" in outlines
        except Exception:
            pass

        if has_bookmarks:
            return []

        return [
            A11yIssue(
                issue_id=uuid4(),
                rule_id=RULE_ID,
                title="Long PDF is missing a bookmark outline",
                description=(
                    f"This PDF has {page_count} pages but no bookmark outline (/Outlines). "
                    "Bookmarks allow keyboard and screen reader users to navigate directly to "
                    "sections without scrolling through the entire document."
                ),
                severity=IssueSeverity.MINOR,
                category=IssueCategory.KEYBOARD_NAVIGATION,
                wcag_criterion=WcagCriterion.SC_2_4_2,
                location=IssueLocation(description="pdf:catalog:/Outlines"),
                evidence=IssueEvidence(
                    computed_value=f"{page_count} pages, no /Outlines entry",
                    expected_value=f"Bookmark outline for documents >{_MIN_PAGES} pages",
                ),
                remediation_type=RemediationType.HUMAN_REQUIRED,
                remediation_guidance=(
                    "Add bookmarks using the Bookmarks panel in Adobe Acrobat, or "
                    "re-export from the source document with heading-based bookmarks enabled."
                ),
            )
        ]
