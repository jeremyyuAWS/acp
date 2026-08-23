"""GET /disposition/audit?doc_id=... — the audit table has always been queryable by result and
policy_id, but not by the one thing a person actually has when they ask "why does this file show
Archive Candidate": the file itself. This closes that gap.

`doc_id` follows the "scan:<scan_id>:<file>" convention Discover's evaluator
(handlers._evaluate_discover_lifecycle_rules) and the per-file override route
(scans.py's lifecycle-override) already write — so a caller with a (scan_id, file) pair can
construct it without a lookup, and this test seeds rows the same way those callers would.
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


def test_doc_id_narrows_the_audit_to_one_document(client):
    c, st = client
    target = "scan:s1:Finance/stale.pdf"
    other = "scan:s1:Finance/other.pdf"
    # Two rules tagged the target file over time (a later rule can re-evaluate what an earlier
    # one already decided); one row belongs to a different file entirely.
    st.create_disposition_audit("a1", doc_id=target, policy_id="r-archive",
        action="tag", result="applied", detail="matched 'stale finance'", owner_email=OWNER)
    st.create_disposition_audit("a2", doc_id=target, policy_id="r-delete",
        action="tag", result="applied", detail="matched 'aged, no legal hold'", owner_email=OWNER)
    st.create_disposition_audit("a3", doc_id=other, policy_id="r-archive",
        action="tag", result="applied", detail="matched 'stale finance'", owner_email=OWNER)

    resp = c.get("/disposition/audit", params={"doc_id": target})
    assert resp.status_code == 200
    rows = resp.json()
    assert {r["id"] for r in rows} == {"a1", "a2"}
    assert all(r["doc_id"] == target for r in rows)


def test_no_doc_id_still_returns_everything_for_the_owner(client):
    c, st = client
    st.create_disposition_audit("a1", doc_id="scan:s1:x.pdf", policy_id="r-1",
        action="tag", result="applied", detail="d", owner_email=OWNER)
    st.create_disposition_audit("a2", doc_id="scan:s1:y.pdf", policy_id="r-2",
        action="tag", result="applied", detail="d", owner_email=OWNER)

    resp = c.get("/disposition/audit")
    assert resp.status_code == 200
    assert {r["id"] for r in resp.json()} == {"a1", "a2"}


def test_doc_id_for_a_document_with_no_history_returns_empty_not_an_error(client):
    c, st = client
    st.create_disposition_audit("a1", doc_id="scan:s1:x.pdf", policy_id="r-1",
        action="tag", result="applied", detail="d", owner_email=OWNER)

    resp = c.get("/disposition/audit", params={"doc_id": "scan:s1:never-tagged.pdf"})
    assert resp.status_code == 200
    assert resp.json() == []
