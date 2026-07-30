"""
Rule: pdf.table-headers — WCAG 1.3.1 (Info and Relationships)

Walks the PDF structure tree looking for /Table elements that have no /TH header cells.
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

RULE_ID = "pdf.table-headers"


class TableHeadersRule:
    rule_id = RULE_ID

    def check(self, pdf: pikepdf.Pdf, plumber_pdf: pdfplumber.PDF) -> list[A11yIssue]:
        root = pdf.Root
        if "/StructTreeRoot" not in root:
            return []

        try:
            struct_root = root["/StructTreeRoot"]
            tables = _collect_nodes(struct_root, "/Table")
        except Exception:
            return []

        issues: list[A11yIssue] = []
        for idx, table in enumerate(tables):
            descendants = _collect_all_descendants(table)
            has_th = any(str(node.get("/S", "")) == "/TH" for node in descendants)
            if not has_th:
                issues.append(
                    A11yIssue(
                        issue_id=uuid4(),
                        rule_id=RULE_ID,
                        title="Table has no header cells",
                        description=(
                            "A table in the PDF structure tree has no /TH header cell elements. "
                            "Screen readers cannot associate data cells with their headers."
                        ),
                        severity=IssueSeverity.SERIOUS,
                        category=IssueCategory.TABLES,
                        wcag_criterion=WcagCriterion.SC_1_3_1,
                        location=IssueLocation(
                            element_index=idx,
                            description=f"StructTree Table[{idx}]",
                        ),
                        evidence=IssueEvidence(
                            computed_value="Table has no header cells (/TH)",
                            expected_value="First row marked as header with /TH elements",
                        ),
                        remediation_type=RemediationType.HUMAN_REQUIRED,
                        remediation_guidance=(
                            "In Adobe Acrobat, use the Tags panel to change the first row's "
                            "cells from /TD to /TH and set the Scope attribute to Column or Row."
                        ),
                    )
                )

        return issues


def _collect_nodes(node, target_type: str, results: list | None = None) -> list:
    if results is None:
        results = []
    try:
        if isinstance(node, pikepdf.Dictionary):
            if str(node.get("/S", "")) == target_type:
                results.append(node)
            for key in ("/K", "/C"):
                if key in node:
                    child = node[key]
                    if isinstance(child, pikepdf.Array):
                        for item in child:
                            _collect_nodes(item, target_type, results)
                    else:
                        _collect_nodes(child, target_type, results)
        elif isinstance(node, pikepdf.Array):
            for item in node:
                _collect_nodes(item, target_type, results)
    except Exception:
        pass
    return results


def _collect_all_descendants(node, results: list | None = None) -> list:
    if results is None:
        results = []
    try:
        if isinstance(node, pikepdf.Dictionary):
            results.append(node)
            for key in ("/K", "/C"):
                if key in node:
                    child = node[key]
                    if isinstance(child, pikepdf.Array):
                        for item in child:
                            _collect_all_descendants(item, results)
                    else:
                        _collect_all_descendants(child, results)
        elif isinstance(node, pikepdf.Array):
            for item in node:
                _collect_all_descendants(item, results)
    except Exception:
        pass
    return results
