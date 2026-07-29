"""
HTML fixer: html.link-purpose
Replaces vague link text (e.g. "click here", "read more") with descriptive text via MCP.
Only applies when MCP returns medium or high confidence — otherwise skips for human review.
Handles axe rule: link-name.
"""

from __future__ import annotations

import asyncio

from bs4 import BeautifulSoup, NavigableString, Tag

from mcp_client import (
    ContentConfidence,
    GenerateLinkTextRequest,
    McpIssueEvidence,
    McpIssueLocation,
    SurroundingContext,
)
from models.manifest import A11yIssue
from remediation.base_fixer import BaseFixer, FixBehavior, FixerResult, FixStatus


class HtmlLinkPurposeFixer(BaseFixer):
    def __init__(self, mcp_client=None) -> None:
        self._mcp = mcp_client

    def apply(self, document: BeautifulSoup, issue: A11yIssue, metadata: dict, behavior: FixBehavior = None) -> FixerResult:
        if behavior is None:
            behavior = FixBehavior.default()
        if self._mcp is None or not behavior.allow_llm:
            return FixerResult(
                status=FixStatus.SKIPPED,
                description="Link purpose requires human review — MCP not configured or LLM disabled",
                issue_id=issue.issue_id,
            )

        try:
            el = _find_link(document, issue)
            if el is None:
                return FixerResult(
                    status=FixStatus.SKIPPED,
                    description="Target link element not found",
                    issue_id=issue.issue_id,
                )

            current_text = el.get_text(strip=True)
            href = el.get("href") or ""
            preceding, following = _extract_sentence_context(el)

            request = GenerateLinkTextRequest(
                issue_id=issue.issue_id,
                file_name=metadata.get("file_name", ""),
                file_type="html",
                location=McpIssueLocation(element_index=issue.location.element_index),
                surrounding_context=SurroundingContext(
                    current_link_text=current_text,
                    href=href or None,
                    preceding_sentence=preceding,
                    following_sentence=following,
                ),
                evidence=McpIssueEvidence(
                    snippet=issue.evidence.snippet,
                    computed_value=issue.evidence.computed_value,
                ),
                wcag_criterion=str(issue.wcag_criterion),
            )

            response = _call_mcp_sync(self._mcp.generate_link_text(request))

            if response is None or response.confidence == ContentConfidence.LOW or not response.generated_text:
                return FixerResult(
                    status=FixStatus.SKIPPED,
                    description="MCP returned low confidence or no text — skipped for human review",
                    issue_id=issue.issue_id,
                )

            el.clear()
            el.append(NavigableString(response.generated_text))

            return FixerResult(
                status=FixStatus.FIXED,
                description=f"Set AI-generated link text: '{response.generated_text}' — review recommended",
                issue_id=issue.issue_id,
            )
        except Exception as exc:
            return FixerResult(
                status=FixStatus.FAILED,
                description=f"Failed to fix link purpose: {exc}",
                issue_id=issue.issue_id,
            )


def _find_link(soup: BeautifulSoup, issue: A11yIssue) -> Tag | None:
    selector = issue.location.x_path
    if selector:
        try:
            results = soup.select(selector)
            for el in results:
                if isinstance(el, Tag) and el.name == "a":
                    return el
            # selector may point to a child — walk up to find <a>
            for el in results:
                if isinstance(el, Tag):
                    parent = el.find_parent("a")
                    if parent:
                        return parent
        except Exception:
            pass
    return None


def _extract_sentence_context(el: Tag) -> tuple[str | None, str | None]:
    preceding: str | None = None
    following: str | None = None

    for sibling in el.previous_siblings:
        text = sibling.get_text(strip=True) if isinstance(sibling, Tag) else str(sibling).strip()
        if text:
            preceding = text[-200:]
            break

    for sibling in el.next_siblings:
        text = sibling.get_text(strip=True) if isinstance(sibling, Tag) else str(sibling).strip()
        if text:
            following = text[:200]
            break

    return preceding, following


def _call_mcp_sync(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
