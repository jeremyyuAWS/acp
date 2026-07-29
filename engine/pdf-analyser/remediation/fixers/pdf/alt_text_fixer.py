"""
PDF fixer: pdf.missing-alt-text
Sets the /Alt attribute on Figure structure tree elements that lack one.
Attempts AI-generated alt text via MCP (with page image for vision); falls back to a placeholder.
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging

import pikepdf
import pypdfium2

from mcp_client import GenerateAltTextRequest, McpIssueEvidence, McpIssueLocation
from models.manifest import A11yIssue
from remediation.base_fixer import BaseFixer, FixBehavior, FixerResult, FixStatus
from remediation.placeholders import RemediationPlaceholders

logger = logging.getLogger(__name__)

# Render at 150 DPI — enough detail for vision without excessive token cost
_RENDER_DPI = 150
_POINTS_PER_INCH = 72
_SCALE = _RENDER_DPI / _POINTS_PER_INCH


class PdfAltTextFixer(BaseFixer):
    def __init__(self, mcp_client=None) -> None:
        self._mcp = mcp_client

    def apply(self, document: pikepdf.Pdf, issue: A11yIssue, metadata: dict, behavior: FixBehavior = None) -> FixerResult:
        try:
            struct_root = document.Root.get("/StructTreeRoot")
            if struct_root is None:
                return FixerResult(
                    status=FixStatus.SKIPPED,
                    description="PDF has no StructTreeRoot — cannot set alt text",
                    issue_id=issue.issue_id,
                )

            element_index = issue.location.element_index
            figures = _collect_figures(struct_root)

            if element_index is not None and element_index < len(figures):
                target_figures = [figures[element_index]]
            else:
                target_figures = [f for f in figures if _get_alt(f) is None]

            fixed_count = 0
            ai_generated = False
            for fig in target_figures:
                if _get_alt(fig) is None:
                    page_number = _resolve_page_number(fig, document)
                    image_data = _render_page_base64(metadata.get("source_path"), page_number)
                    alt_text = self._resolve_alt_text(issue, metadata, behavior, image_data)
                    if alt_text is None:
                        return FixerResult(
                            status=FixStatus.SKIPPED,
                            description="LLM and placeholder fixes both disabled — skipped",
                            issue_id=issue.issue_id,
                        )
                    if alt_text != RemediationPlaceholders.ALT_TEXT:
                        ai_generated = True
                    fig["/Alt"] = pikepdf.String(alt_text)
                    fixed_count += 1

            if fixed_count == 0:
                return FixerResult(
                    status=FixStatus.SKIPPED,
                    description="No figure elements found to fix",
                    issue_id=issue.issue_id,
                )

            description = (
                f"Set AI-generated alt text on {fixed_count} figure(s) — review recommended"
                if ai_generated
                else f"Set placeholder alt text on {fixed_count} figure(s) — manual description required"
            )
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

    def _resolve_alt_text(self, issue: A11yIssue, metadata: dict, behavior: FixBehavior, image_data: str | None) -> str | None:
        if self._mcp is not None and behavior.allow_llm:
            try:
                request = GenerateAltTextRequest(
                    issue_id=issue.issue_id,
                    file_name=metadata.get("file_name", ""),
                    file_type="pdf",
                    location=McpIssueLocation(element_index=issue.location.element_index),
                    evidence=McpIssueEvidence(
                        snippet=issue.evidence.snippet,
                        computed_value=issue.evidence.computed_value,
                    ),
                    wcag_criterion=str(issue.wcag_criterion),
                    image_data=image_data,
                )
                response = _call_mcp_sync(self._mcp.generate_alt_text(request))
                if response and response.generated_text:
                    return response.generated_text
            except Exception:
                logger.warning("MCP alt text generation failed — falling back to placeholder", exc_info=True)
        if behavior.allow_placeholders:
            return RemediationPlaceholders.ALT_TEXT
        return None


def _render_page_base64(source_path: str | None, page_number: int | None) -> str | None:
    """Render a PDF page to a base64-encoded PNG using pypdfium2. Returns None on any failure."""
    if source_path is None or page_number is None:
        return None
    try:
        pdf = pypdfium2.PdfDocument(source_path)
        try:
            # page_number is 1-based from the analyser
            page_index = page_number - 1
            if page_index < 0 or page_index >= len(pdf):
                return None
            page = pdf[page_index]
            bitmap = page.render(scale=_SCALE)
            pil_image = bitmap.to_pil()
            buf = io.BytesIO()
            pil_image.save(buf, format="PNG")
            return base64.b64encode(buf.getvalue()).decode("ascii")
        finally:
            pdf.close()
    except Exception:
        logger.warning("Failed to render page %s of %s for vision", page_number, source_path, exc_info=True)
        return None


def _call_mcp_sync(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _collect_figures(node, figures: list | None = None) -> list:
    if figures is None:
        figures = []
    try:
        if isinstance(node, pikepdf.Dictionary):
            if str(node.get("/S", "")) == "/Figure":
                figures.append(node)
            for key in ("/K", "/C"):
                if key in node:
                    child = node[key]
                    if isinstance(child, pikepdf.Array):
                        for item in child:
                            _collect_figures(item, figures)
                    else:
                        _collect_figures(child, figures)
        elif isinstance(node, pikepdf.Array):
            for item in node:
                _collect_figures(item, figures)
    except Exception:
        pass
    return figures


def _get_alt(figure: pikepdf.Dictionary) -> str | None:
    try:
        raw = figure.get("/Alt")
        if raw is None:
            return None
        val = str(raw).strip()
        return val if val else None
    except Exception:
        return None


def _resolve_page_number(figure: pikepdf.Dictionary, pdf: pikepdf.Pdf) -> int | None:
    try:
        pg_ref = figure.get("/Pg")
        if pg_ref is None:
            return None
        for i, page in enumerate(pdf.pages):
            if page.objgen == pg_ref.objgen:
                return i + 1  # 1-based
    except Exception:
        pass
    return None
