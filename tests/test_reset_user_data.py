"""Self-service reset: store.reset_user_data(owner_email) clears ONE user's scans and everything
tied to them, without touching another user's data — the sibling of the global admin
reset_analytics(), scoped so two people testing concurrently never clear each other's work.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


def _scan(s, owner, scan_id_hint=""):
    report = {"started_at": "2026-08-21T10:00:00+00:00", "completed_at": "2026-08-21T10:01:00+00:00",
              "source": "drive", "owner": owner,
              "rubric": {"name": "WCAG 2.1 AA", "hash": "abc123"},
              "summary": {"files": 1, "certifiable": 1, "uncertain": 0, "error": 0, "avg_score": 90},
              "files": [{"file": f"{scan_id_hint}deck.pptx", "engine": "office", "status": "PASS",
                         "score": 90, "compliant": 1, "skipped_rules": 0, "issues": []}]}
    return s.save_scan(report)


def test_clears_only_the_target_owners_scan(isolated_store):
    s = isolated_store
    sid_a = _scan(s, "jeremy@acp.io", "a-")
    sid_b = _scan(s, "deva@acp.io", "b-")

    result = s.reset_user_data("jeremy@acp.io")

    assert s.get_scan(sid_a, owner="jeremy@acp.io") is None      # jeremy's scan is gone
    assert s.get_scan(sid_b, owner="deva@acp.io") is not None    # deva's scan survives
    assert "scan_runs" in result["cleared_tables"]
    assert result["owner"] == "jeremy@acp.io"


def test_clears_dependent_scan_id_tables_for_that_owner_only(isolated_store):
    s = isolated_store
    sid_a = _scan(s, "jeremy@acp.io", "a-")
    sid_b = _scan(s, "deva@acp.io", "b-")
    s.record_hitl_event(sid_a, "a-deck.pptx", "1.1.1", "i1", "approve", edited=False)
    s.record_hitl_event(sid_b, "b-deck.pptx", "1.1.1", "i2", "approve", edited=False)
    s.add_finding_comment(sid_a, "a-deck.pptx||1.1.1||", "jeremy@acp.io", "note on my scan")
    s.add_finding_comment(sid_b, "b-deck.pptx||1.1.1||", "deva@acp.io", "note on deva's scan")

    s.reset_user_data("jeremy@acp.io")

    assert s.document_timeline(sid_a, "a-deck.pptx") == []                 # jeremy's hitl event gone
    assert s.list_finding_comments(sid_a, "a-deck.pptx||1.1.1||") == []    # jeremy's comment gone
    assert s.list_finding_comments(sid_b, "b-deck.pptx||1.1.1||") != []    # deva's comment survives


def test_cross_attribution_removes_a_teammates_comment_on_my_scan(isolated_store):
    """Resetting my scan removes a comment a teammate left ON it too — the scan they were
    commenting about no longer exists. This is 'delete my scan and everything about it', not
    'delete only what I personally authored'."""
    s = isolated_store
    sid = _scan(s, "jeremy@acp.io", "a-")
    s.add_finding_comment(sid, "a-deck.pptx||1.1.1||", "deva@acp.io", "deva's comment on jeremy's scan")

    s.reset_user_data("jeremy@acp.io")

    assert s.list_finding_comments(sid, "a-deck.pptx||1.1.1||") == []


def test_inventory_is_never_touched(isolated_store):
    """`inventory` has no owner concept (a global path-dedup index) — excluded from the per-user
    reset entirely, unlike the global reset_analytics()."""
    s = isolated_store
    with s._db.cursor() as cur:
        s._db.execute(cur, "INSERT INTO inventory(file, first_seen, last_seen, last_status, last_score) "
                           "VALUES(%s,%s,%s,%s,%s)", ("some/path.docx", "2026-08-21", "2026-08-21", "PASS", 90))
    _scan(s, "jeremy@acp.io")
    with s._db.cursor() as cur:
        s._db.execute(cur, "SELECT COUNT(*) AS n FROM inventory", ())
        before = s._db.fetchall(cur)[0]["n"]

    result = s.reset_user_data("jeremy@acp.io")

    assert "inventory" not in result["cleared_tables"]
    with s._db.cursor() as cur:
        s._db.execute(cur, "SELECT COUNT(*) AS n FROM inventory", ())
        assert s._db.fetchall(cur)[0]["n"] == before      # unchanged by the reset, whatever it was


def test_decision_log_is_not_deleted_and_caller_can_append_to_it(isolated_store):
    """decision_log is documented as immutable/append-only — reset_user_data must not delete rows
    from it (unlike reset_analytics, which does — an existing inconsistency not repeated here)."""
    s = isolated_store
    _scan(s, "jeremy@acp.io")
    s.log_decision("jeremy@acp.io", "some_prior_action", detail="pre-existing row")

    result = s.reset_user_data("jeremy@acp.io")
    assert "decision_log" not in result["cleared_tables"]

    # The route appends one row after calling this — simulate that here and confirm both survive.
    s.log_decision("jeremy@acp.io", "reset_user_data", detail="tables=20")
    rows = s.list_decisions()
    assert len(rows) == 2


def test_doc_id_keyed_tables_scoped_via_documents_owner(isolated_store):
    """disposition_audit / remediation_state key on doc_id, not scan_id — scoped via a join
    through `documents.owner_email`, not through scan_runs."""
    s = isolated_store
    s.upsert_document("doc-a", source="drive", path="a.pptx", content_hash="h1", owner="Jeremy Yu",
                      created_at="2026-08-21T00:00:00Z", last_seen="2026-08-21T00:00:00Z",
                      triage_score=0, triage_rationale="", owner_email="jeremy@acp.io")
    s.upsert_document("doc-b", source="drive", path="b.pptx", content_hash="h2", owner="Deva",
                      created_at="2026-08-21T00:00:00Z", last_seen="2026-08-21T00:00:00Z",
                      triage_score=0, triage_rationale="", owner_email="deva@acp.io")
    with s._db.cursor() as cur:
        s._db.execute(cur,
            "INSERT INTO disposition_audit(id, ts, doc_id, action) VALUES(%s,%s,%s,%s)",
            ("da1", "2026-08-21T00:00:00Z", "doc-a", "archive"))
        s._db.execute(cur,
            "INSERT INTO disposition_audit(id, ts, doc_id, action) VALUES(%s,%s,%s,%s)",
            ("da2", "2026-08-21T00:00:00Z", "doc-b", "archive"))

    s.reset_user_data("jeremy@acp.io")

    with s._db.cursor() as cur:
        s._db.execute(cur, "SELECT doc_id FROM disposition_audit", ())
        remaining = {r["doc_id"] for r in s._db.fetchall(cur)}
    assert remaining == {"doc-b"}          # jeremy's row gone, deva's survives
    with s._db.cursor() as cur:
        s._db.execute(cur, "SELECT doc_id FROM documents", ())
        remaining_docs = {r["doc_id"] for r in s._db.fetchall(cur)}
    assert remaining_docs == {"doc-b"}


def test_org_memory_scoped_by_org_field(isolated_store):
    s = isolated_store
    with s._db.cursor() as cur:
        s._db.execute(cur, "INSERT INTO org_memory(id, org, kind, guidance, status) VALUES(%s,%s,%s,%s,%s)",
                      ("m1", "jeremy@acp.io", "note", "some guidance", "active"))
        s._db.execute(cur, "INSERT INTO org_memory(id, org, kind, guidance, status) VALUES(%s,%s,%s,%s,%s)",
                      ("m2", "deva@acp.io", "note", "some guidance", "active"))

    s.reset_user_data("jeremy@acp.io")

    with s._db.cursor() as cur:
        s._db.execute(cur, "SELECT org FROM org_memory", ())
        remaining = {r["org"] for r in s._db.fetchall(cur)}
    assert remaining == {"deva@acp.io"}


def test_empty_for_an_owner_with_no_scans(isolated_store):
    s = isolated_store
    result = s.reset_user_data("nobody@acp.io")
    assert result["owner"] == "nobody@acp.io"
    assert len(result["cleared_tables"]) > 0     # still runs every DELETE, just affects 0 rows


def test_route_and_frontend_wiring():
    root = Path(__file__).resolve().parent.parent
    system = (root / "api" / "routes" / "system.py").read_text()
    assert '@router.post("/me/reset-data")' in system
    assert "reset_user_data" in system
    assert "confirmation required" in system
    api = (root / "frontend" / "src" / "api.js").read_text()
    assert "resetMyData" in api and "/me/reset-data" in api
    settings = (root / "frontend" / "src" / "Settings.jsx").read_text()
    assert "ResetMyData" in settings and "'mydata'" in settings
