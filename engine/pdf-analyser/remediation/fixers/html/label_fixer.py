"""
HTML fixer: html.label
Associates orphaned form controls to their labels, or injects aria-label as fallback.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

from models.manifest import A11yIssue
from remediation.base_fixer import BaseFixer, FixBehavior, FixerResult, FixStatus

_SKIP_INPUT_TYPES = {"hidden", "submit", "button", "reset", "image"}


class HtmlLabelFixer(BaseFixer):
    def apply(self, document: BeautifulSoup, issue: A11yIssue, metadata: dict, behavior: FixBehavior = None) -> FixerResult:
        try:
            fixed = 0
            controls = document.find_all(["input", "select", "textarea"])

            for control in controls:
                if not isinstance(control, Tag):
                    continue
                input_type = (control.get("type") or "text").lower()
                if input_type in _SKIP_INPUT_TYPES:
                    continue

                # Skip if already labelled
                if _has_label(document, control):
                    continue

                # Attempt to associate an orphaned <label> by proximity
                associated = _associate_nearby_label(document, control)
                if associated:
                    fixed += 1
                    continue

                # Fallback: inject aria-label from placeholder, name, or id
                label_text = (
                    control.get("placeholder")
                    or control.get("name")
                    or control.get("id")
                    or "Input field"
                )
                control["aria-label"] = str(label_text).strip()
                fixed += 1

            if fixed == 0:
                return FixerResult(
                    status=FixStatus.SKIPPED,
                    description="No unlabelled form controls found to fix",
                    issue_id=issue.issue_id,
                )

            return FixerResult(
                status=FixStatus.FIXED,
                description=f"Associated labels or added aria-label to {fixed} form control(s) — review label text accuracy",
                issue_id=issue.issue_id,
            )
        except Exception as exc:
            return FixerResult(
                status=FixStatus.FAILED,
                description=f"Failed to fix form labels: {exc}",
                issue_id=issue.issue_id,
            )


def _has_label(soup: BeautifulSoup, control: Tag) -> bool:
    if control.get("aria-label") or control.get("aria-labelledby") or control.get("title"):
        return True
    control_id = control.get("id")
    if control_id:
        label = soup.find("label", attrs={"for": control_id})
        if label:
            return True
    # Check for wrapping <label>
    for parent in control.parents:
        if isinstance(parent, Tag) and parent.name == "label":
            return True
    return False


def _associate_nearby_label(soup: BeautifulSoup, control: Tag) -> bool:
    control_id = control.get("id")
    if not control_id:
        return False

    # Find a <label> that isn't yet associated to any control
    for label in soup.find_all("label"):
        if label.get("for"):
            continue  # Already associated
        label["for"] = control_id
        return True

    return False
