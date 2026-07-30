"""HTML fixer: html.language / html.html-lang-valid — injects lang attribute on <html>."""

from __future__ import annotations

from bs4 import BeautifulSoup

from models.manifest import A11yIssue
from remediation.base_fixer import BaseFixer, FixBehavior, FixerResult, FixStatus


class HtmlLangFixer(BaseFixer):
    def apply(self, document: BeautifulSoup, issue: A11yIssue, metadata: dict, behavior: FixBehavior = None) -> FixerResult:
        try:
            html_tag = document.find("html")
            if html_tag is None:
                return FixerResult(
                    status=FixStatus.SKIPPED,
                    description="No <html> tag found",
                    issue_id=issue.issue_id,
                )

            lang = metadata.get("language", "en")
            existing = html_tag.get("lang", "").strip()

            if existing:
                return FixerResult(
                    status=FixStatus.SKIPPED,
                    description=f"lang attribute already set to '{existing}'",
                    issue_id=issue.issue_id,
                )

            html_tag["lang"] = lang
            return FixerResult(
                status=FixStatus.FIXED,
                description=f"Added lang=\"{lang}\" to <html> element",
                issue_id=issue.issue_id,
            )
        except Exception as exc:
            return FixerResult(
                status=FixStatus.FAILED,
                description=f"Failed to set lang attribute: {exc}",
                issue_id=issue.issue_id,
            )
