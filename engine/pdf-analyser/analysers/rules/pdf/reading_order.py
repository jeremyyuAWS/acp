"""
Rule: pdf.reading-order — WCAG 1.3.2 (Meaningful Sequence)

Heuristic: compares the visual top-to-bottom order of text blocks on each page
(from pdfplumber layout) with the order they appear in the content stream.
If more than DIVERGENCE_THRESHOLD of blocks are significantly out of visual order,
the page is flagged. Limited to the first MAX_PAGES pages for performance.

This is inherently imprecise and reports at MODERATE severity.
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

RULE_ID = "pdf.reading-order"
_MAX_PAGES = 20
_DIVERGENCE_THRESHOLD = 0.25  # 25% of blocks out of order triggers the issue
_MIN_BLOCKS = 4               # need at least this many blocks to draw a conclusion


class ReadingOrderRule:
    rule_id = RULE_ID

    def check(self, pdf: pikepdf.Pdf, plumber_pdf: pdfplumber.PDF) -> list[A11yIssue]:
        issues: list[A11yIssue] = []
        pages_to_check = min(len(plumber_pdf.pages), _MAX_PAGES)

        for page_idx in range(pages_to_check):
            try:
                page = plumber_pdf.pages[page_idx]
                words = page.extract_words(use_text_flow=False)
                if len(words) < _MIN_BLOCKS:
                    continue

                divergence = _compute_divergence(words)
                if divergence >= _DIVERGENCE_THRESHOLD:
                    issues.append(
                        A11yIssue(
                            issue_id=uuid4(),
                            rule_id=RULE_ID,
                            title="Possible reading order issue detected",
                            description=(
                                f"Page {page_idx + 1} may have a reading order that does not match "
                                "the visual layout. Screen readers follow the content stream order, "
                                "which may cause text to be read in the wrong sequence."
                            ),
                            severity=IssueSeverity.MODERATE,
                            category=IssueCategory.READING_ORDER,
                            wcag_criterion=WcagCriterion.SC_1_3_2,
                            location=IssueLocation(page_number=page_idx + 1),
                            evidence=IssueEvidence(
                                computed_value=f"{divergence:.0%} of text blocks appear out of visual order",
                                expected_value="Content stream order matches visual reading order",
                                additional_context={
                                    "page": str(page_idx + 1),
                                    "block_count": str(len(words)),
                                },
                            ),
                            remediation_type=RemediationType.HUMAN_REQUIRED,
                            remediation_guidance=(
                                "Use the Order panel in Adobe Acrobat to verify and correct the "
                                "reading order. This may require re-tagging the document."
                            ),
                        )
                    )
            except Exception:
                pass

        return issues


def _compute_divergence(words: list[dict]) -> float:
    """
    Compute what fraction of text blocks are out of top-to-bottom, left-to-right visual order
    relative to their position in the content stream (which is the list order from pdfplumber).

    Strategy: sort blocks by (top, x0) to get visual order, then count inversions.
    We use a simple positional comparison rather than full inversion count for speed.
    """
    if not words:
        return 0.0

    # pdfplumber y-axis: top of page = 0 in some versions, bottom = 0 in others.
    # We sort by 'top' ascending (smaller top = higher on page) and 'x0' for same line.
    visual_order = sorted(range(len(words)), key=lambda i: (words[i]["top"], words[i]["x0"]))

    # Count how many positions differ between stream order (0,1,2,...) and visual order
    out_of_order = sum(
        1 for stream_pos, visual_pos in enumerate(visual_order)
        if abs(stream_pos - visual_pos) > max(2, len(words) * 0.1)
    )

    return out_of_order / len(words)
