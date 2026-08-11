"""The access gate marks its OWN 401s with X-Acp-Auth: session, so the SPA can tell a real session
expiry from a route-level 401 and stop ejecting an authenticated user over an unconnected source
(found 2026-08-11: /sources 401'ing a Microsoft user with no Google Drive bounced the whole session).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

USER = "jeremy_acp@fgxlxj.onmicrosoft.com"


@pytest.fixture()
def gated(monkeypatch, isolated_store):
    import core
    from fastapi.testclient import TestClient

    from app import app

    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "test-client-id", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    monkeypatch.setattr(core, "verify_gis_token", lambda tok: tok or None)
    monkeypatch.setattr(core, "email_allowed", lambda e: e == USER)
    return TestClient(app)


def test_no_bearer_401_is_marked_session(gated):
    r = gated.get("/scans")
    assert r.status_code == 401
    assert r.headers.get("X-Acp-Auth") == "session"


def test_invalid_token_401_is_marked_session(gated, monkeypatch):
    import core
    monkeypatch.setattr(core, "verify_gis_token", lambda tok: None)  # token no longer valid
    r = gated.get("/scans", headers={"Authorization": "Bearer stale"})
    assert r.status_code == 401
    assert r.headers.get("X-Acp-Auth") == "session"


def test_forbidden_is_NOT_marked_session(gated):
    # A valid session for a non-allow-listed identity is 403 — not a session expiry, and must not
    # carry the marker (the SPA should show "access restricted", not sign the user out).
    r = gated.get("/scans", headers={"Authorization": "Bearer stranger@example.com"})
    assert r.status_code == 403
    assert r.headers.get("X-Acp-Auth") is None
