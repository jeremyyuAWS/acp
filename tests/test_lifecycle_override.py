"""POST /scans/{sid}/files/{file}/lifecycle-override — lifecycle rules #8: a human's reasoned
disagreement with a rule's Archive/Delete Candidate recommendation for ONE file.

Deliberately does not touch lifecycle_status/lifecycle_rule_id/lifecycle_reason: those record
what the RULE said, and stay put so DiscoveryResults' bucket reconciliation stays a true
partition of what the rule pass produced. The override is itself only a recommendation, recorded
alongside — a reason is required, and it lands in both audit tables (disposition_audit and
decision_log) the same dual-write convention every other disposition route follows.
"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

OWNER = "jeremyyu.movate@gmail.com"


@pytest.fixture()
def client(monkeypatch, isolated_store):
    import core
    from fastapi.testclient import TestClient
    from app import app
    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "test-client-id", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    monkeypatch.setattr(core, "OWNER_EMAIL", OWNER, raising=False)
    monkeypatch.setattr(core, "verify_gis_token", lambda tok: tok or None)
    monkeypatch.setattr(core, "email_allowed", lambda e: e == OWNER)
    client = TestClient(app)
    client.headers.update({"Authorization": f"Bearer {OWNER}"})
    return client, isolated_store


def _seed(st, sid, file, *, status="Archive Candidate", rule_id="r-42",
         reason="matched archive rule 'stale finance'", owner=OWNER):
    st.save_scan({"_scan_id": sid, "started_at": "2026-08-18T10:00:00+00:00",
                 "completed_at": "2026-08-18T10:05:00+00:00", "source": "drive", "owner": owner,
                 "rubric": {"name": "wcag-aa", "hash": "h"}, "scope": {"kind": "drive"},
                 "summary": {"files": 0, "certifiable": 0, "uncertain": 0, "error": 0, "avg_score": 0},
                 "files": []})
    st.add_inventory(sid, [{"file": file, "doc_class": "pdf"}])
    if status:
        st.set_lifecycle_status(sid, file, status, rule_id=rule_id, reason=reason)


# ── store ────────────────────────────────────────────────────────────────────────────────────

def test_override_records_reason_actor_and_timestamp(isolated_store):
    st = isolated_store
    _seed(st, "s1", "Finance/old.pdf")
    prior = st.override_lifecycle("s1", "Finance/old.pdf", reason="legal hold pending", actor=OWNER)
    assert prior == {"lifecycle_status": "Archive Candidate", "lifecycle_rule_id": "r-42"}
    row = st.get_lifecycle_status("s1", "Finance/old.pdf")
    assert row["lifecycle_override_reason"] == "legal hold pending"
    assert row["lifecycle_overridden_by"] == OWNER
    assert row["lifecycle_overridden_at"]
    # The rule's own record is untouched — this is an annotation, not a status change.
    assert row["lifecycle_status"] == "Archive Candidate"
    assert row["lifecycle_rule_id"] == "r-42"


def test_override_refused_when_file_carries_no_candidate_status(isolated_store):
    st = isolated_store
    _seed(st, "s1", "Finance/active.pdf", status=None)   # stays 'Active'
    assert st.override_lifecycle("s1", "Finance/active.pdf", reason="x", actor=OWNER) is None
    row = st.get_lifecycle_status("s1", "Finance/active.pdf")
    assert row["lifecycle_override_reason"] is None


def test_override_refused_for_unknown_file(isolated_store):
    st = isolated_store
    _seed(st, "s1", "Finance/old.pdf")
    assert st.override_lifecycle("s1", "nope.pdf", reason="x", actor=OWNER) is None


# ── route ────────────────────────────────────────────────────────────────────────────────────

def test_route_requires_a_nonblank_reason(client):
    c, st = client
    _seed(st, "s1", "Finance/old.pdf")
    r = c.post("/scans/s1/files/Finance/old.pdf/lifecycle-override", json={"reason": "   "})
    assert r.status_code == 422
    r2 = c.post("/scans/s1/files/Finance/old.pdf/lifecycle-override", json={"reason": ""})
    assert r2.status_code == 422


def test_route_409s_a_file_with_no_recommendation_to_override(client):
    c, st = client
    _seed(st, "s1", "Finance/active.pdf", status=None)
    r = c.post("/scans/s1/files/Finance/active.pdf/lifecycle-override", json={"reason": "keep it"})
    assert r.status_code == 409


def test_route_404s_a_scan_the_caller_does_not_own(client):
    c, st = client
    _seed(st, "s1", "Finance/old.pdf", owner="someone.else@example.com")
    r = c.post("/scans/s1/files/Finance/old.pdf/lifecycle-override", json={"reason": "keep it"})
    assert r.status_code == 404


def test_route_writes_both_audit_tables_and_returns_the_updated_row(client):
    c, st = client
    _seed(st, "s1", "Finance/old.pdf", rule_id="r-42", reason="matched archive rule 'stale finance'")
    r = c.post("/scans/s1/files/Finance/old.pdf/lifecycle-override",
              json={"reason": "under active legal hold"})
    assert r.status_code == 200
    body = r.json()
    assert body["lifecycle_override_reason"] == "under active legal hold"
    assert body["lifecycle_overridden_by"] == OWNER
    assert body["lifecycle_status"] == "Archive Candidate"   # unchanged — an annotation, not an action

    audit = st.list_disposition_audit(owner=OWNER)
    hit = [a for a in audit if a["doc_id"] == "scan:s1:Finance/old.pdf"]
    assert len(hit) == 1
    assert hit[0]["policy_id"] == "r-42"
    assert hit[0]["result"] == "overridden"
    assert hit[0]["detail"] == "under active legal hold"

    decisions = st.list_decisions(scan_id="s1")
    dec = [d for d in decisions if d["action"] == "disposition.file_overridden"]
    assert len(dec) == 1
    assert dec[0]["file"] == "Finance/old.pdf"
    assert dec[0]["rule_id"] == "r-42"
    assert dec[0]["detail"] == "under active legal hold"
    assert dec[0]["actor"] == OWNER


def test_override_reaches_the_scan_inventory_endpoint(client):
    """The whole point: GET /scans/{id}/inventory is what the frontend actually reads (via
    getScanInventory / mergeLifecycle), so the override must round-trip through it, not just
    through get_lifecycle_status."""
    c, st = client
    _seed(st, "s1", "Finance/old.pdf")
    c.post("/scans/s1/files/Finance/old.pdf/lifecycle-override", json={"reason": "keep — audit in progress"})
    r = c.get("/scans/s1/inventory")
    row = next(x for x in r.json()["rows"] if x["file"] == "Finance/old.pdf")
    assert row["lifecycle_override_reason"] == "keep — audit in progress"
    assert row["lifecycle_overridden_by"] == OWNER
