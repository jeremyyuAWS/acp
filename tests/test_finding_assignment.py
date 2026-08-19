"""Per-file assignment persistence — the backend foundation for the "Assigned to me" inbox filter.

A reviewer can assign a finding (a file, in the inbox's terms) to a teammate. That assignment is a
per-file decision axis exactly like triage and action: it rides `scan_decisions` on its
`(scan_id, file, kind)` PK with `kind='assignee'` and `value=<assignee email>`, so it is
owner-scoped for free, one file carries at most one assignee, and a re-assign upserts the row. No
new table.

`assessment_policy.assignments` and `files_assigned_to` are the pure read helpers the frontend
inbox filter reads — the mirror of `selected_documents`. This proves the round-trip through a real
store and the helper semantics.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import assessment_policy as ap  # noqa: E402


# ── the pure semantics — mirrors the frontend "Assigned to me" filter ──
def test_assignments_semantics():
    # no decisions ⇒ no assignments (empty dict, never None — this is a plain map, not a scope)
    assert ap.assignments(None) == {}
    assert ap.assignments({}) == {}
    # a triage/action decision is not an assignment
    assert ap.assignments({"a.docx": {"triage": "inscope"}, "b.pdf": {"action": "approved"}}) == {}
    # an assignee decision yields {file: email}; files without one are simply absent
    decisions = {
        "a.docx": {"triage": "inscope", "assignee": "dev@example.com"},
        "b.pdf": {"assignee": "qa@example.com"},
        "c.pptx": {"triage": "na"},
        "d.docx": {"assignee": ""},          # cleared/blank ⇒ not assigned
    }
    assert ap.assignments(decisions) == {"a.docx": "dev@example.com", "b.pdf": "qa@example.com"}


def test_files_assigned_to_semantics():
    decisions = {
        "a.docx": {"assignee": "dev@example.com"},
        "b.pdf": {"assignee": "qa@example.com"},
        "c.pptx": {"assignee": "dev@example.com"},
    }
    assert ap.files_assigned_to(decisions, "dev@example.com") == frozenset({"a.docx", "c.pptx"})
    assert ap.files_assigned_to(decisions, "qa@example.com") == frozenset({"b.pdf"})
    # nobody assigned to an unknown reviewer
    assert ap.files_assigned_to(decisions, "nobody@example.com") == frozenset()
    # a signed-out / unknown caller matches NOTHING, never the whole estate
    assert ap.files_assigned_to(decisions, None) == frozenset()
    assert ap.files_assigned_to(decisions, "") == frozenset()
    assert ap.files_assigned_to(None, "dev@example.com") == frozenset()


# ── the round-trip, end to end over a real store ──
def test_assignment_round_trips_through_scan_decisions(isolated_store):
    s = isolated_store
    sid = "assign1"
    owner = "owner@example.com"
    when = "2026-08-19T00:00:00Z"

    # no assignments yet
    assert ap.assignments(s.get_decisions(sid, owner=owner)) == {}

    # assign two files, reusing the existing decisions persistence (kind='assignee')
    s.save_decision(sid, "a.docx", "assignee", "dev@example.com", owner, when)
    s.save_decision(sid, "b.pdf", "assignee", "qa@example.com", owner, when)

    decisions = s.get_decisions(sid, owner=owner)
    assert ap.assignments(decisions) == {"a.docx": "dev@example.com", "b.pdf": "qa@example.com"}
    assert ap.files_assigned_to(decisions, "dev@example.com") == frozenset({"a.docx"})

    # re-assign upserts the same row (one assignee per file), never a second row
    s.save_decision(sid, "a.docx", "assignee", "qa@example.com", owner, "2026-08-19T01:00:00Z")
    decisions = s.get_decisions(sid, owner=owner)
    assert ap.files_assigned_to(decisions, "qa@example.com") == frozenset({"a.docx", "b.pdf"})
    assert ap.files_assigned_to(decisions, "dev@example.com") == frozenset()

    # clearing an assignment deletes the row
    s.delete_decision(sid, "a.docx", "assignee")
    decisions = s.get_decisions(sid, owner=owner)
    assert ap.assignments(decisions) == {"b.pdf": "qa@example.com"}


def test_assignment_is_owner_scoped(isolated_store):
    """Assignments live on the same owner-scoped rows as triage/action: another owner's read of the
    same scan never sees them."""
    s = isolated_store
    sid = "assign2"
    s.save_decision(sid, "a.docx", "assignee", "dev@example.com", "alice@example.com", "2026-08-19T00:00:00Z")

    assert ap.assignments(s.get_decisions(sid, owner="alice@example.com")) == {"a.docx": "dev@example.com"}
    assert ap.assignments(s.get_decisions(sid, owner="bob@example.com")) == {}


def test_assignment_coexists_with_triage_on_the_same_file(isolated_store):
    """assignee and triage are different kinds on the same (scan,file), so a file can be both
    in-scope and assigned without either clobbering the other."""
    s = isolated_store
    sid = "assign3"
    owner = "owner@example.com"
    s.save_decision(sid, "a.docx", "triage", "inscope", owner, "2026-08-19T00:00:00Z")
    s.save_decision(sid, "a.docx", "assignee", "dev@example.com", owner, "2026-08-19T00:00:00Z")

    decisions = s.get_decisions(sid, owner=owner)
    assert ap.selected_documents(decisions) == frozenset({"a.docx"})
    assert ap.assignments(decisions) == {"a.docx": "dev@example.com"}


# ── the existing decisions endpoints accept kind='assignee' (no new route) ──
@pytest.fixture()
def client(monkeypatch, isolated_store):
    import core
    from fastapi.testclient import TestClient
    from app import app
    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    monkeypatch.setattr(core, "OWNER_EMAIL", "", raising=False)
    return TestClient(app), isolated_store


def _seed_scan(s, sid):
    s.init_scan_run(sid, "local", 0, "2026-08-19T00:00:00Z", "default", "h", owner="demo")


def test_put_decision_endpoint_accepts_assignee(client):
    c, s = client
    sid = "assign-ep1"
    _seed_scan(s, sid)

    # single-file route: kind=assignee is now a valid Query kind (was 422 before)
    r = c.put(f"/scans/{sid}/decisions/a.docx?kind=assignee", json={"value": "dev@example.com"})
    assert r.status_code == 200, r.text
    assert ap.assignments(c.get(f"/scans/{sid}/decisions").json()) == {"a.docx": "dev@example.com"}

    # batch route: an assignee item is upserted, not skipped
    r = c.put(f"/scans/{sid}/decisions",
              json={"items": [{"file": "b.pdf", "kind": "assignee", "value": "qa@example.com"}]})
    assert r.json()["saved"] == 1
    assert ap.files_assigned_to(c.get(f"/scans/{sid}/decisions").json(), "qa@example.com") == frozenset({"b.pdf"})

    # null value clears the assignment
    c.put(f"/scans/{sid}/decisions/a.docx?kind=assignee", json={"value": None})
    assert ap.assignments(c.get(f"/scans/{sid}/decisions").json()) == {"b.pdf": "qa@example.com"}


def test_put_decision_endpoint_still_rejects_unknown_kind(client):
    c, s = client
    sid = "assign-ep2"
    _seed_scan(s, sid)
    # the allow-list widened by exactly one kind; a bogus kind is still a 422 on the path route
    assert c.put(f"/scans/{sid}/decisions/a.docx?kind=bogus", json={"value": "x"}).status_code == 422
    # …and silently skipped in the batch route
    r = c.put(f"/scans/{sid}/decisions",
              json={"items": [{"file": "a.docx", "kind": "bogus", "value": "x"}]})
    assert r.json()["saved"] == 0
