"""
HTML fixer: html.skip-nav (bypass / skip-link axe rules)
Injects a skip navigation link as the first element inside <body>.
"""

from __future__ import annotations

from bs4 import BeautifulSoup

from models.manifest import A11yIssue
from remediation.base_fixer import BaseFixer, FixBehavior, FixerResult, FixStatus

_SKIP_LINK_HTML = (
    '<a href="#main-content" '
    'style="position:absolute;left:-9999px;top:auto;width:1px;height:1px;overflow:hidden;" '
    'class="skip-link">'
    'Skip to main content'
    '</a>'
)


class HtmlSkipNavFixer(BaseFixer):
    def apply(self, document: BeautifulSoup, issue: A11yIssue, metadata: dict, behavior: FixBehavior = None) -> FixerResult:
        try:
            # Check if a skip link already exists
            existing = document.find("a", class_="skip-link")
            if existing:
                return FixerResult(
                    status=FixStatus.SKIPPED,
                    description="Skip navigation link already present",
                    issue_id=issue.issue_id,
                )

            body = document.find("body")
            if body is None:
                return FixerResult(
                    status=FixStatus.SKIPPED,
                    description="No <body> tag found",
                    issue_id=issue.issue_id,
                )

            skip_tag = BeautifulSoup(_SKIP_LINK_HTML, "lxml").find("a")
            body.insert(0, skip_tag)

            # Also ensure there's a #main-content anchor target if no <main> exists
            main = document.find("main") or document.find(id="main-content")
            if main is None:
                # Wrap body content in a <main> with the id
                first_content = body.find(
                    lambda tag: tag.name not in (None, "script", "style", "a")
                )
                if first_content:
                    first_content["id"] = "main-content"

            return FixerResult(
                status=FixStatus.FIXED,
                description="Injected skip-to-main-content link at start of <body>",
                issue_id=issue.issue_id,
            )
        except Exception as exc:
            return FixerResult(
                status=FixStatus.FAILED,
                description=f"Failed to inject skip link: {exc}",
                issue_id=issue.issue_id,
            )
