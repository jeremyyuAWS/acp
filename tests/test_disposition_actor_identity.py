"""The decision_log entry for a disposition action names the real caller, not the literal
string "admin".

THE DEFECT: every `log_decision(...)` call in api/routes/disposition.py passed the hardcoded
string "admin" as the actor, regardless of who actually made the request — so
disposition.policy_created / _updated / _enabled / _executed / .approved / .rejected all read
back as having been done by "admin", even under the open-access model where any signed-in user
can author a rule and an owner can execute or approve one.

This is exactly the ownership-isolation gap fixed elsewhere in this branch (see
test_disposition_owner_isolation.py), just in the decision_log rather than disposition_policy /
disposition_audit — the route already computes `owner = _owner(request)` for every one of these
calls (it needs it for the owner-scoped store lookups right above), so passing it into
log_decision instead of "admin" is a one-word fix per call site, not a new capability.

Route level, not store level: the fix is entirely in api/routes/disposition.py's call sites, so
these tests exercise the routes through the same gated_client fixture pattern as
test_disposition_owner_isolation.py rather than calling store methods directly.
"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

OWNER = "jeremyyu.movate@gmail.com"

MATCH = [{"field": "path", "op": "prefix", "value": "/Finance/"}]


@pytest.fixture()
def gated_client(monkeypatch, isolated_store):
    """Same fixture as test_disposition_owner_isolation.py's gated_client."""
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
    return client


def _last_actor(store, action_prefix: str) -> str:
    rows = [d for d in store.list_decisions() if d["action"].startswith(action_prefix)]
    assert rows, f"no decision_log row for {action_prefix!r}"
    return rows[0]["actor"]


def test_policy_created_is_attributed_to_the_real_caller(gated_client, isolated_store):
    gated_client.post("/disposition/policies",
                      json={"name": "archive stale finance", "match": MATCH, "action": "archive"})
    actor = _last_actor(isolated_store, "disposition.policy_created")
    assert actor == OWNER
    assert actor != "admin"


def test_policy_enabled_is_attributed_to_the_real_caller(gated_client, isolated_store):
    pid = gated_client.post(
        "/disposition/policies",
        json={"name": "x", "match": MATCH, "action": "archive"}).json()["policy_id"]
    gated_client.put(f"/disposition/policies/{pid}/enabled?enabled=true")
    assert _last_actor(isolated_store, "disposition.policy_enabled") == OWNER


def test_policy_updated_is_attributed_to_the_real_caller(gated_client, isolated_store):
    pid = gated_client.post(
        "/disposition/policies",
        json={"name": "x", "match": MATCH, "action": "archive"}).json()["policy_id"]
    gated_client.put(f"/disposition/policies/{pid}", json={"name": "renamed"})
    assert _last_actor(isolated_store, "disposition.policy_updated") == OWNER


def test_approve_and_reject_are_attributed_to_the_real_caller(gated_client, isolated_store):
    st = isolated_store
    st.create_disposition_policy("p1", name="mine", match='[{"field":"path","op":"prefix","value":"/Finance/"}]',
                                 action="archive", action_config="{}",
                                 requires_approval=True, enabled=True, owner_email=OWNER)
    st.create_disposition_audit("a1", doc_id="d1", policy_id="p1", action="archive",
                                result="pending_approval", detail="queued", owner_email=OWNER)
    st.create_disposition_audit("a2", doc_id="d2", policy_id="p1", action="archive",
                                result="pending_approval", detail="queued", owner_email=OWNER)

    gated_client.post("/disposition/approvals/a1/approve?execute=false")
    gated_client.post("/disposition/approvals/a2/reject")

    assert _last_actor(isolated_store, "disposition.approved") == OWNER
    assert _last_actor(isolated_store, "disposition.rejected") == OWNER
