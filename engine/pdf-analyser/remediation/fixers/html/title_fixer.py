"""HTML fixer: html.document-title — injects <title> in <head>."""

from __future__ import annotations

import asyncio
import re

from bs4 import BeautifulSoup, Tag

from mcp_client import GenerateDocumentTitleRequest, McpIssueEvidence, SurroundingContext
from models.manifest import A11yIssue
from remediation.base_fixer import BaseFixer, FixBehavior, FixerResult, FixStatus

_HEADING_RE = re.compile(r"^h[1-6]$")


class HtmlTitleFixer(BaseFixer):
    def __init__(self, mcp_client=None) -> None:
        self._mcp = mcp_client

    def apply(self, document: BeautifulSoup, issue: A11yIssue, metadata: dict, behavior: FixBehavior = None) -> FixerResult:
        try:
            head = document.find("head")
            if head is None:
                head = document.new_tag("head")
                html_tag = document.find("html")
                if html_tag:
                    html_tag.insert(0, head)
                else:
                    document.insert(0, head)

            title_tag = document.find("title")
            if title_tag and title_tag.get_text(strip=True):
                return FixerResult(
                    status=FixStatus.SKIPPED,
                    description="Title already present",
                    issue_id=issue.issue_id,
                )

            title_text = self._resolve_title(document, issue, metadata, behavior)

            if title_tag:
                title_tag.string = title_text
            else:
                new_title = document.new_tag("title")
                new_title.string = title_text
                head.insert(0, new_title)

            return FixerResult(
                status=FixStatus.FIXED,
                description=f"Injected <title>{title_text}</title>",
                issue_id=issue.issue_id,
            )
        except Exception as exc:
            return FixerResult(
                status=FixStatus.FAILED,
                description=f"Failed to set HTML title: {exc}",
                issue_id=issue.issue_id,
            )

    def _resolve_title(self, document: BeautifulSoup, issue: A11yIssue, metadata: dict, behavior: FixBehavior) -> str:
        if self._mcp is not None and behavior is not None and behavior.allow_llm:
            try:
                first_heading = _extract_first_heading(document)
                first_paragraph = _extract_first_paragraph(document)
                request = GenerateDocumentTitleRequest(
                    issue_id=issue.issue_id,
                    file_name=metadata.get("file_name", ""),
                    file_type="html",
                    surrounding_context=SurroundingContext(
                        first_heading=first_heading,
                        first_paragraph=first_paragraph,
                        document_language=metadata.get("language", "en"),
                    ),
                    evidence=McpIssueEvidence(
                        snippet=issue.evidence.snippet if issue.evidence else None,
                        computed_value=issue.evidence.computed_value if issue.evidence else None,
                    ),
                    wcag_criterion=str(issue.wcag_criterion),
                )
                response = _call_mcp_sync(self._mcp.generate_document_title(request))
                if response and response.generated_text:
                    return response.generated_text
            except Exception:
                pass

        file_name: str = metadata.get("file_name", "Untitled Page")
        title_text = file_name.rsplit(".", 1)[0].replace("-", " ").replace("_", " ").strip()
        return title_text or "Untitled Page"


def _extract_first_heading(document: BeautifulSoup) -> str | None:
    tag = document.find(_HEADING_RE)
    if isinstance(tag, Tag):
        text = tag.get_text(strip=True)
        return text or None
    return None


def _extract_first_paragraph(document: BeautifulSoup) -> str | None:
    for p in document.find_all("p"):
        if not isinstance(p, Tag):
            continue
        text = p.get_text(strip=True)
        if text:
            return text[:500]
    return None


def _call_mcp_sync(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
