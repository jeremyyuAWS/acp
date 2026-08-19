"""The non-admin per-user scan-scope override route (ADR 0035 stage 2, the user-facing surface).

`GET/PUT/DELETE /settings/mine` let a SIGNED-IN user manage their OWN scan-scope override, keyed to
their email, never able to write another user's. Under test: the round-trip, validation-before-write
(a malformed scope is a 422 and is NOT stored), the "" vs DELETE distinction (a real no-restriction
override vs clearing the override), per-user isolation, and that an anonymous caller is refused.

A signed-in user is simulated the way production stamps one: the access gate verifies a Bearer token
via core.verify_gis_token, so the test monkeypatches that to return a fixed email and sends a bearer.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))


def _client(monkeypatch, isolated_store, *, email="alice@hosp.org"):
    """A TestClient whose access gate is LIVE (GOOGLE_CLIENT_ID set) and whose token verification is
    stubbed to stamp `email` — so request.state.user_email is a real, specific signed-in user."""
    import core
    from fastapi.testclient import TestClient
    from app import app

    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "test-client-id", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    monkeypatch.setattr(core, "OWNER_EMAIL", "", raising=False)
    monkeypatch.setattr(core, "verify_gis_token", lambda tok: email, raising=False)
    monkeypatch.setattr(core, "email_allowed", lambda e: True, raising=False)
    return TestClient(app)


_AUTH = {"Authorization": "Bearer tok"}


def test_round_trip_get_put_get(monkeypatch, isolated_store):
    c = _client(monkeypatch, isolated_store)
    assert c.get("/settings/mine", headers=_AUTH).json()["scan_scope"] == ""     # none to start
    put = c.put("/settings/mine", headers=_AUTH, json={"scan_scope": {"1.4.3": ["docx", "pdf"]}})
    assert put.status_code == 200, put.text
    got = c.get("/settings/mine", headers=_AUTH).json()
    assert got["scan_scope"] == '{"1.4.3": ["docx", "pdf"]}'                      # raw, round-trips


def test_get_reports_the_owner_default_it_widens_onto(monkeypatch, isolated_store):
    isolated_store.set_setting("scan_scope", '{"1.4.3": ["docx"]}')              # owner mandate
    c = _client(monkeypatch, isolated_store)
    assert c.get("/settings/mine", headers=_AUTH).json()["owner_default"] == '{"1.4.3": ["docx"]}'


def test_a_malformed_scope_is_422_and_not_stored(monkeypatch, isolated_store):
    c = _client(monkeypatch, isolated_store)
    res = c.put("/settings/mine", headers=_AUTH, json={"scan_scope": "not-a-known-preset"})
    assert res.status_code == 422
    assert isolated_store.get_user_setting("alice@hosp.org", "scan_scope") is None  # nothing stored


def test_empty_override_is_stored_as_no_restriction_distinct_from_delete(monkeypatch, isolated_store):
    c = _client(monkeypatch, isolated_store)
    # PUT "" is a REAL override: the user opting into no restriction. Stored as "" (present).
    assert c.put("/settings/mine", headers=_AUTH, json={"scan_scope": ""}).status_code == 200
    assert isolated_store.get_user_setting("alice@hosp.org", "scan_scope") == ""    # present, empty
    # DELETE removes the override entirely → falls back to owner default (get_user_setting None).
    assert c.delete("/settings/mine", headers=_AUTH).status_code == 200
    assert isolated_store.get_user_setting("alice@hosp.org", "scan_scope") is None


def test_empty_object_normalizes_to_empty_string(monkeypatch, isolated_store):
    c = _client(monkeypatch, isolated_store)
    assert c.put("/settings/mine", headers=_AUTH, json={"scan_scope": {}}).json()["scan_scope"] == ""


def test_one_users_override_never_touches_another(monkeypatch, isolated_store):
    ca = _client(monkeypatch, isolated_store, email="alice@hosp.org")
    ca.put("/settings/mine", headers=_AUTH, json={"scan_scope": {"1.4.3": ["pdf"]}})
    # A different signed-in user sees THEIR own (absent) override, not alice's.
    monkeypatch.setattr(__import__("core"), "verify_gis_token", lambda tok: "bob@hosp.org",
                        raising=False)
    assert ca.get("/settings/mine", headers=_AUTH).json()["scan_scope"] == ""
    assert isolated_store.get_user_setting("alice@hosp.org", "scan_scope") == '{"1.4.3": ["pdf"]}'


def test_anonymous_caller_is_401(monkeypatch, isolated_store):
    # No Authorization header → the access gate refuses before the route; per-user settings require
    # an identity and must never fall back to a shared owner.
    c = _client(monkeypatch, isolated_store)
    assert c.get("/settings/mine").status_code == 401
    assert c.put("/settings/mine", json={"scan_scope": ""}).status_code == 401
