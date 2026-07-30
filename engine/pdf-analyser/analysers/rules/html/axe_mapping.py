"""
Maps axe-core violation objects to A11yIssue instances.

axe-core violation schema (relevant fields):
  {
    "id": "image-alt",           # rule ID
    "impact": "critical",        # critical | serious | moderate | minor
    "description": "...",
    "help": "...",
    "helpUrl": "...",
    "nodes": [
      {
        "target": ["img:nth-child(2)"],   # CSS selector(s)
        "html": "<img src='x.png'>",
        "failureSummary": "Fix any of the following: ..."
      }
    ]
  }

Each node in a violation becomes a separate A11yIssue.
"""

from __future__ import annotations

from uuid import uuid4

from models.manifest import (
    A11yIssue,
    IssueCategory,
    IssueEvidence,
    IssueLocation,
    IssueSeverity,
    RemediationType,
    WcagCriterion,
)

# ── Severity mapping ──────────────────────────────────────────────────────────

_AXE_SEVERITY: dict[str, IssueSeverity] = {
    "critical": IssueSeverity.CRITICAL,
    "serious": IssueSeverity.SERIOUS,
    "moderate": IssueSeverity.MODERATE,
    "minor": IssueSeverity.MINOR,
}

# ── Rule metadata mapping ─────────────────────────────────────────────────────
# Maps axe rule ID → (our_rule_id, category, wcag_criterion, remediation_type)

_RULE_MAP: dict[str, tuple[str, IssueCategory, WcagCriterion, RemediationType]] = {
    "image-alt": (
        "html.alt-text",
        IssueCategory.ALT_TEXT,
        WcagCriterion.SC_1_1_1,
        RemediationType.AUTO_PLACEHOLDER,
    ),
    "image-redundant-alt": (
        "html.alt-text",
        IssueCategory.ALT_TEXT,
        WcagCriterion.SC_1_1_1,
        RemediationType.HUMAN_REQUIRED,
    ),
    "document-title": (
        "html.document-title",
        IssueCategory.DOCUMENT_TITLE,
        WcagCriterion.SC_2_4_2,
        RemediationType.AUTO_FIX,
    ),
    "heading-order": (
        "html.heading-structure",
        IssueCategory.HEADING_STRUCTURE,
        WcagCriterion.SC_2_4_6,
        RemediationType.HUMAN_REQUIRED,
    ),
    "empty-heading": (
        "html.heading-structure",
        IssueCategory.HEADING_STRUCTURE,
        WcagCriterion.SC_2_4_6,
        RemediationType.HUMAN_REQUIRED,
    ),
    "link-name": (
        "html.link-purpose",
        IssueCategory.LINKS,
        WcagCriterion.SC_2_4_4,
        RemediationType.HUMAN_REQUIRED,
    ),
    "html-has-lang": (
        "html.language",
        IssueCategory.LANGUAGE,
        WcagCriterion.SC_3_1_1,
        RemediationType.AUTO_FIX,
    ),
    "html-lang-valid": (
        "html.html-lang-valid",
        IssueCategory.LANGUAGE,
        WcagCriterion.SC_3_1_1,
        RemediationType.HUMAN_REQUIRED,
    ),
    "html-xml-lang-mismatch": (
        "html.html-lang-valid",
        IssueCategory.LANGUAGE,
        WcagCriterion.SC_3_1_1,
        RemediationType.HUMAN_REQUIRED,
    ),
    "label": (
        "html.label",
        IssueCategory.FORMS,
        WcagCriterion.SC_1_3_1,
        RemediationType.HUMAN_REQUIRED,
    ),
    "label-content-name-mismatch": (
        "html.label",
        IssueCategory.FORMS,
        WcagCriterion.SC_1_3_1,
        RemediationType.HUMAN_REQUIRED,
    ),
    "color-contrast": (
        "html.colour-contrast",
        IssueCategory.COLOUR_CONTRAST,
        WcagCriterion.SC_1_4_3,
        RemediationType.HUMAN_REQUIRED,
    ),
    "color-contrast-enhanced": (
        "html.colour-contrast",
        IssueCategory.COLOUR_CONTRAST,
        WcagCriterion.SC_1_4_3,
        RemediationType.HUMAN_REQUIRED,
    ),
    "td-headers-attr": (
        "html.table-headers",
        IssueCategory.TABLES,
        WcagCriterion.SC_1_3_1,
        RemediationType.HUMAN_REQUIRED,
    ),
    "th-has-data-cells": (
        "html.table-headers",
        IssueCategory.TABLES,
        WcagCriterion.SC_1_3_1,
        RemediationType.HUMAN_REQUIRED,
    ),
    "scope-attr-valid": (
        "html.table-headers",
        IssueCategory.TABLES,
        WcagCriterion.SC_1_3_1,
        RemediationType.HUMAN_REQUIRED,
    ),
    "aria-roles": (
        "html.aria-roles",
        IssueCategory.NAME_ROLE_VALUE,
        WcagCriterion.SC_4_1_2,
        RemediationType.HUMAN_REQUIRED,
    ),
    "aria-allowed-attr": (
        "html.aria-roles",
        IssueCategory.NAME_ROLE_VALUE,
        WcagCriterion.SC_4_1_2,
        RemediationType.HUMAN_REQUIRED,
    ),
    "aria-required-attr": (
        "html.aria-roles",
        IssueCategory.NAME_ROLE_VALUE,
        WcagCriterion.SC_4_1_2,
        RemediationType.HUMAN_REQUIRED,
    ),
    "aria-required-children": (
        "html.aria-roles",
        IssueCategory.NAME_ROLE_VALUE,
        WcagCriterion.SC_4_1_2,
        RemediationType.HUMAN_REQUIRED,
    ),
    "aria-required-parent": (
        "html.aria-roles",
        IssueCategory.NAME_ROLE_VALUE,
        WcagCriterion.SC_4_1_2,
        RemediationType.HUMAN_REQUIRED,
    ),
    "bypass": (
        "html.skip-nav",
        IssueCategory.KEYBOARD_NAVIGATION,
        WcagCriterion.SC_2_1_1,
        RemediationType.AUTO_FIX,
    ),
    "skip-link": (
        "html.skip-nav",
        IssueCategory.KEYBOARD_NAVIGATION,
        WcagCriterion.SC_2_1_1,
        RemediationType.AUTO_FIX,
    ),
    # Additional common axe rules
    "button-name": (
        "html.aria-roles",
        IssueCategory.NAME_ROLE_VALUE,
        WcagCriterion.SC_4_1_2,
        RemediationType.HUMAN_REQUIRED,
    ),
    "frame-title": (
        "html.aria-roles",
        IssueCategory.NAME_ROLE_VALUE,
        WcagCriterion.SC_4_1_2,
        RemediationType.HUMAN_REQUIRED,
    ),
    "input-image-alt": (
        "html.alt-text",
        IssueCategory.ALT_TEXT,
        WcagCriterion.SC_1_1_1,
        RemediationType.HUMAN_REQUIRED,
    ),
    "object-alt": (
        "html.alt-text",
        IssueCategory.ALT_TEXT,
        WcagCriterion.SC_1_1_1,
        RemediationType.HUMAN_REQUIRED,
    ),
}

