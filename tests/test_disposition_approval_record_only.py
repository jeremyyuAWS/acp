"""Recording an approval WITHOUT executing it (approve?execute=false).

WHY THE OPTION EXISTS, rather than the UI simply calling approve and hoping:

  • `disposition.execute_action` supports Drive-backed documents ONLY — anything else comes
    back "unsupported source". A SharePoint/OneDrive document therefore CANNOT be executed
    today, whatever the caller asks for, and an Approve button that claimed otherwise would be
    describing a capability the deployment does not have.
  • ACP holds read-only scopes (sharepointScopes.CAN_WRITE_BACK is false). Recording the
    decision is the half of the operation that is real, and it is the half a compliance
    reviewer needs: the PRD asks for an approval queue that leaves an audit record, not for a
    button that moves files.

The load-bearing detail is that 'approved' is a LIVE outcome. `doc_has_disposition` gates
re-queueing, and if an approved-but-unexecuted decision did not count, the next execute run
would propose the same document again — asking a reviewer a question they have already
answered, which is how an approval queue stops being trusted. Third test below.

Default behaviour is UNCHANGED: approve with no query param still executes.
"""
from __future__ import annotations
import json
import sys
import tempfile
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))


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


def _seed(st, *, doc_id="sp:1", source="sharepoint", path="/Finance/old.docx"):
    """One document, one approval-gated policy, one pending audit row.

    Signatures taken from store.py rather than assumed — `department` is deliberately NOT an
    upsert_document field (ADR 0003's own noted gap: no real-scan source for it yet), so the
    enriched queue reports it as None here, which is the truthful answer.
    """
    st.upsert_document(doc_id, source=source, path=path, content_hash=None, owner="demo",
                       created_at="2020-01-01T00:00:00+00:00",
                       last_seen="2026-08-18T00:00:00+00:00",
                       triage_score=10, triage_rationale="seeded")
    st.create_disposition_policy("p1", name="archive-stale", match=json.dumps(
        [{"field": "source", "op": "eq", "value": source}]),
        action="archive", action_config="{}", requires_approval=True, enabled=True)
    st.create_disposition_audit("a1", doc_id=doc_id, policy_id="p1", action="archive",
                                result="pending_approval", detail="queued")
    return "a1"


# ── the queue is usable, and says which source each row belongs to ───────────

def test_the_queue_carries_the_document_not_just_its_id(client):
    """An audit row holds only doc_id. Approving "sp:1" asks somebody to authorise a string."""
    c, st = client
    _seed(st)
    row = c.get("/disposition/approvals").json()[0]
    assert row["path"] == "/Finance/old.docx"
    assert row["source"] == "sharepoint"
    assert row["document_exists"] is True


def test_a_queued_action_on_a_vanished_document_stays_visible(client):
    """Filtering it out would hide the one row a reviewer most needs to see before deciding."""
    c, st = client
    st.create_disposition_policy("p1", name="x", match="[]", action="archive",
                                 action_config="{}", requires_approval=True, enabled=True)
    st.create_disposition_audit("a1", doc_id="gone:1", policy_id="p1", action="archive",
                                result="pending_approval", detail="queued")
    row = c.get("/disposition/approvals").json()[0]
    assert row["document_exists"] is False
    assert row["source"] is None and row["path"] is None


# ── record-only ──────────────────────────────────────────────────────────────

def test_execute_false_records_the_decision_and_touches_nothing(client, monkeypatch):
    c, st = client
    _seed(st)
    import disposition
    monkeypatch.setattr(disposition, "execute_action",
                        lambda *a, **k: pytest.fail("execute_action must not run"))
    body = c.post("/disposition/approvals/a1/approve?execute=false").json()
    assert body["result"] == "approved"
    assert "not touched" in body["detail"]


def test_an_approved_decision_is_not_re_proposed(client):
    """The load-bearing one. doc_has_disposition gates re-queueing; if 'approved' were not
    live, the next execute run would ask the reviewer the same question again."""
    c, st = client
    _seed(st)
    c.post("/disposition/approvals/a1/approve?execute=false")
    assert st.doc_has_disposition("sp:1", "p1") is True


def test_rejected_and_failed_stay_re_proposable(client):
    """Deliberately NOT live — a re-run should be free to raise those again."""
    c, st = client
    _seed(st)
    c.post("/disposition/approvals/a1/reject")
    assert st.doc_has_disposition("sp:1", "p1") is False


def test_the_queue_empties_once_decided(client):
    c, st = client
    _seed(st)
    assert len(c.get("/disposition/approvals").json()) == 1
    c.post("/disposition/approvals/a1/approve?execute=false")
    assert c.get("/disposition/approvals").json() == []


def test_a_decided_row_cannot_be_decided_twice(client):
    c, st = client
    _seed(st)
    c.post("/disposition/approvals/a1/approve?execute=false")
    assert c.post("/disposition/approvals/a1/approve?execute=false").status_code == 404
    assert c.post("/disposition/approvals/a1/reject").status_code == 404


# ── the default is unchanged ─────────────────────────────────────────────────

def test_approve_without_the_param_still_executes(client, monkeypatch):
    """Existing callers relied on approve performing the action; that must not change under
    them because a new option was added."""
    c, st = client
    _seed(st, doc_id="drive:1", source="drive")
    seen = {}
    import routes.disposition as rd
    monkeypatch.setattr(rd.disposition, "execute_action",
                        lambda doc, action, cfg, svc: (seen.setdefault("ran", True), ("applied", "did it"))[1])
    body = c.post("/disposition/approvals/a1/approve").json()
    assert seen.get("ran") is True
    assert body["result"] == "applied"


def test_a_sharepoint_document_cannot_actually_execute(client):
    """The reason record-only exists: execute_action is Drive-only, so approving a SharePoint
    row for real fails by construction. Pinned so the UI's choice stays justified."""
    import disposition
    result, detail = disposition.execute_action(
        {"doc_id": "sp:1", "source": "sharepoint", "path": "/x.docx"}, "archive", {}, None)
    assert result == "failed"
    assert "unsupported source" in detail
