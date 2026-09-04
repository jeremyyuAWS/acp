"""Per-scan decision snapshots — route and isolation tests.

Validates the GET /scans/{sid}/decisions and PUT /scans/{sid}/decisions[/{filename}]
endpoints for all four decision kinds (triage, action, assignee, due_date), with
time-travel isolation (each scan has its own independent snapshot) and owner isolation
(a different owner's GET returns 404, not another owner's decisions).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


# ── test client fixture ───────────────────────────────────────────────────────

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


def _seed(s, sid, owner="demo"):
    s.init_scan_run(sid, "local", 0, "2026-09-01T00:00:00Z", "default", "h", owner=owner)


# ── 1. GET returns empty dict for a fresh scan ────────────────────────────────

def test_get_decisions_empty_for_new_scan(client):
    c, s = client
    sid = "ds-empty"
    _seed(s, sid)
    r = c.get(f"/scans/{sid}/decisions")
    assert r.status_code == 200
    assert r.json() == {}


# ── 2. GET returns 404 for an unknown scan ────────────────────────────────────

def test_get_decisions_404_for_unknown_scan(client):
    c, s = client
    r = c.get("/scans/nonexistent-scan/decisions")
    assert r.status_code == 404


# ── 3. Single-file PUT + GET round-trip for all four kinds ───────────────────

@pytest.mark.parametrize("kind,value", [
    ("triage",   "inscope"),
    ("triage",   "na"),
    ("triage",   "defer"),
    ("action",   '{"state":"approved","action":"accept"}'),
    ("assignee", "dev@example.com"),
    ("due_date", "2026-12-31"),
])
def test_single_file_put_get_round_trip(client, kind, value):
    c, s = client
    sid = f"ds-single-{kind}"
    _seed(s, sid)

    r = c.put(f"/scans/{sid}/decisions/report.pdf?kind={kind}", json={"value": value})
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True

    decisions = c.get(f"/scans/{sid}/decisions").json()
    assert "report.pdf" in decisions
    assert decisions["report.pdf"][kind] == value


# ── 4. Single-file PUT with value=null deletes ────────────────────────────────

def test_single_file_delete_via_null_value(client):
    c, s = client
    sid = "ds-del-single"
    _seed(s, sid)

    c.put(f"/scans/{sid}/decisions/report.pdf?kind=triage", json={"value": "inscope"})
    r = c.put(f"/scans/{sid}/decisions/report.pdf?kind=triage", json={"value": None})
    assert r.status_code == 200
    assert r.json().get("deleted") is True

    decisions = c.get(f"/scans/{sid}/decisions").json()
    assert "report.pdf" not in decisions or "triage" not in decisions.get("report.pdf", {})


# ── 5. Batch PUT upserts all four kinds in one call ───────────────────────────

def test_batch_put_upserts_all_kinds(client):
    c, s = client
    sid = "ds-batch"
    _seed(s, sid)

    items = [
        {"file": "a.pdf", "kind": "triage",   "value": "inscope"},
        {"file": "a.pdf", "kind": "action",   "value": '{"state":"open"}'},
        {"file": "a.pdf", "kind": "assignee", "value": "alice@example.com"},
        {"file": "a.pdf", "kind": "due_date", "value": "2026-10-15"},
        {"file": "b.docx", "kind": "triage",  "value": "na"},
    ]
    r = c.put(f"/scans/{sid}/decisions", json={"items": items})
    assert r.status_code == 200
    assert r.json()["saved"] == 5

    decisions = c.get(f"/scans/{sid}/decisions").json()
    assert decisions["a.pdf"]["triage"]   == "inscope"
    assert decisions["a.pdf"]["action"]   == '{"state":"open"}'
    assert decisions["a.pdf"]["assignee"] == "alice@example.com"
    assert decisions["a.pdf"]["due_date"] == "2026-10-15"
    assert decisions["b.docx"]["triage"]  == "na"


# ── 6. Batch PUT with value=null deletes the row ─────────────────────────────

def test_batch_put_null_deletes(client):
    c, s = client
    sid = "ds-batch-del"
    _seed(s, sid)

    c.put(f"/scans/{sid}/decisions",
          json={"items": [{"file": "a.pdf", "kind": "triage", "value": "inscope"},
                          {"file": "a.pdf", "kind": "assignee", "value": "x@example.com"}]})

    r = c.put(f"/scans/{sid}/decisions",
              json={"items": [{"file": "a.pdf", "kind": "triage", "value": None}]})
    assert r.json()["saved"] == 1

    decisions = c.get(f"/scans/{sid}/decisions").json()
    assert "triage" not in decisions.get("a.pdf", {})
    assert decisions["a.pdf"]["assignee"] == "x@example.com"  # untouched


# ── 7. Batch PUT silently skips unknown kinds ─────────────────────────────────

def test_batch_put_skips_unknown_kinds(client):
    c, s = client
    sid = "ds-bad-kind"
    _seed(s, sid)

    r = c.put(f"/scans/{sid}/decisions",
              json={"items": [{"file": "a.pdf", "kind": "bogus", "value": "x"},
                              {"file": "a.pdf", "kind": "triage", "value": "inscope"}]})
    assert r.json()["saved"] == 1  # only valid kind counted
    assert c.get(f"/scans/{sid}/decisions").json()["a.pdf"]["triage"] == "inscope"


# ── 8. Single-file PUT rejects unknown kind (422) ────────────────────────────

def test_single_put_rejects_unknown_kind(client):
    c, s = client
    sid = "ds-422"
    _seed(s, sid)
    r = c.put(f"/scans/{sid}/decisions/a.pdf?kind=bogus", json={"value": "x"})
    assert r.status_code == 422


# ── 9. Upsert: second write for same (scan, file, kind) overwrites first ─────

def test_upsert_overwrites_previous_value(client):
    c, s = client
    sid = "ds-upsert"
    _seed(s, sid)

    c.put(f"/scans/{sid}/decisions/report.pdf?kind=triage", json={"value": "inscope"})
    c.put(f"/scans/{sid}/decisions/report.pdf?kind=triage", json={"value": "defer"})

    decisions = c.get(f"/scans/{sid}/decisions").json()
    assert decisions["report.pdf"]["triage"] == "defer"


# ── 10. Time-travel isolation: two scans have independent snapshots ───────────

def test_scan_decisions_are_isolated_between_scans(client):
    """Decisions saved on scan-A are invisible to scan-B — each scan has its own snapshot."""
    c, s = client
    sid_a, sid_b = "ds-tt-a", "ds-tt-b"
    _seed(s, sid_a)
    _seed(s, sid_b)

    c.put(f"/scans/{sid_a}/decisions/report.pdf?kind=triage", json={"value": "inscope"})
    c.put(f"/scans/{sid_b}/decisions/report.pdf?kind=triage", json={"value": "na"})

    decs_a = c.get(f"/scans/{sid_a}/decisions").json()
    decs_b = c.get(f"/scans/{sid_b}/decisions").json()

    assert decs_a["report.pdf"]["triage"] == "inscope"
    assert decs_b["report.pdf"]["triage"] == "na"

    # changing A does not affect B
    c.put(f"/scans/{sid_a}/decisions/report.pdf?kind=triage", json={"value": None})
    assert c.get(f"/scans/{sid_a}/decisions").json().get("report.pdf", {}).get("triage") is None
    assert c.get(f"/scans/{sid_b}/decisions").json()["report.pdf"]["triage"] == "na"


# ── 11. Multiple files on the same scan are returned together ─────────────────

def test_multiple_files_returned_in_one_get(client):
    c, s = client
    sid = "ds-multi"
    _seed(s, sid)

    files = ["annual.pdf", "q1.xlsx", "memo.docx"]
    for f in files:
        c.put(f"/scans/{sid}/decisions/{f}?kind=triage", json={"value": "inscope"})

    decisions = c.get(f"/scans/{sid}/decisions").json()
    assert set(decisions.keys()) == set(files)
    assert all(decisions[f]["triage"] == "inscope" for f in files)


# ── 12. Store-level owner isolation ──────────────────────────────────────────

def test_store_decisions_are_owner_scoped(isolated_store):
    """get_decisions(owner=X) returns only rows whose owner_email matches X.
    Rows created by alice are invisible to a query with owner='bob'."""
    s = isolated_store
    sid = "ds-owner"
    when = "2026-09-01T00:00:00Z"

    s.save_decision(sid, "a.pdf", "triage",   "inscope",         "alice@example.com", when)
    s.save_decision(sid, "a.pdf", "assignee", "dev@example.com", "alice@example.com", when)
    s.save_decision(sid, "b.pdf", "triage",   "na",              "alice@example.com", when)

    alice_view = s.get_decisions(sid, owner="alice@example.com")
    bob_view   = s.get_decisions(sid, owner="bob@example.com")

    # alice sees her own decisions
    assert alice_view["a.pdf"]["triage"]   == "inscope"
    assert alice_view["a.pdf"]["assignee"] == "dev@example.com"
    assert alice_view["b.pdf"]["triage"]   == "na"
    # bob sees nothing — these rows belong to alice
    assert bob_view == {}


# ── 13. Store-level: decisions survive a scan that has many files ─────────────

def test_store_decisions_across_many_files(isolated_store):
    """Decisions for 50 files all survive and are retrievable in one call."""
    s = isolated_store
    sid = "ds-bulk"
    owner = "owner@example.com"
    when = "2026-09-01T00:00:00Z"

    files = [f"file_{i:03d}.pdf" for i in range(50)]
    for f in files:
        s.save_decision(sid, f, "triage", "inscope", owner, when)

    decisions = s.get_decisions(sid, owner=owner)
    assert len(decisions) == 50
    assert all(decisions[f]["triage"] == "inscope" for f in files)


# ── 14. Store-level: all four kinds coexist on the same (scan, file) ─────────

def test_all_four_kinds_coexist_on_same_file(isolated_store):
    s = isolated_store
    sid = "ds-coexist"
    owner = "owner@example.com"
    when = "2026-09-01T00:00:00Z"

    s.save_decision(sid, "a.pdf", "triage",   "inscope",         owner, when)
    s.save_decision(sid, "a.pdf", "action",   '{"state":"open"}', owner, when)
    s.save_decision(sid, "a.pdf", "assignee", "dev@example.com", owner, when)
    s.save_decision(sid, "a.pdf", "due_date", "2026-12-01",      owner, when)

    d = s.get_decisions(sid, owner=owner)["a.pdf"]
    assert d["triage"]   == "inscope"
    assert d["action"]   == '{"state":"open"}'
    assert d["assignee"] == "dev@example.com"
    assert d["due_date"] == "2026-12-01"
