"""The conformance report's "Files affected" column must count FILES.

It counts issue instances. The two agree whenever every file contributes at most one finding per
criterion, which is true of every fixture in this repo and of most real scans — so the defect is
invisible almost everywhere and then prints a number larger than the scan itself.

FOUND ON A REAL SCAN, not by reading the code. 37 PDFs through the real analysers produced a
report whose Open Issues table read:

    2.4.2 Page Titled        A    Moderate    49

against 37 files. 2.4.2 had 49 findings spread over those 37 documents; every other criterion in
that scan happened to have exactly one finding per file, so only this row was wrong and nothing
looked odd about the rest.

WHERE IT SHOWS. `file_count` feeds three customer-facing places, all of which say "files":

  - the Open Issues table's "Files affected" column
  - the bar chart, whose caption is "Files with open issues per criterion"
  - the chart's text alternative, which says "affects the most files, N of M" — and with N
    counting instances, N can exceed M, so the sentence read aloud to a screen-reader user is
    arithmetically impossible.

Asserted on `_prepare_context` rather than on rendered PDF text: it is the single function both
the shipped Chromium renderer and the WeasyPrint candidate build their numbers from, so one
assertion here covers every renderer, and it needs neither Chromium nor a font stack to run.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

from report_tagged import _prepare_context  # noqa: E402

_META = {"target": "WCAG 2.1 Level AA", "version": "3", "hash": "abc"}
_RUN = {"id": "counts", "completed_at": "2026-09-01T00:00:00", "avg_score": 40}


def _row(ctx: dict, criterion_startswith: str) -> dict:
    """The Open Issues row for a criterion, by its rendered label."""
    matches = [r for r in ctx["open_by_crit"] if r["criterion"].startswith(criterion_startswith)]
    assert len(matches) == 1, f"expected one {criterion_startswith} row, got {matches}"
    return matches[0]


def test_two_findings_of_one_criterion_in_one_file_are_one_file_affected():
    """The minimal shape of the real-scan bug: one file, one criterion, two findings."""
    files = [
        {"file": "a.pdf", "compliant": 0, "score": 40, "status": "done",
         "issues": [{"wcag": "SC_2_4_2", "severity": "MODERATE"},
                    {"wcag": "SC_2_4_2", "severity": "MODERATE"}]},
    ]
    row = _row(_prepare_context(_RUN, files, _META), "2.4.2")
    assert row["file_count"] == 1, (
        f'"Files affected" counted findings, not files: {row["file_count"]} for 1 file')


def test_files_affected_never_exceeds_the_number_of_files_in_the_scan():
    """The invariant that makes the defect visible without knowing the right answer.

    A count of affected files cannot exceed the files assessed. This is what turns the chart's
    alternative text — "affects the most files, N of M" — from a sentence into a contradiction,
    and it is the cheapest thing to assert about any future change to this aggregation.
    """
    files = [
        {"file": "a.pdf", "compliant": 0, "score": 40, "status": "done",
         "issues": [{"wcag": "SC_2_4_2", "severity": "MODERATE"},
                    {"wcag": "SC_2_4_2", "severity": "MODERATE"},
                    {"wcag": "SC_1_3_1", "severity": "CRITICAL"}]},
        {"file": "b.pdf", "compliant": 0, "score": 55, "status": "done",
         "issues": [{"wcag": "SC_2_4_2", "severity": "MODERATE"}]},
    ]
    ctx = _prepare_context(_RUN, files, _META)
    for row in ctx["open_by_crit"]:
        assert row["file_count"] <= ctx["total_files"], (
            f'{row["criterion"]}: {row["file_count"]} files affected out of '
            f'{ctx["total_files"]} assessed')


def test_the_same_criterion_across_different_files_still_counts_each_file():
    """The other direction, so the fix cannot be "always report 1".

    Deduplication has an obvious wrong implementation — collapsing per criterion rather than per
    (criterion, file) — and it passes the two tests above.
    """
    files = [
        {"file": "a.pdf", "compliant": 0, "score": 40, "status": "done",
         "issues": [{"wcag": "SC_2_4_2", "severity": "MODERATE"},
                    {"wcag": "SC_2_4_2", "severity": "MODERATE"}]},
        {"file": "b.pdf", "compliant": 0, "score": 55, "status": "done",
         "issues": [{"wcag": "SC_2_4_2", "severity": "MODERATE"}]},
        {"file": "c.pdf", "compliant": 0, "score": 60, "status": "done",
         "issues": [{"wcag": "SC_2_4_2", "severity": "MODERATE"}]},
    ]
    row = _row(_prepare_context(_RUN, files, _META), "2.4.2")
    assert row["file_count"] == 3, f"three files carry 2.4.2, got {row['file_count']}"


def test_the_bar_chart_is_drawn_from_the_same_corrected_counts():
    """The chart and the table must not disagree.

    `bar_data` is built from the same rows, but it is built separately, and a fix applied to one
    and not the other would leave a report whose picture and table contradict each other — the
    kind of difference a reader notices and cannot resolve.
    """
    files = [
        {"file": "a.pdf", "compliant": 0, "score": 40, "status": "done",
         "issues": [{"wcag": "SC_2_4_2", "severity": "MODERATE"},
                    {"wcag": "SC_2_4_2", "severity": "MODERATE"}]},
        {"file": "b.pdf", "compliant": 0, "score": 55, "status": "done",
         "issues": [{"wcag": "SC_2_4_2", "severity": "MODERATE"}]},
    ]
    ctx = _prepare_context(_RUN, files, _META)
    table = {r["criterion"]: r["file_count"] for r in ctx["open_by_crit"]}
    # The SVG carries each bar's count as its printed value label.
    for criterion, count in table.items():
        assert f">{count}</text>" in ctx["bars_svg"], (
            f"chart has no bar labelled {count} for {criterion}; table and chart disagree")


def test_total_open_still_counts_every_finding():
    """The headline "open issues" number is a count of FINDINGS and must not be deduplicated.

    Pinned because the fix is a change to a loop that increments both, and quietly turning the
    headline into a file count would understate the remediation backlog — the opposite error, in
    the more prominent place.
    """
    files = [
        {"file": "a.pdf", "compliant": 0, "score": 40, "status": "done",
         "issues": [{"wcag": "SC_2_4_2", "severity": "MODERATE"},
                    {"wcag": "SC_2_4_2", "severity": "MODERATE"},
                    {"wcag": "SC_1_3_1", "severity": "CRITICAL"}]},
    ]
    ctx = _prepare_context(_RUN, files, _META)
    assert ctx["total_open"] == 3, f"expected 3 findings, got {ctx['total_open']}"
