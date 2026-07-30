"""
Rule: pdf.missing-alt-text — WCAG 1.1.1 (Non-text Content)

Walks the PDF structure tree looking for /Figure elements that lack an /Alt entry.
Only applies to tagged PDFs; skipped gracefully if no StructTreeRoot is present.
"""

from __future__ import annotations

from uuid import uuid4

import pikepdf
import pdfplumber

from models.manifest import (
    A11yIssue,
    IssueCategory,
    IssueEvidence,
    IssueLocation,
    IssueSeverity,
    RemediationType,
    WcagCriterion,
)

RULE_ID = "pdf.missing-alt-text"


class ImageAltTextRule:
    rule_id = RULE_ID

    def check(self, pdf: pikepdf.Pdf, plumber_pdf: pdfplumber.PDF) -> list[A11yIssue]:
        root = pdf.Root
        if "/StructTreeRoot" not in root:
            return []  # Untagged PDF — covered by pdf.tagged rule

        try:
            struct_root = root["/StructTreeRoot"]
            figures = _collect_figures(struct_root)
        except Exception:
            return []

        issues: list[A11yIssue] = []
        for idx, figure in enumerate(figures):
            alt = _get_alt(figure)
            if alt is not None:
                continue

            page_num = _resolve_page_number(figure, pdf)
            issues.append(
                A11yIssue(
                    issue_id=uuid4(),
                    rule_id=RULE_ID,
                    title="Figure element is missing alternative text",
                    description=(
                        "A tagged figure (image) in the PDF structure tree does not have "
                        "an /Alt attribute. Screen readers cannot describe this image to users."
                    ),
                    severity=IssueSeverity.CRITICAL,
                    category=IssueCategory.ALT_TEXT,
                    wcag_criterion=WcagCriterion.SC_1_1_1,
                    location=IssueLocation(
                        page_number=page_num,
                        element_index=idx,
                        description=f"StructTree Figure[{idx}]",
                    ),
                    evidence=IssueEvidence(
                        computed_value="(no /Alt attribute)",
                        expected_value="A descriptive /Alt text string",
                    ),
                    remediation_type=RemediationType.AUTO_PLACEHOLDER,
                    remediation_guidance=(
                        "Add alternative text to the figure using the Tags panel in Adobe Acrobat: "
                        "right-click the Figure tag > Properties > Alternate Text."
                    ),
                )
            )

        return issues


def _collect_figures(node, figures: list | None = None) -> list:
    if figures is None:
        figures = []
    try:
        if isinstance(node, pikepdf.Dictionary):
            s_type = node.get("/S")
            if s_type is not None and str(s_type) == "/Figure":
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
