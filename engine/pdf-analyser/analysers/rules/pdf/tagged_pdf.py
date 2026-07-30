"""
Rule: pdf.tagged — WCAG 1.3.1 (Info and Relationships)

Checks that the PDF is tagged (has a structure tree and MarkInfo).
Untagged PDFs are entirely inaccessible to screen readers.
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

RULE_ID = "pdf.tagged"


class TaggedPdfRule:
    rule_id = RULE_ID

    def check(self, pdf: pikepdf.Pdf, plumber_pdf: pdfplumber.PDF) -> list[A11yIssue]:
        root = pdf.Root

        has_mark_info = False
        if "/MarkInfo" in root:
            mark_info = root["/MarkInfo"]
            if isinstance(mark_info, pikepdf.Dictionary):
                marked = mark_info.get("/Marked")
                has_mark_info = marked is not None and bool(marked)

        has_struct_tree = "/StructTreeRoot" in root

        if has_mark_info and has_struct_tree:
            return []

        return [
            A11yIssue(
                issue_id=uuid4(),
                rule_id=RULE_ID,
                title="PDF is not tagged for accessibility",
                description=(
                    "This PDF does not have a tagged structure tree (PDF/UA tagging). "
                    "Tagged PDFs are required for screen readers and other assistive technologies "
                    "to interpret the document content and reading order correctly."
                ),
                severity=IssueSeverity.CRITICAL,
                category=IssueCategory.READING_ORDER,
                wcag_criterion=WcagCriterion.SC_1_3_1,
                location=IssueLocation(description="pdf:document-structure"),
                evidence=IssueEvidence(
                    computed_value=(
                        f"MarkInfo.Marked={has_mark_info}, StructTreeRoot={has_struct_tree}"
                    ),
                    expected_value="MarkInfo.Marked=true with a valid StructTreeRoot",
                ),
                remediation_type=RemediationType.HUMAN_REQUIRED,
                remediation_guidance=(
                    "Open the PDF in Adobe Acrobat Pro and use the Accessibility Checker "
                    "to add tags. Alternatively, re-export from the source document with "
                    "accessibility options enabled."
                ),
            )
        ]
