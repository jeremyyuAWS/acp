"""R19 · Due dates on a finding's document.

A due date is the deadline half of "who does this, by when" — the sibling of the R17 assignee axis.
It rides the generic scan_decisions store on kind='due_date' (no new persistence), so it is
owner-scoped for free and one file carries at most one due date. These tests pin the extraction
helper, the overdue comparison, that the decision routes accept the new kind, and the frontend
wiring.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import assessment_policy as ap   # noqa: E402


def test_due_dates_reads_only_that_kind():
    decisions = {
        "a.pdf": {"assignee": "deva@acp.io", "due_date": "2026-09-01", "triage": "inscope"},
        "b.docx": {"assignee": "j@acp.io"},                 # assigned, no due date
        "c.pptx": {"due_date": "2026-08-15"},               # dated, unassigned
        "d.pdf": {"triage": "na"},                          # neither
    }
    assert ap.due_dates(decisions) == {"a.pdf": "2026-09-01", "c.pptx": "2026-08-15"}


def test_due_dates_empty_inputs():
    assert ap.due_dates(None) == {}
    assert ap.due_dates({}) == {}
    assert ap.due_dates({"x": {"due_date": ""}}) == {}      # cleared value is absent, not ""


def test_overdue_is_strictly_before_today():
    decisions = {
        "past.pdf": {"due_date": "2026-08-10"},
        "today.pdf": {"due_date": "2026-08-20"},            # due today is NOT overdue
        "future.pdf": {"due_date": "2026-08-25"},
    }
    assert ap.overdue_files(decisions, "2026-08-20") == frozenset({"past.pdf"})


def test_overdue_handles_full_iso_timestamps():
    decisions = {"a.pdf": {"due_date": "2026-08-19T23:59:00+00:00"}}
    assert ap.overdue_files(decisions, "2026-08-20T09:00:00+00:00") == frozenset({"a.pdf"})


def test_overdue_empty_today_matches_nothing():
    # A missing "today" must never render every dated file overdue.
    assert ap.overdue_files({"a.pdf": {"due_date": "2020-01-01"}}, "") == frozenset()


def test_due_date_persists_through_the_store(isolated_store):
    s = isolated_store
    s.save_decision("s1", "a.pdf", "due_date", "2026-09-01", "owner@acp.io", "2026-08-20T00:00:00Z")
    s.save_decision("s1", "a.pdf", "assignee", "deva@acp.io", "owner@acp.io", "2026-08-20T00:00:00Z")
    d = s.get_decisions("s1", owner="owner@acp.io")
    assert ap.due_dates(d) == {"a.pdf": "2026-09-01"}       # rides alongside the assignee, one row each
    assert ap.assignments(d) == {"a.pdf": "deva@acp.io"}
    # clearing deletes just the due date, leaving the assignee
    s.delete_decision("s1", "a.pdf", "due_date")
    d2 = s.get_decisions("s1", owner="owner@acp.io")
    assert ap.due_dates(d2) == {} and ap.assignments(d2) == {"a.pdf": "deva@acp.io"}


def test_routes_and_frontend_wiring():
    root = Path(__file__).resolve().parent.parent
    scans = (root / "api" / "routes" / "scans.py").read_text()
    assert '("triage", "action", "assignee", "due_date")' in scans          # batch route
    assert "triage|action|assignee|due_date" in scans                       # PUT route pattern
    dd = (root / "frontend" / "src" / "DueDate.jsx").read_text()
    assert "due_date" in dd and "saveDecision" in dd
    rem = (root / "frontend" / "src" / "Remediate.jsx").read_text()
    assert "DueDate" in rem