_FALLBACK = (
    "html.accessibility",
    IssueCategory.PARSING,
    WcagCriterion.SC_4_1_1,
    RemediationType.HUMAN_REQUIRED,
)


def map_axe_violation(violation: dict, disabled_rule_ids: set[str]) -> list[A11yIssue]:
    """
    Convert a single axe-core violation (with potentially many nodes)
    into a list of A11yIssue objects, one per node.
    """
    axe_id: str = violation.get("id", "")
    impact: str = violation.get("impact", "serious")
    help_text: str = violation.get("help", "")
    description: str = violation.get("description", help_text)

    rule_id, category, wcag_criterion, remediation_type = _RULE_MAP.get(axe_id, _FALLBACK)

    # Use the mapped rule_id (not axe_id) for disabled-rule checking
    if rule_id in disabled_rule_ids:
        return []

    severity = _AXE_SEVERITY.get(impact, IssueSeverity.SERIOUS)

    issues: list[A11yIssue] = []
    for node in violation.get("nodes", []):
        target = node.get("target", [])
        html_snippet = node.get("html", "")
        failure_summary = node.get("failureSummary", "")

        # Build additional context from axe's any/all/none check messages
        additional: dict[str, str] = {}
        if failure_summary:
            additional["failureSummary"] = failure_summary[:500]
        if axe_id != rule_id:
            additional["axeRuleId"] = axe_id

        issues.append(
            A11yIssue(
                issue_id=uuid4(),
                rule_id=rule_id,
                title=help_text or description,
                description=description,
                severity=severity,
                category=category,
                wcag_criterion=wcag_criterion,
                location=IssueLocation(
                    x_path=", ".join(str(t) for t in target) if target else None,
                    description=f"axe: {axe_id}",
                ),
                evidence=IssueEvidence(
                    snippet=html_snippet[:500] if html_snippet else None,
                    additional_context=additional if additional else None,
                ),
                remediation_type=remediation_type,
            )
        )

    return issues
