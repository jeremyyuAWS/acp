"""
PDF fixer: pdf.missing-bookmarks

With MCP enabled: extracts candidate headings from the PDF via pdfplumber, asks
generate_heading_structure for a corrected outline, then builds named bookmarks
pointing to the page where each heading appears.

Without MCP (or when MCP is unavailable): falls back to a flat page-level outline
(Page 1, Page 2, …).  A proper outline should be built from heading structure.
"""

from __future__ import annotations

import asyncio

import pikepdf
import pdfplumber

from mcp_client import GenerateHeadingStructureRequest, McpIssueEvidence, SurroundingContext
from models.manifest import A11yIssue
from remediation.base_fixer import BaseFixer, FixBehavior, FixerResult, FixStatus

# Minimum average word height (pt) to treat a line as a potential heading
_MIN_HEADING_HEIGHT = 10
# Maximum character length for a line to be considered a heading
_MAX_HEADING_LINE_LEN = 150


class PdfBookmarksFixer(BaseFixer):
    def __init__(self, mcp_client=None) -> None:
        self._mcp = mcp_client

    def apply(self, document: pikepdf.Pdf, issue: A11yIssue, metadata: dict, behavior: FixBehavior = None) -> FixerResult:
        try:
            pages = document.pages
            if not pages:
                return FixerResult(
                    status=FixStatus.SKIPPED,
                    description="No pages found in PDF",
                    issue_id=issue.issue_id,
                )

            source_path = metadata.get("source_path")
            outline_items, description = self._build_outline(
                document, pages, source_path, issue, metadata, behavior
            )

            outlines = pikepdf.Dictionary(
                Type=pikepdf.Name("/Outlines"),
                Count=len(outline_items),
            )
            for i, item in enumerate(outline_items):
                if i > 0:
                    item["/Prev"] = outline_items[i - 1]
                if i < len(outline_items) - 1:
                    item["/Next"] = outline_items[i + 1]

            if outline_items:
                outlines["/First"] = outline_items[0]
                outlines["/Last"] = outline_items[-1]

            document.Root["/Outlines"] = document.make_indirect(outlines)

            return FixerResult(
                status=FixStatus.FIXED,
                description=description,
                issue_id=issue.issue_id,
            )
        except Exception as exc:
            return FixerResult(
                status=FixStatus.FAILED,
                description=f"Failed to add bookmarks: {exc}",
                issue_id=issue.issue_id,
            )

    def _build_outline(
        self,
        document: pikepdf.Pdf,
        pages,
        source_path: str | None,
        issue: A11yIssue,
        metadata: dict,
        behavior: FixBehavior,
    ) -> tuple[list[pikepdf.Dictionary], str]:
        # Try heading-based outline via MCP
        if self._mcp is not None and behavior is not None and behavior.allow_llm and source_path:
            try:
                extracted = _extract_heading_candidates(source_path)
                if extracted:
                    heading_outline = [{"level": h["level"], "text": h["text"]} for h in extracted]
                    request = GenerateHeadingStructureRequest(
                        issue_id=issue.issue_id,
                        file_name=metadata.get("file_name", ""),
                        file_type="pdf",
                        surrounding_context=SurroundingContext(
                            heading_outline=heading_outline,
                        ),
                        evidence=McpIssueEvidence(
                            snippet=issue.evidence.snippet if issue.evidence else None,
                        ),
                        wcag_criterion=str(issue.wcag_criterion),
                    )
                    response = _call_mcp_sync(self._mcp.generate_heading_structure(request))
                    if response and response.proposed_structure:
                        items = _build_named_items(document, pages, response.proposed_structure, extracted)
                        if items:
                            return items, f"Added {len(items)} heading-based bookmarks (AI-proposed structure — review recommended)"
            except Exception:
                pass

        # Fallback: flat page-level outline
        items = _build_flat_items(document, pages)
        return items, f"Added page-level bookmarks for {len(pages)} pages — review and replace with heading-based bookmarks"


def _extract_heading_candidates(source_path: str) -> list[dict]:
    """
    Returns a list of dicts with keys: text, page_index, level.
    Level is a rough estimate based on font size relative to the median body size.
    """
    candidates: list[dict] = []
    try:
        with pdfplumber.open(source_path) as pdf:
            for page_index, page in enumerate(pdf.pages):
                words = page.extract_words(keep_blank_chars=False, extra_attrs=["height", "fontname"])
                if not words:
                    continue

                # Group into lines by top-y coordinate
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

                for line in lines:
                    text = " ".join(w["text"] for w in line).strip()
                    if not text or len(text) > _MAX_HEADING_LINE_LEN:
                        continue
                    avg_height = sum(w["height"] for w in line) / len(line)
                    if avg_height < _MIN_HEADING_HEIGHT:
                        continue
                    # Rough level: larger font = lower level number (h1 > h2 > h3)
                    if avg_height >= 18:
                        level = 1
                    elif avg_height >= 14:
                        level = 2
                    else:
                        level = 3
                    candidates.append({"text": text, "page_index": page_index, "level": level})
    except Exception:
        pass
    return candidates


def _build_named_items(
    document: pikepdf.Pdf,
    pages,
    proposed: list[dict],
    extracted: list[dict],
) -> list[pikepdf.Dictionary]:
    """
    Map each proposed heading back to the best matching extracted candidate to
    get a page destination, then build pikepdf outline items.
    """
    items: list[pikepdf.Dictionary] = []
    used_indices: set[int] = set()

    for entry in proposed:
        text = (entry.get("text") or "").strip()
        if not text:
            continue

        # Find the closest not-yet-used extracted heading by simple substring match
        best_idx: int | None = None
        best_score = -1
        for i, cand in enumerate(extracted):
            if i in used_indices:
                continue
            cand_text = cand["text"].lower()
            entry_text = text.lower()
            # Score: number of shared words
            score = len(set(entry_text.split()) & set(cand_text.split()))
            if score > best_score:
                best_score = score
                best_idx = i

        if best_idx is not None and best_score > 0:
            page_index = extracted[best_idx]["page_index"]
            used_indices.add(best_idx)
        else:
            # No match — skip rather than producing a misleading destination
            continue

        if page_index >= len(pages):
            continue

        dest = pikepdf.Array([pages[page_index], pikepdf.Name("/Fit")])
        item = pikepdf.Dictionary(Title=pikepdf.String(text), Dest=dest)
        items.append(item)

    return items


def _build_flat_items(document: pikepdf.Pdf, pages) -> list[pikepdf.Dictionary]:
    items = []
    for i, page in enumerate(pages):
        dest = pikepdf.Array([page, pikepdf.Name("/Fit")])
        items.append(pikepdf.Dictionary(Title=pikepdf.String(f"Page {i + 1}"), Dest=dest))
    return items


def _call_mcp_sync(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
