"""
Rule: pdf.reading-order — WCAG 1.3.2 (Meaningful Sequence)

A BOUNDED capability. This reports a reading-order defect on ONE shape of page — untagged,
single-column, no out-of-flow content — and ABSTAINS everywhere else. Abstaining is not a pass:
it means this rule has no opinion, and nothing downstream may read its silence as conformance.

WHAT IT REPLACED, because the shape of the old bug is the reason for every guard below.
`page.extract_words(use_text_flow=False)` PRESORTS words by (top, x0). `_compute_divergence`
then sorted that same list by (top, x0) and counted what moved. Sorting an already-sorted list
moves nothing, so the divergence was 0.0 for every document ever scanned — including one whose
content stream is written in exactly reverse visual order — and the threshold was never reached.
The rule looked right, computed a number, and could not fire.

WHY THE ONE-WORD FIX WAS NOT THE FIX. `use_text_flow=True` makes it fire, and it is what the
docstring always described. But comparing the stream against a flat (top, x0) sort is not
comparing it against the visual READING order, and three ordinary, correct layouts score far
past the old 25% threshold under it (measured, see tests/test_pdf_reading_order.py):

    two-column layout                   78%   column one's line 2 sorts above column two's line 1
    footnote drawn before the body     100%   normal output of every layout engine
    tagged, order defined by the tree  100%   worst where it should be best

A detector that reports confidently on correct documents costs more than one that is quiet —
see the 1.4.3-on-PDF story in CLAUDE.md, where a fixer that assumed a white page rewrote
compliant dark-theme PDFs from 21:1 down to 3.66:1, unattended.

SO THE BOUNDARY IS THE FEATURE. Each abstention below corresponds to one of those measured
false positives, and each is a positive test rather than a hope:

  TAGGED           -> abstain. A tagged PDF's reading order is defined by its structure tree,
                     which is what assistive technology walks; the order glyphs happen to be
                     drawn in is irrelevant to a reader and routinely differs. NOTE THE
                     ASYMMETRY THAT MATTERS: finding /StructTreeRoot means "not assessable
                     here", NEVER "correctly ordered". A malformed or mis-ordered tree abstains
                     for exactly the same reason as a good one — this rule cannot tell them
                     apart, and must not imply it can.
  MULTI-COLUMN     -> abstain. Detected as a vertical gutter: a strip wider than 5% of the page
                     that no line crosses. Column order is a layout decision this rule cannot
                     recover.
  OUT-OF-FLOW      -> abstain. Footnotes, captions and running heads are drawn out of narrative
                     order legitimately. Detected as a line whose font is materially smaller
                     than the body's, which is what separated the footnote fixture (8.0 against
                     a body of 11.0).
  TOO FEW LINES    -> abstain. Below _MIN_LINES there is no order to speak of.

WHAT IT MEASURES WHEN IT DOES SPEAK. Lines, not words: within a line, word order is a property
of the writing system, not the reading order, and counting it adds noise that the threshold then
has to absorb. Inversions between the content-stream sequence of lines and their top-to-bottom
sequence, normalised to [0, 1] — 0.0 for a correctly ordered page, 1.0 for a fully reversed one.
Only a gross permutation is reported (_INVERSION_THRESHOLD), because a small one is more likely
to be a layout artefact this rule has not learned to recognise than a real defect.

WHAT IS STILL NOT COVERED, stated so silence is not mistaken for coverage: tagged documents (the
common case for any file that has been through an accessibility workflow), multi-column layouts,
pages with footnotes or captions, tables, and any page whose columns are implied by whitespace
rather than separated by a gutter. (1.3.2, pdf) stays visibly uncovered in the capability report
until a ground-truth corpus pair earns the narrower claim this now makes possible.

Reports at MODERATE severity: a real defect here is serious for a screen-reader user, but this
rule's confidence in its own applicability is what is bounded, so it routes to a human.
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
_MIN_LINES = 4                 # below this there is no order to speak of
_INVERSION_THRESHOLD = 0.50    # only a gross permutation is reported
_LINE_TOLERANCE = 3.0          # points; words within this of each other share a line
_GUTTER_FRACTION = 0.05        # a column gap must exceed this share of the page width
_SMALL_FONT_RATIO = 0.85       # a line this much smaller than the body reads as out-of-flow


class ReadingOrderRule:
    rule_id = RULE_ID

    def check(self, pdf: pikepdf.Pdf, plumber_pdf: pdfplumber.PDF) -> list[A11yIssue]:
        if _is_tagged(pdf):
            # Not assessable here, and NOT a statement that the order is correct.
            return []

        issues: list[A11yIssue] = []
        for page_idx in range(min(len(plumber_pdf.pages), _MAX_PAGES)):
            try:
                page = plumber_pdf.pages[page_idx]
                lines = _stream_lines(page)
                if len(lines) < _MIN_LINES:
                    continue
                if _vertical_gutter(lines, page.width) is not None:
                    continue                       # multi-column
                if _has_out_of_flow(lines):
                    continue                       # footnote / caption / running head
                ratio = _inversion_ratio(lines)
                if ratio < _INVERSION_THRESHOLD:
                    continue
                issues.append(_issue(page_idx, ratio, len(lines)))
            except Exception:
                continue                           # one unreadable page never sinks the rest
        return issues


# ── the boundary ─────────────────────────────────────────────────────────────────
def _is_tagged(pdf: pikepdf.Pdf) -> bool:
    """A structure tree means the reading order is defined somewhere this rule does not look.

    Deliberately does NOT inspect the tree's quality. A malformed or mis-ordered tree is still a
    document whose order this rule cannot judge, so it abstains identically — the alternative
    would be to let the mere presence of /StructTreeRoot stand in for correctness, which is the
    claim this rule most needs not to make.
    """
    try:
        return "/StructTreeRoot" in pdf.Root
    except Exception:
        return True        # cannot tell -> do not assess


def _stream_lines(page) -> list[dict]:
    """Lines in CONTENT-STREAM order.

    `use_text_flow=True` is the whole point: it returns words in the order the page draws them,
    which is the sequence a screen reader follows on an untagged document. The old `False` asked
    pdfplumber to sort by position first, which is the very thing being compared against.
    """
    words = page.extract_words(use_text_flow=True, extra_attrs=["size"])
    lines: list[dict] = []
    cur: dict | None = None
    for w in words:
        top = float(w["top"])
        if cur is None or abs(cur["top"] - top) > _LINE_TOLERANCE:
            cur = {"top": top, "x0": float(w["x0"]), "x1": float(w["x1"]),
                   "size": float(w.get("size") or 0.0)}
            lines.append(cur)
            continue
        cur["x0"] = min(cur["x0"], float(w["x0"]))
        cur["x1"] = max(cur["x1"], float(w["x1"]))
        cur["size"] = max(cur["size"], float(w.get("size") or 0.0))
    return lines


def _vertical_gutter(lines: list[dict], page_width: float):
    """A vertical strip no line crosses, wider than _GUTTER_FRACTION of the page — a column gap.

    Returns the gap as (x_start, x_end), or None. Merging the horizontal spans first means a
    single full-width line (a heading spanning both columns) correctly hides the gutter, which is
    the conservative direction: it produces an abstention only when the columns are unambiguous.
    """
    if not lines or not page_width:
        return None
    spans = sorted((l["x0"], l["x1"]) for l in lines)
    merged: list[list[float]] = []
    for a, b in spans:
        if merged and a <= merged[-1][1] + 1.0:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    for (_, end), (start, _) in zip(merged, merged[1:]):
        if (start - end) > page_width * _GUTTER_FRACTION:
            return (end, start)
    return None


def _has_out_of_flow(lines: list[dict]) -> bool:
    """Is some line set in a materially smaller face than the body?

    Footnotes, captions and running heads are drawn out of narrative order by every layout
    engine, legitimately, and the cheapest reliable signal for them in a text-only view is type
    size. Compared against the MEDIAN rather than the maximum so that a single large heading on
    an otherwise uniform page does not read as a body/footnote split.
    """
    sizes = sorted(l["size"] for l in lines if l["size"] > 0)
    if len(sizes) < 2:
        return False
    body = sizes[len(sizes) // 2]
    return bool(body) and sizes[0] < body * _SMALL_FONT_RATIO


def _inversion_ratio(lines: list[dict]) -> float:
    """How far the stream order of LINES departs from their top-to-bottom order.

    0.0 when the two agree, 1.0 when the stream is the exact reverse. Normalised by the number of
    pairs, so it does not drift with page length the way a raw inversion count would.
    """
    n = len(lines)
    if n < 2:
        return 0.0
    order = sorted(range(n), key=lambda i: lines[i]["top"])
    rank = [0] * n
    for visual_pos, stream_idx in enumerate(order):
        rank[stream_idx] = visual_pos
    inversions = sum(1 for i in range(n) for j in range(i + 1, n) if rank[i] > rank[j])
    return inversions / (n * (n - 1) / 2)


def _issue(page_idx: int, ratio: float, line_count: int) -> A11yIssue:
    return A11yIssue(
        issue_id=uuid4(),
        rule_id=RULE_ID,
        title="Reading order does not follow the visual layout",
        description=(
            f"On page {page_idx + 1} the text is drawn in an order that differs substantially "
            "from the order it is laid out in. This document has no structure tree, so a screen "
            "reader follows the drawing order and will read the page out of sequence."
        ),
        severity=IssueSeverity.MODERATE,
        category=IssueCategory.READING_ORDER,
        wcag_criterion=WcagCriterion.SC_1_3_2,
        location=IssueLocation(page_number=page_idx + 1),
        evidence=IssueEvidence(
            computed_value=f"{ratio:.0%} of line pairs are in the opposite order to the layout",
            expected_value="the drawing order matches the visual reading order",
            additional_context={
                "page": str(page_idx + 1),
                "line_count": str(line_count),
                "assessed_because": "untagged, single-column, no out-of-flow text",
            },
        ),
        remediation_type=RemediationType.HUMAN_REQUIRED,
        remediation_guidance=(
            "Tag the document so the reading order is defined explicitly, or re-export it from "
            "the source application so the content is drawn in reading order. Confirm the result "
            "in Acrobat's Reading Order / Tags view."
        ),
    )
