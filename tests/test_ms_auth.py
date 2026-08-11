"""The backend authenticates a Microsoft (Entra) sign-in, not only Google.

#239 shipped a "Sign in with Microsoft" button, but the access gate only ever accepted Google
tokens (`verify_gis_token` against Google's tokeninfo). A Microsoft user therefore 401'd the instant
the SPA made its first real call — the app showed "session expired" the moment they were in.

These pin the fix:
  * `verify_ms_token` verifies by asking Microsoft Graph /me (the same "ask the provider" shape as
    the Google lane), and caches the answer.
  * the access gate routes on the `X-Auth-Provider` header, so a Microsoft request is verified
    against Graph and a Google request (no header) is unchanged.
  * `email_allowed` decides access identically for both providers.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

MS_USER = "jeremy_acp@fgxlxj.onmicrosoft.com"
BLOCKED = "stranger@example.com"


def test_verify_ms_token_returns_graph_identity(monkeypatch):
    import core
    monkeypatch.setattr(core, "_graph_me_email", lambda tok: MS_USER if tok == "good" else None)
    core._ms_cache.clear()
    assert core.verify_ms_token("good") == MS_USER
    assert core.verify_ms_token("bad") is None


def test_verify_ms_token_caches_the_graph_call(monkeypatch):
    import core
    calls = {"n": 0}

    def fake(tok):
        calls["n"] += 1
        return MS_USER

    monkeypatch.setattr(core, "_graph_me_email", fake)
    core._ms_cache.clear()
    assert core.verify_ms_token("t") == MS_USER
    assert core.verify_ms_token("t") == MS_USER
    assert calls["n"] == 1  # second call served from cache — no second Graph round-trip per request


@pytest.fixture()
def gated(monkeypatch, isolated_store):
    """A TestClient behind the real access gate, with token==email for both providers so a test can
    'sign in' as anybody without a network call. Faithful to production: ACP_ACCESS_CODE is empty,
    so the gate takes the `elif core.GOOGLE_CLIENT_ID` branch."""
    import core
    from fastapi.testclient import TestClient

    from app import app

    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "test-client-id", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    monkeypatch.setattr(core, "verify_gis_token", lambda tok: tok or None)
    monkeypatch.setattr(core, "verify_ms_token", lambda tok: tok or None)
    monkeypatch.setattr(core, "email_allowed", lambda e: e == MS_USER)
    return TestClient(app)


def test_microsoft_user_passes_the_gate(gated):
    # /scans is the first authed call the SPA makes after sign-in — the exact one that 401'd.
    r = gated.get("/scans", headers={"Authorization": f"Bearer {MS_USER}", "X-Auth-Provider": "microsoft"})
    assert r.status_code == 200


def test_microsoft_user_not_allowlisted_is_forbidden(gated):
    r = gated.get("/scans", headers={"Authorization": f"Bearer {BLOCKED}", "X-Auth-Provider": "microsoft"})
    assert r.status_code == 403


def test_microsoft_request_uses_ms_verify_not_google(gated, monkeypatch):
    """Prove the routing: if the gate wrongly ran the Google verifier for a Microsoft request, this
    would 401 (Google can't verify a Graph token). Make Google verify ALWAYS fail; MS must still in."""
    import core
    monkeypatch.setattr(core, "verify_gis_token", lambda tok: None)
    r = gated.get("/scans", headers={"Authorization": f"Bearer {MS_USER}", "X-Auth-Provider": "microsoft"})
    assert r.status_code == 200


def test_default_request_still_uses_google(gated, monkeypatch):
    """No X-Auth-Provider → the Google path, unchanged. Make MS verify fail to prove it's untouched."""
    import core
    monkeypatch.setattr(core, "verify_ms_token", lambda tok: None)
    r = gated.get("/scans", headers={"Authorization": f"Bearer {MS_USER}"})
    assert r.status_code == 200


def test_no_bearer_is_401(gated):
    assert gated.get("/scans").status_code == 401
