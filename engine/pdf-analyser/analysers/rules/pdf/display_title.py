"""
Rule: pdf.display-doc-title — WCAG 2.4.2 (Page Titled)

Checks that ViewerPreferences/DisplayDocTitle is set to true so the document
title (not the filename) is shown in PDF viewers.
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

RULE_ID = "pdf.display-doc-title"


class DisplayTitleRule:
    rule_id = RULE_ID

    def check(self, pdf: pikepdf.Pdf, plumber_pdf: pdfplumber.PDF) -> list[A11yIssue]:
        root = pdf.Root
        display_title = False

        if "/ViewerPreferences" in root:
            vp = root["/ViewerPreferences"]
            if isinstance(vp, pikepdf.Dictionary) and "/DisplayDocTitle" in vp:
                display_title = bool(vp["/DisplayDocTitle"])

        if display_title:
            return []

        return [
            A11yIssue(
                issue_id=uuid4(),
                rule_id=RULE_ID,
                title="PDF viewer is not set to display the document title",
                description=(
                    "The PDF ViewerPreferences dictionary does not set DisplayDocTitle to true. "
                    "Without this setting, PDF viewers display the filename rather than the "
                    "document title in the title bar, which reduces accessibility for users who "
                    "rely on the title to identify documents."
                ),
                severity=IssueSeverity.MODERATE,
                category=IssueCategory.DOCUMENT_TITLE,
                wcag_criterion=WcagCriterion.SC_2_4_2,
                location=IssueLocation(description="pdf:ViewerPreferences/DisplayDocTitle"),
                evidence=IssueEvidence(
                    computed_value=str(display_title),
                    expected_value="true",
                ),
                remediation_type=RemediationType.AUTO_FIX,
                remediation_guidance=(
                    "Set ViewerPreferences/DisplayDocTitle to true in the PDF. "
                    "In Adobe Acrobat: File > Properties > Initial View > Show > Document Title."
                ),
            )
        ]
