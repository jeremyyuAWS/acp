"""What a document's verdict may claim — and specifically, that it never claims "clean" about a
document nobody measured.

Two rules, layered, both learned from production:

1. 'issues' means OPEN FINDINGS. It used to be returned for ANY non-compliant file, which put
   zero-finding documents on the "open findings / Remediate in progress" path with nothing to
   remediate.

2. 'clean' means ASSESSED AND CLEAR. It used to be the final fall-through, so a document with no
   score — never opened, never assessed — was reported as having no findings. Seen live
   2026-07-30 on v2026.7.29.8: two Google Drive spreadsheets rendered
   "status: clean · score: n/a · findings: clean" in the file inventory while the drawer for one
   of them, reading the same scan's rule traces, reported "1 issue needs remediation".

A null score is a sound marker for "not measured", not a guess at one: Rubric.assess
(scripts/rubric.py) returns score=None if and only if it returns Status.ERROR, which _status
classifies as 'unanalysable' before reaching the clean/not-assessed decision. So every ANALYSED
or UNCERTAIN record carries a number, and a scoreless row is one nobody scored.

This is the certification PDF. It is the worst possible surface on which to print a pass that
nobody measured, which is why the mirror is pinned against the frontend's copy as well.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import report  # noqa: E402

DOC_STATUS_JS = Path(__file__).resolve().parent.parent / "frontend" / "src" / "docStatus.js"


def _f(**kw):
    # NOTE: no default score — each test states whether this document was scored, because that
    # is the fact under test.
    base = {"status": "analysed", "compliant": 0, "issues": []}
    base.update(kw)
    return base


def test_scored_zero_findings_not_compliant_is_clean_not_issues():
    # Opened, scored, failed no rule — 'clean' is a claim the data supports.
    assert report._status(_f(status="analysed", compliant=0, issues=[], score=100)) == "clean"
    assert report._status(_f(status="analysed", compliant=0, issues=[], score=0)) == "clean"


def test_findings_present_is_issues():
    assert report._status(_f(compliant=0, issues=[{"ruleId": "X", "wcag": "1.1.1"}], score=55)) == "issues"


def test_compliant_is_certifiable_even_with_nonblocking_findings():
    # a certifiable file can carry findings that were cleared / non-blocking
    assert report._status(_f(compliant=1, issues=[{"ruleId": "X"}], score=90)) == "certifiable"
    assert report._status(_f(compliant=1, issues=[], score=100)) == "certifiable"


def test_error_and_uncertain_take_precedence():
    # Both also have no score. They were OPENED — reporting them as "nobody looked" would lose
    # the fact that ACP tried and the document defeated it.
    assert report._status(_f(status="error", compliant=0, issues=[], score=None)) == "unanalysable"
    assert report._status(_f(status="uncertain", compliant=0, issues=[], score=None)) == "uncertain"


def test_an_unscored_document_is_never_clean():
    for f in (
        _f(status="discovered", compliant=0, issues=[], score=None),   # ADR 0020 inventory row
        _f(status="skipped", compliant=0, issues=[], score=None),      # shadow-skip record
        _f(status="analysed", compliant=0, issues=[], score=None),     # saved without a score
        _f(status="analysed", compliant=0, issues=[]),                 # score absent entirely
    ):
        assert report._status(f) != "clean", f
        assert report._status(f) == report.NOT_ASSESSED, f


def test_the_unscored_state_has_a_label_and_colour_of_its_own():
    assert report.STATUS_LABEL["clean"] == "no findings"
    assert report.STATUS_LABEL[report.NOT_ASSESSED] == "not assessed"
    # Whatever it says, it must not be an affirmative claim about findings.
    assert not re.search(r"no findings|clean|clear|pass",
                         report.STATUS_LABEL[report.NOT_ASSESSED], re.I)
    assert report.NOT_ASSESSED in report.STATUS_COLOR
    assert report.STATUS_COLOR[report.NOT_ASSESSED] != report.STATUS_COLOR["clean"]
    assert report.STATUS_COLOR[report.NOT_ASSESSED] != report.STATUS_COLOR["certifiable"]


def test_the_frontend_and_the_pdf_use_the_same_token():
    """A mirror that drifts is worse than no mirror: the app would call a document one thing and
    the certified PDF another, from the same row."""
    src = DOC_STATUS_JS.read_text()
    m = re.search(r"export const NOT_ASSESSED = '([^']+)'", src)
    assert m, "docStatus.js no longer exports NOT_ASSESSED"
    assert m.group(1) == report.NOT_ASSESSED


def test_the_frontend_verdict_still_orders_the_score_check_last():
    """The Python and JS derivations must agree clause for clause, not just on this one input.
    Pinned as source shape because the two languages cannot share the function."""
    src = DOC_STATUS_JS.read_text()
    body = re.search(r"export const statusOf = \(f\) => \((.*?)\n\)", src, re.S).group(1)
    # error → uncertain → compliant → issues → score: the same precedence _status uses above.
    # The score clause LAST is what keeps 'error'/'uncertain' (also scoreless) out of it.
    clauses = ["f.status === 'error'", "f.status === 'uncertain'", "f.compliant",
               "f.issues && f.issues.length", "f.score == null"]
    positions = [body.index(c) for c in clauses]
    assert positions == sorted(positions), f"statusOf clause order changed: {body}"


def test_the_executive_verdict_never_certifies_an_unassessed_estate():
    """The reported estate, as the PDF's summary saw it: two documents, neither scored. The
    else-branch used to fire (no issues, no uncertain, no unanalysable) and print
    "All 2 analysed document(s) meet WCAG 2.1 AA ... and are certifiable"."""
    counts = {}
    for f in _REPORTED_ESTATE:
        counts[report._status(f)] = counts.get(report._status(f), 0) + 1

    assert counts == {report.NOT_ASSESSED: 2}
    # No count that a "…are certifiable" sentence keys on may be non-zero here.
    assert not counts.get("clean")
    assert not counts.get("certifiable")


# The two Drive spreadsheets from the 2026-07-30 report, in the row shape store.get_scan returns
# for a document that was listed but never opened (the ADR 0020 inventory fallback).
_REPORTED_ESTATE = [
    {"file": "acme-fy2026-summary.xlsx", "engine": "inventory", "status": "discovered",
     "score": None, "compliant": 0, "skipped_rules": 0, "issues": [], "remediated_at": None,
     "drive_write_url": None, "acp_stamped": None, "size_kb": 88, "pages": None, "sheets": None},
    {"file": "assessment-applicability-matrix-28JUL-Final.xlsx", "engine": "inventory",
     "status": "discovered", "score": None, "compliant": 0, "skipped_rules": 0, "issues": [],
     "remediated_at": None, "drive_write_url": None, "acp_stamped": None, "size_kb": 132,
     "pages": None, "sheets": None},
]


def _flat(pdf: bytes) -> str:
    import io

    from pypdf import PdfReader
    txt = "".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(pdf)).pages)
    return re.sub(r"\s+", " ", txt)


def test_the_certification_pdf_makes_no_conformance_claim_about_unassessed_documents(
        isolated_store, monkeypatch):
    """End to end over the real builder, because this is the document a customer files. The unit
    tests above pin the verdict; this pins what actually gets printed on the page."""
    import core
    from report import build_report
    monkeypatch.setattr(core, "store", isolated_store)

    run = {"id": "scan-unassessed", "completed_at": "2026-07-30T09:00:00",
           "avg_score": None, "owner_email": None}
    t = _flat(build_report(run, _REPORTED_ESTATE, {"target": "WCAG 2.1 AA", "version": "1.2",
                                                  "hash": "deadbeef"}))

    # The sentence that used to be printed, verbatim in shape: an "All N … are certifiable"
    # claim over documents nobody opened.
    assert not re.search(r"All\s*2\s*(analysed|assessed) document\(s\) meet", t)
    # The decision card is three-valued and must not read green here.
    assert "NOT CERTIFIABLE" in t
    assert "0 of 2" in t
    # And the gap is stated rather than left for the reader to infer from a blank score column.
    assert "never assessed" in t
    assert "makes no conformance claim" in t
    # The per-document row says so too, instead of "clean".
    assert "not assessed" in t
