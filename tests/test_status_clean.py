"""A not-certifiable file with ZERO findings is 'clean', not 'issues'/'open findings'.

The bug: report._status (and the frontend statusOf it mirrors) returned 'issues' for ANY
non-compliant file — including an unscored discover/skip record that has no findings at all.
That put a clean document on the "open findings / Remediate in progress" path with nothing to
remediate. 'issues' must require actual findings; 0-finding non-compliant → 'clean'.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import report  # noqa: E402


def _f(**kw):
    base = {"status": "analysed", "compliant": 0, "issues": []}
    base.update(kw)
    return base


def test_zero_findings_not_compliant_is_clean_not_issues():
    # a discovered/skipped record, no findings, not yet certified
    assert report._status(_f(status="discovered", compliant=0, issues=[])) == "clean"
    assert report._status(_f(status="skipped", compliant=0, issues=[])) == "clean"
    assert report._status(_f(status="analysed", compliant=0, issues=[])) == "clean"


def test_findings_present_is_issues():
    assert report._status(_f(compliant=0, issues=[{"ruleId": "X", "wcag": "1.1.1"}])) == "issues"


def test_compliant_is_certifiable_even_with_nonblocking_findings():
    # a certifiable file can carry findings that were cleared / non-blocking
    assert report._status(_f(compliant=1, issues=[{"ruleId": "X"}])) == "certifiable"
    assert report._status(_f(compliant=1, issues=[])) == "certifiable"


def test_error_and_uncertain_take_precedence():
    assert report._status(_f(status="error", compliant=0, issues=[])) == "unanalysable"
    assert report._status(_f(status="uncertain", compliant=0, issues=[])) == "uncertain"


def test_clean_has_label_and_color_so_the_donut_and_legend_render():
    assert report.STATUS_LABEL["clean"] == "no findings"
    assert "clean" in report.STATUS_COLOR
