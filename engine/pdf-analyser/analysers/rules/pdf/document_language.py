"""
Rule: pdf.document-language — WCAG 3.1.1 (Language of Page)

Checks that the PDF has a document language set in the catalog /Lang entry.
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

RULE_ID = "pdf.document-language"


class DocumentLanguageRule:
    rule_id = RULE_ID

    def check(self, pdf: pikepdf.Pdf, plumber_pdf: pdfplumber.PDF) -> list[A11yIssue]:
        lang: str | None = None
        try:
            raw = pdf.Root.get("/Lang")
            if raw is not None:
                lang = str(raw).strip()
        except Exception:
            pass

        if lang:
            return []

        return [
            A11yIssue(
                issue_id=uuid4(),
                rule_id=RULE_ID,
                title="PDF is missing a document language",
                description=(
                    "The PDF catalog does not specify a language (/Lang entry). "
                    "Screen readers use the document language to select the correct "
                    "text-to-speech voice and pronunciation rules."
                ),
                severity=IssueSeverity.SERIOUS,
                category=IssueCategory.LANGUAGE,
                wcag_criterion=WcagCriterion.SC_3_1_1,
                location=IssueLocation(description="pdf:catalog:/Lang"),
                evidence=IssueEvidence(
                    computed_value="(missing)" if lang is None else "(empty)",
                    expected_value="A valid BCP 47 language tag, e.g. en-GB",
                ),
                remediation_type=RemediationType.HUMAN_REQUIRED,
                remediation_guidance=(
                    "Set the document language in Adobe Acrobat: File > Properties > Advanced > "
                    "Language. Or re-export from the source document with the language set."
                ),
            )
        ]
