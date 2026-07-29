"""PDF fixer: pdf.display-doc-title — sets ViewerPreferences/DisplayDocTitle=true."""

from __future__ import annotations

import pikepdf

from models.manifest import A11yIssue
from remediation.base_fixer import BaseFixer, FixBehavior, FixerResult, FixStatus


class PdfDisplayTitleFixer(BaseFixer):
    def apply(self, document: pikepdf.Pdf, issue: A11yIssue, metadata: dict, behavior: FixBehavior = None) -> FixerResult:
        try:
            root = document.Root
            if "/ViewerPreferences" not in root:
                root["/ViewerPreferences"] = pikepdf.Dictionary()

            vp = root["/ViewerPreferences"]
            vp["/DisplayDocTitle"] = pikepdf.Boolean(True)

            return FixerResult(
                status=FixStatus.FIXED,
                description="Set ViewerPreferences/DisplayDocTitle to true",
                issue_id=issue.issue_id,
            )
        except Exception as exc:
            return FixerResult(
                status=FixStatus.FAILED,
                description=f"Failed to set DisplayDocTitle: {exc}",
                issue_id=issue.issue_id,
            )
