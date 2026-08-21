"""Explicit rule priority and PUT /disposition/policies/reorder.

Lifecycle Rules build-plan item #6, priority half. Rule evaluation order used to be an accident
of list_disposition_policies' own ORDER BY name — reordering meant renaming. This gives it a real
column: new rules are assigned the next integer past the tenant's current max (so a new rule
starts last, the safe default); NULL (every pre-existing row) sorts after every prioritized row
and is broken by name among itself, so a tenant who never reorders sees no behaviour change.

list_disposition_policies' order IS evaluation order — handlers._evaluate_discover_lifecycle_rules
and the conflicts report both just consume what it returns — so these tests check the store's
ordering directly rather than a separate "priority" concept.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

OWNER = "jeremyyu.movate@gmail.com"
MATCH = [{"field": "path", "op": "prefix", "value": "/Finance/"}]


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


# ── Store level: assignment and ordering ────────────────────────────────────────────────────

def test_a_rules_priority_is_the_next_integer_past_this_tenants_max(isolated_store):
    st = isolated_store
    st.create_disposition_policy("p1", name="first", match=json.dumps(MATCH), action="archive",
                                 action_config="{}", requires_approval=True, enabled=False,
                                 owner_email=OWNER)
    st.create_disposition_policy("p2", name="second", match=json.dumps(MATCH), action="archive",
                                 action_config="{}", requires_approval=True, enabled=False,
                                 owner_email=OWNER)
    st.create_disposition_policy("p3", name="third", match=json.dumps(MATCH), action="archive",
                                 action_config="{}", requires_approval=True, enabled=False,
                                 owner_email=OWNER)
    priorities = {p["policy_id"]: p["priority"] for p in st.list_disposition_policies(owner=OWNER)}
    assert priorities == {"p1": 1, "p2": 2, "p3": 3}


def test_two_tenants_get_independent_priority_sequences(isolated_store):
    """The MAX(priority) subquery is scoped by owner_email — one tenant's rule count must not
    push another tenant's next priority past 1."""
    st = isolated_store
    st.create_disposition_policy("mine1", name="a", match=json.dumps(MATCH), action="archive",
                                 action_config="{}", requires_approval=True, enabled=False,
                                 owner_email=OWNER)
    st.create_disposition_policy("mine2", name="b", match=json.dumps(MATCH), action="archive",
                                 action_config="{}", requires_approval=True, enabled=False,
                                 owner_email=OWNER)
    st.create_disposition_policy("theirs1", name="c", match=json.dumps(MATCH), action="archive",
                                 action_config="{}", requires_approval=True, enabled=False,
                                 owner_email="someone.else@example.com")
    assert st.get_disposition_policy("theirs1")["priority"] == 1


def test_null_priority_sorts_after_every_prioritized_rule_then_by_name(isolated_store):
    """A pre-migration row (priority NULL) must not accidentally sort FIRST just because NULL
    compares oddly — it goes last, exactly where "no explicit priority" belongs."""
    st = isolated_store
    st.create_disposition_policy("legacy", name="AAA legacy", match=json.dumps(MATCH),
                                 action="archive", action_config="{}", requires_approval=True,
                                 enabled=False, owner_email=OWNER)   # priority=1 on create
    # Force it back to NULL to simulate a genuinely pre-migration row.
    with st._db.cursor() as cur:
        st._db.execute(cur, "UPDATE disposition_policy SET priority=NULL WHERE policy_id=%s", ("legacy",))
    st.create_disposition_policy("new", name="ZZZ new", match=json.dumps(MATCH), action="archive",
                                 action_config="{}", requires_approval=True, enabled=False,
                                 owner_email=OWNER)
    ids = [p["policy_id"] for p in st.list_disposition_policies(owner=OWNER)]
    assert ids == ["new", "legacy"]   # priority=1 before NULL, regardless of name


def test_reorder_writes_1_through_n_in_the_given_order(isolated_store):
    st = isolated_store
    for pid in ("p1", "p2", "p3"):
        st.create_disposition_policy(pid, name=pid, match=json.dumps(MATCH), action="archive",
                                     action_config="{}", requires_approval=True, enabled=False,
                                     owner_email=OWNER)
    st.reorder_disposition_policies(OWNER, ["p3", "p1", "p2"])
    ids = [p["policy_id"] for p in st.list_disposition_policies(owner=OWNER)]
    assert ids == ["p3", "p1", "p2"]


# ── Route level ──────────────────────────────────────────────────────────────────────────────

def test_reorder_route_requires_the_full_current_set_exactly_once(client):
    c, st = client
    for pid in ("p1", "p2", "p3"):
        st.create_disposition_policy(pid, name=pid, match=json.dumps(MATCH), action="archive",
                                     action_config="{}", requires_approval=True, enabled=False,
                                     owner_email=OWNER)
    # missing p3
    assert c.put("/disposition/policies/reorder", json={"policy_ids": ["p2", "p1"]}).status_code == 422
    # a duplicate
    assert c.put("/disposition/policies/reorder",
                json={"policy_ids": ["p1", "p1", "p2"]}).status_code == 422
    # a foreign id
    assert c.put("/disposition/policies/reorder",
                json={"policy_ids": ["p1", "p2", "not-mine"]}).status_code == 422
    # exactly right
    r = c.put("/disposition/policies/reorder", json={"policy_ids": ["p3", "p2", "p1"]})
    assert r.status_code == 200
    assert [p["policy_id"] for p in r.json()] == ["p3", "p2", "p1"]


def test_reorder_is_scoped_to_the_caller_tenant_only(client):
    """Reordering must never move a rule that belongs to someone else, even if it were somehow
    named in the list — the current_ids check is what makes a foreign id 422 rather than acted on."""
    c, st = client
    st.create_disposition_policy("mine", name="mine", match=json.dumps(MATCH), action="archive",
                                 action_config="{}", requires_approval=True, enabled=False,
                                 owner_email=OWNER)
    st.create_disposition_policy("theirs", name="theirs", match=json.dumps(MATCH), action="archive",
                                 action_config="{}", requires_approval=True, enabled=False,
                                 owner_email="someone.else@example.com")
    r = c.put("/disposition/policies/reorder", json={"policy_ids": ["mine", "theirs"]})
    assert r.status_code == 422
    assert st.get_disposition_policy("theirs")["priority"] == 1   # untouched
