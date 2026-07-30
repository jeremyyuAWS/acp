"""
HTML fixer: html.heading-structure
Never mutates the document — always HUMAN_REQUIRED.
When MCP is available, proposes a corrected heading outline in the skip reason for human review.
Handles axe rules: heading-order, empty-heading.
"""

from __future__ import annotations

import asyncio

from bs4 import BeautifulSoup, Tag

from mcp_client import GenerateHeadingStructureRequest, McpIssueEvidence, SurroundingContext
from models.manifest import A11yIssue
from remediation.base_fixer import BaseFixer, FixBehavior, FixerResult, FixStatus

_HEADING_TAGS = ["h1", "h2", "h3", "h4", "h5", "h6"]


class HtmlHeadingStructureFixer(BaseFixer):
    def __init__(self, mcp_client=None) -> None:
        self._mcp = mcp_client

    def apply(self, document: BeautifulSoup, issue: A11yIssue, metadata: dict, behavior: FixBehavior = None) -> FixerResult:
        if behavior is None:
            behavior = FixBehavior.default()
        if self._mcp is None or not behavior.allow_llm:
            return FixerResult(
                status=FixStatus.SKIPPED,
                description="Heading structure requires human review — MCP not configured or LLM disabled",
                issue_id=issue.issue_id,
            )

        try:
            outline = _extract_heading_outline(document)
            request = GenerateHeadingStructureRequest(
                issue_id=issue.issue_id,
                file_name=metadata.get("file_name", ""),
                file_type="html",
                surrounding_context=SurroundingContext(heading_outline=outline),
                evidence=McpIssueEvidence(
                    snippet=issue.evidence.snippet,
                    computed_value=issue.evidence.computed_value,
                ),
                wcag_criterion=str(issue.wcag_criterion),
            )

            response = _call_mcp_sync(self._mcp.generate_heading_structure(request))

            if response and response.proposed_structure:
                proposal = "; ".join(
                    f"H{entry.get('level', '?')}: {entry.get('text', '').strip()}"
                    for entry in response.proposed_structure
                )
                description = f"AI proposed heading structure: [{proposal}] — apply manually"
            else:
                description = "Heading structure requires human review"

        except Exception:
            description = "Heading structure requires human review"

        return FixerResult(
            status=FixStatus.SKIPPED,
            description=description,
            issue_id=issue.issue_id,
        )


def _extract_heading_outline(soup: BeautifulSoup) -> list[dict]:
    outline = []
    for tag in soup.find_all(_HEADING_TAGS):
        if isinstance(tag, Tag):
            text = tag.get_text(strip=True)
            level = int(tag.name[1])
            outline.append({"level": level, "text": text})
    return outline


def _call_mcp_sync(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
