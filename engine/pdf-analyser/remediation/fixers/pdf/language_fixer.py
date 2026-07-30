"""PDF fixer: pdf.document-language — writes /Lang to the PDF catalog."""

from __future__ import annotations

import pikepdf

from models.manifest import A11yIssue
from remediation.base_fixer import BaseFixer, FixBehavior, FixerResult, FixStatus


class PdfLanguageFixer(BaseFixer):
    def apply(self, document: pikepdf.Pdf, issue: A11yIssue, metadata: dict, behavior: FixBehavior = None) -> FixerResult:
        try:
            lang = metadata.get("language", "en")
            document.Root["/Lang"] = pikepdf.String(lang)
            return FixerResult(
                status=FixStatus.FIXED,
                description=f"Set document language to '{lang}'",
                issue_id=issue.issue_id,
            )
        except Exception as exc:
            return FixerResult(
                status=FixStatus.FAILED,
                description=f"Failed to set PDF language: {exc}",
                issue_id=issue.issue_id,
            )
