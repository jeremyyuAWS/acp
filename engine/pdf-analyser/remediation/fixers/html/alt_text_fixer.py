"""
HTML fixer: html.alt-text
Sets the alt attribute on img and input[type=image] elements that lack meaningful alt text.
Attempts AI-generated alt text via MCP; falls back to a placeholder requiring human review.
Handles axe rules: image-alt, input-image-alt, object-alt.
"""

from __future__ import annotations

import asyncio

from bs4 import BeautifulSoup, Tag

from mcp_client import GenerateAltTextRequest, McpIssueEvidence, McpIssueLocation, SurroundingContext
from models.manifest import A11yIssue
from remediation.base_fixer import BaseFixer, FixBehavior, FixerResult, FixStatus
from remediation.placeholders import RemediationPlaceholders


class HtmlAltTextFixer(BaseFixer):
    def __init__(self, mcp_client=None) -> None:
        self._mcp = mcp_client

    def apply(self, document: BeautifulSoup, issue: A11yIssue, metadata: dict, behavior: FixBehavior = None) -> FixerResult:
        try:
            targets = _find_targets(document, issue)
            if not targets:
                return FixerResult(
                    status=FixStatus.SKIPPED,
                    description="No target image elements found",
                    issue_id=issue.issue_id,
                )

            fixed_count = 0
            ai_generated = False
            for el in targets:
                alt_text = self._resolve_alt_text(el, issue, metadata, behavior)
                if alt_text is None:
                    return FixerResult(
                        status=FixStatus.SKIPPED,
                        description="LLM and placeholder fixes both disabled — skipped",
                        issue_id=issue.issue_id,
                    )
                if alt_text != RemediationPlaceholders.ALT_TEXT:
                    ai_generated = True
                el["alt"] = alt_text
                fixed_count += 1

            if fixed_count == 0:
                return FixerResult(
                    status=FixStatus.SKIPPED,
                    description="No elements required an alt text update",
                    issue_id=issue.issue_id,
                )

            if ai_generated:
                description = f"Set AI-generated alt text on {fixed_count} element(s) — review recommended"
            else:
                description = f"Set placeholder alt text on {fixed_count} element(s) — manual description required"

            return FixerResult(
                status=FixStatus.FIXED,
                description=description,
                issue_id=issue.issue_id,
            )
        except Exception as exc:
            return FixerResult(
                status=FixStatus.FAILED,
                description=f"Failed to set alt text: {exc}",
                issue_id=issue.issue_id,
            )

    def _resolve_alt_text(self, el: Tag, issue: A11yIssue, metadata: dict, behavior: FixBehavior) -> str | None:
        if self._mcp is not None and behavior.allow_llm:
            try:
                preceding_heading, preceding_paragraph = _extract_context(el)
                request = GenerateAltTextRequest(
                    issue_id=issue.issue_id,
                    file_name=metadata.get("file_name", ""),
                    file_type="html",
                    location=McpIssueLocation(element_index=issue.location.element_index),
                    surrounding_context=SurroundingContext(
                        preceding_heading=preceding_heading,
                        preceding_paragraph=preceding_paragraph,
                    ),
                    evidence=McpIssueEvidence(
                        snippet=issue.evidence.snippet,
                        computed_value=issue.evidence.computed_value,
                    ),
                    wcag_criterion=str(issue.wcag_criterion),
                )
                response = _call_mcp_sync(self._mcp.generate_alt_text(request))
                if response and response.generated_text:
                    return response.generated_text
            except Exception:
                pass
        if behavior.allow_placeholders:
            return RemediationPlaceholders.ALT_TEXT
        return None  # both LLM and placeholders disabled — caller must skip


def _find_targets(soup: BeautifulSoup, issue: A11yIssue) -> list[Tag]:
    selector = issue.location.x_path
    if selector:
        try:
            return [el for el in soup.select(selector) if isinstance(el, Tag)]
        except Exception:
            pass
    # Fallback: all images missing or empty alt
    return [
        el for el in soup.find_all(["img", "input"])
        if isinstance(el, Tag)
        and (el.name == "img" or el.get("type", "").lower() == "image")
        and not el.get("alt", "").strip()
    ]


def _extract_context(el: Tag) -> tuple[str | None, str | None]:
    preceding_heading: str | None = None
    preceding_paragraph: str | None = None
    heading_tags = {"h1", "h2", "h3", "h4", "h5", "h6"}

    node = el
    while node is not None:
        for sibling in reversed(list(node.previous_siblings)):
            if not isinstance(sibling, Tag):
                continue
            if sibling.name in heading_tags and preceding_heading is None:
                text = sibling.get_text(strip=True)
                if text:
                    preceding_heading = text
            elif sibling.name == "p" and preceding_paragraph is None:
                text = sibling.get_text(strip=True)
                if text:
                    preceding_paragraph = text
            if preceding_heading and preceding_paragraph:
                return preceding_heading, preceding_paragraph
        node = node.parent

    return preceding_heading, preceding_paragraph


def _call_mcp_sync(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
