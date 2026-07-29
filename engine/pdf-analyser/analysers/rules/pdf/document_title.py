"""
Rule: pdf.document-title — WCAG 2.4.2 (Page Titled)

Checks that the PDF has a non-empty document title in its metadata.
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

RULE_ID = "pdf.document-title"


class DocumentTitleRule:
    rule_id = RULE_ID

    def check(self, pdf: pikepdf.Pdf, plumber_pdf: pdfplumber.PDF) -> list[A11yIssue]:
        title: str | None = None
        try:
            raw = pdf.docinfo.get("/Title")
            if raw is not None:
                title = str(raw).strip()
        except Exception:
            pass

        if title:
            return []

        return [
            A11yIssue(
                issue_id=uuid4(),
                rule_id=RULE_ID,
                title="PDF is missing a document title",
                description=(
                    "The PDF document information does not contain a title. "
                    "A descriptive title helps users identify the document and is "
                    "announced by screen readers when the document is opened."
                ),
                severity=IssueSeverity.SERIOUS,
                category=IssueCategory.DOCUMENT_TITLE,
                wcag_criterion=WcagCriterion.SC_2_4_2,
                location=IssueLocation(description="pdf:docinfo:/Title"),
                evidence=IssueEvidence(
                    computed_value="(missing)" if title is None else "(empty)",
                    expected_value="A descriptive document title",
                ),
                remediation_type=RemediationType.AUTO_FIX,
                remediation_guidance=(
                    "Set the document title in File > Properties > Description in Adobe Acrobat, "
                    "or re-export from the source document with the title property set."
                ),
            )
        ]
