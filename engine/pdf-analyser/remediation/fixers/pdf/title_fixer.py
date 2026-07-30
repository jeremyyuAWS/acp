"""PDF fixer: pdf.document-title — writes /Title to docinfo using pikepdf."""

from __future__ import annotations

import asyncio

import pikepdf
import pdfplumber

from mcp_client import GenerateDocumentTitleRequest, McpIssueEvidence, SurroundingContext
from models.manifest import A11yIssue
from remediation.base_fixer import BaseFixer, FixBehavior, FixerResult, FixStatus


class PdfTitleFixer(BaseFixer):
    def __init__(self, mcp_client=None) -> None:
        self._mcp = mcp_client

    def apply(self, document: pikepdf.Pdf, issue: A11yIssue, metadata: dict, behavior: FixBehavior = None) -> FixerResult:
        try:
            title = self._resolve_title(document, issue, metadata, behavior)

            with document.open_metadata() as meta:
                meta["dc:title"] = title

            document.docinfo["/Title"] = title
            return FixerResult(
                status=FixStatus.FIXED,
                description=f"Set document title to '{title}'",
                issue_id=issue.issue_id,
            )
        except Exception as exc:
            return FixerResult(
                status=FixStatus.FAILED,
                description=f"Failed to set PDF title: {exc}",
                issue_id=issue.issue_id,
            )

    def _resolve_title(self, document: pikepdf.Pdf, issue: A11yIssue, metadata: dict, behavior: FixBehavior) -> str:
        if self._mcp is not None and behavior is not None and behavior.allow_llm:
            try:
                source_path = metadata.get("source_path")
                first_heading, first_paragraph = _extract_pdf_context(source_path)
                request = GenerateDocumentTitleRequest(
                    issue_id=issue.issue_id,
                    file_name=metadata.get("file_name", ""),
                    file_type="pdf",
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

        file_name: str = metadata.get("file_name", "Untitled Document")
        title = file_name.rsplit(".", 1)[0].replace("-", " ").replace("_", " ").strip()
        return title or "Untitled Document"


def _extract_pdf_context(source_path: str | None) -> tuple[str | None, str | None]:
    if not source_path:
        return None, None
    try:
        with pdfplumber.open(source_path) as pdf:
            if not pdf.pages:
                return None, None
            first_page = pdf.pages[0]
            words = first_page.extract_words(keep_blank_chars=False)
            if not words:
                return None, None

            # Heuristic: the first short, large-font line is the heading
            # Group words into lines by their top-y coordinate (within 2pt tolerance)
            lines: list[list[dict]] = []
            for word in words:
                placed = False
                for line in lines:
                    if abs(word["top"] - line[0]["top"]) < 2:
                        line.append(word)
                        placed = True
                        break
                if not placed:
                    lines.append([word])

            first_heading: str | None = None
            first_paragraph: str | None = None
            body_lines: list[str] = []

            for line in lines:
                text = " ".join(w["text"] for w in line).strip()
                if not text:
                    continue
                avg_height = sum(w["height"] for w in line) / len(line)
                if first_heading is None and avg_height > 10 and len(text) < 120:
                    first_heading = text
                else:
                    body_lines.append(text)
                if first_heading and body_lines:
                    break

            if body_lines:
                first_paragraph = " ".join(body_lines)[:500]

            return first_heading, first_paragraph
    except Exception:
        return None, None


def _call_mcp_sync(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
