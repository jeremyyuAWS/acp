"""Scope-rule CRUD API (Phase C4c, Discover/Assess Lifecycle PRD §4.4).

Owner-gated endpoints over the merged scope_resolver + store accessors. Under test:

  * `GET /scope/selectors` — the editor's building blocks (selectors + Core-17 catalog).
  * `GET /scope/rules` / `POST` / `PATCH` / `DELETE` — the CRUD happy path.
  * validation — a rule with a non-Core-17 code is a 400 carrying the validator's message,
    and nothing is persisted.
  * the owner gate — with an OWNER_EMAIL configured, an anonymous caller cannot mutate.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import scope_resolver
import wcag_codeset


@pytest.fixture()
def client(monkeypatch, isolated_store):
    """A TestClient with the access gate OFF (owner resolves to 'demo', writes allowed)."""
    import core
    from fastapi.testclient import TestClient
    from app import app

    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    monkeypatch.setattr(core, "OWNER_EMAIL", "", raising=False)   # local-dev no-auth path
    return TestClient(app), isolated_store


# ── /scope/selectors ──────────────────────────────────────────────────────────────────
def test_selectors_lists_selectors_and_core17_catalog(client):
    c, _ = client
    body = c.get("/scope/selectors").json()
    assert body["selectors"] == list(scope_resolver.SELECTORS)
    assert len(body["codes"]) == 17
    entry = {e["code"]: e for e in body["codes"]}["1.4.3"]
    assert entry["name"] == "Contrast (Minimum)"
    assert entry["formats"] == ["docx", "pdf", "pptx", "xlsx"]


# ── CRUD happy path ───────────────────────────────────────────────────────────────────
def test_create_list_patch_delete_round_trip(client):
    c, store = client

    # Empty to start.
    assert c.get("/scope/rules").json()["rules"] == []

    # Create.
    res = c.post("/scope/rules", json={
        "name": "Finance folder", "selector": "folder", "value": "Finance",
        "codes": ["1.4.3", "2.4.6"], "priority": 5, "is_override": True,
    })
    assert res.status_code == 200, res.text
    created = res.json()
    rid = created["rule_id"]
    assert rid
    assert created["selector"] == "folder"
    assert created["value"] == "Finance"
    assert sorted(created["codes"]) == ["1.4.3", "2.4.6"]
    assert created["priority"] == 5
    assert created["is_override"] is True
    assert created["enabled"] is True
    assert created["created_by"] == "demo"

    # List reflects it, codes decoded.
    listed = c.get("/scope/rules").json()["rules"]
    assert len(listed) == 1
    assert listed[0]["rule_id"] == rid
    assert sorted(listed[0]["codes"]) == ["1.4.3", "2.4.6"]

    # Disable via PATCH.
    res = c.patch(f"/scope/rules/{rid}", json={"enabled": False})
    assert res.status_code == 200, res.text
    assert res.json()["enabled"] is False
    assert store.get_scope_rule(rid)["enabled"] is False

    # Delete.
    res = c.delete(f"/scope/rules/{rid}")
    assert res.status_code == 200, res.text
    assert res.json()["deleted"] == rid
    assert c.get("/scope/rules").json()["rules"] == []


def test_list_is_priority_desc_as_the_store_gives_it(client):
    c, _ = client
    c.post("/scope/rules", json={"name": "low", "selector": "owner",
                                 "value": "a@x.com", "codes": ["1.4.3"], "priority": 1})
    c.post("/scope/rules", json={"name": "high", "selector": "owner",
                                 "value": "b@x.com", "codes": ["1.4.3"], "priority": 9})
    rules = c.get("/scope/rules").json()["rules"]
    assert [r["priority"] for r in rules] == [9, 1]   # priority desc


# ── validation ────────────────────────────────────────────────────────────────────────
def test_create_rejects_non_core17_code_with_400(client):
    c, store = client
    # 2.4.7 is a real WCAG SC but NOT in the Core 17 — the validator rejects it.
    res = c.post("/scope/rules", json={"name": "bad", "selector": "folder",
                                       "value": "HR", "codes": ["2.4.7"]})
    assert res.status_code == 400, res.text
    assert "allowed Core-17" in res.json()["detail"]
    # Nothing persisted on a rejected create.
    assert store.list_scope_rules() == []


def test_create_rejects_empty_codes_and_blank_value(client):
    c, _ = client
    assert c.post("/scope/rules", json={"selector": "folder", "value": "HR",
                                        "codes": []}).status_code == 400
    assert c.post("/scope/rules", json={"selector": "folder", "value": "  ",
                                        "codes": ["1.4.3"]}).status_code == 400
    assert c.post("/scope/rules", json={"selector": "nonsense", "value": "HR",
                                        "codes": ["1.4.3"]}).status_code == 400


def test_patch_and_delete_unknown_rule_are_404(client):
    c, _ = client
    assert c.patch("/scope/rules/nope", json={"enabled": False}).status_code == 404
    assert c.delete("/scope/rules/nope").status_code == 404


# ── owner gate ────────────────────────────────────────────────────────────────────────
def test_mutations_are_owner_only(monkeypatch, isolated_store):
    """With an OWNER_EMAIL set and no authenticated caller, every write is a 403 and the
    read stays open (the SPA renders the editor read-only off exactly this)."""
    import core
    from fastapi.testclient import TestClient
    from app import app

    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    monkeypatch.setattr(core, "OWNER_EMAIL", "owner@example.com", raising=False)
    c = TestClient(app)

    assert c.get("/scope/rules").status_code == 200          # read is open
    assert c.get("/scope/selectors").status_code == 200

    assert c.post("/scope/rules", json={"selector": "folder", "value": "HR",
                                        "codes": ["1.4.3"]}).status_code == 403
    assert c.patch("/scope/rules/x", json={"enabled": False}).status_code == 403
    assert c.delete("/scope/rules/x").status_code == 403
    assert isolated_store.list_scope_rules() == []           # nothing slipped through
