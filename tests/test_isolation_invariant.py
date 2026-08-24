"""Isolation-off invariant: ACCESS_CODE overrides GOOGLE_CLIENT_ID and drops per-user stamping.

THE INVARIANT (backlog R13):

    isolated = bool(core.GOOGLE_CLIENT_ID) and not core.ACCESS_CODE

The footgun: ACCESS_CODE and GOOGLE_CLIENT_ID are an if/ELIF in the access gate, so setting an
access code on a deployment that ALSO has Google configured does NOT add a second auth factor —
it takes the `if ACCESS_CODE` branch and exits without stamping `request.state.user_email`.
`_owner(request)` then returns 'demo' for everyone, collapsing the estate into a single shared
namespace: patient A's remediated documents become readable by patient B.

WHAT THESE TESTS DO:
  1. Isolation ON  (GOOGLE_CLIENT_ID set, ACCESS_CODE absent)  — a Bearer token is verified, the
     user's email is stamped on request.state, _owner() returns that email, and the user sees
     only their own scans, not scans belonging to 'demo'.

  2. Isolation OFF (both set, ACCESS_CODE takes the if-branch) — Basic auth is checked, no
     email is ever stamped, _owner() falls back to 'demo', and a signed-in user finds themselves
     looking at demo-owned scans rather than their own estate.

The tests drive real HTTP through the real access-gate middleware (api/app.py) with monkeypatched
core constants and a mocked token verifier — no line-of-sight changes to app.py or core.py.
"""
from __future__ import annotations

import base64
import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

USER = "alice@hospital.example.com"
OTHER = "demo"  # the shared-estate fallback


def _seed_scan(store, sid: str, owner: str) -> None:
    """A minimal finalized scan attributed to `owner`, visible to list_scans."""
    store.save_scan({
        "_scan_id": sid,
        "started_at": "2026-01-01T00:00:00+00:00",
        "completed_at": "2026-01-01T01:00:00+00:00",
        "source": "local",
        "owner": owner,
        "rubric": {"name": "wcag-aa", "hash": "abc123"},
        "summary": {"files": 1, "certifiable": 1, "uncertain": 0, "error": 0, "avg_score": 95},
        "files": [{"file": "doc.pdf", "engine": "pdf", "status": "certifiable",
                   "score": 95, "compliant": 1, "skipped_rules": 0, "issues": []}],
    })


def _basic_header(password: str) -> str:
    return "Basic " + base64.b64encode(f"user:{password}".encode()).decode()


# ── Isolation ON: GOOGLE_CLIENT_ID set, no ACCESS_CODE ────────────────────────────────────────


@pytest.fixture()
def gis_only_client(monkeypatch, isolated_store):
    """TestClient with the Google-only access gate (isolation ON).

    ACCESS_CODE is absent, so the gate takes the `elif GOOGLE_CLIENT_ID` branch, verifies the
    Bearer token, and stamps request.state.user_email. _owner() then returns that email.
    """
    import core
    from fastapi.testclient import TestClient
    from app import app

    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", None, raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "test-client-id.apps.googleusercontent.com",
                        raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    # Token == email: a test can "sign in" as any address without talking to Google.
    monkeypatch.setattr(core, "verify_gis_token", lambda tok: tok or None)
    monkeypatch.setattr(core, "email_allowed", lambda e: True)

    return TestClient(app)


def test_isolation_on__google_user_sees_only_own_scans(gis_only_client, isolated_store):
    """THE positive case: with Google auth and no ACCESS_CODE the gate stamps user_email, so
    _owner() resolves to the verified email and the user's scans are isolated from 'demo'."""
    _seed_scan(isolated_store, "user-scan-001", USER)
    _seed_scan(isolated_store, "demo-scan-001", OTHER)

    r = gis_only_client.get("/scans", headers={"Authorization": f"Bearer {USER}"})
    assert r.status_code == 200

    ids = [s["id"] for s in r.json()]
    assert "user-scan-001" in ids, (
        "signed-in Google user must see their own scan — user_email was not stamped or "
        "_owner() did not resolve to the right email"
    )
    assert "demo-scan-001" not in ids, (
        "signed-in Google user must NOT see the 'demo' estate; isolation is supposed to be ON"
    )


def test_isolation_on__no_bearer_token_is_refused(gis_only_client):
    """Baseline: the gate must reject unauthenticated requests when GOOGLE_CLIENT_ID is set."""
    r = gis_only_client.get("/scans")
    assert r.status_code == 401
    assert r.headers.get("X-Acp-Auth") == "session"


def test_isolation_on__bad_token_is_refused(gis_only_client, monkeypatch):
    """An invalid/expired token must produce a 401, not silently fall through to 'demo'."""
    import core
    monkeypatch.setattr(core, "verify_gis_token", lambda tok: None)  # every token invalid
    r = gis_only_client.get("/scans", headers={"Authorization": "Bearer expired-token"})
    assert r.status_code == 401


# ── Isolation OFF: ACCESS_CODE overrides GOOGLE_CLIENT_ID ─────────────────────────────────────


@pytest.fixture()
def access_code_plus_gis_client(monkeypatch, isolated_store):
    """TestClient with ACCESS_CODE set alongside GOOGLE_CLIENT_ID (isolation OFF).

    The if/ELIF footgun: ACCESS_CODE takes the first branch, which checks Basic auth and then
    calls next WITHOUT stamping user_email. Even though GOOGLE_CLIENT_ID is present, the
    elif branch never runs — so no email is ever set on request.state.
    """
    import core
    from fastapi.testclient import TestClient
    from app import app

    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "s3cret-code", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "test-client-id.apps.googleusercontent.com",
                        raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    # verify_gis_token should never be called on this path — if it is, the test will reveal it.
    monkeypatch.setattr(core, "verify_gis_token",
                        lambda tok: (_ for _ in ()).throw(
                            AssertionError("verify_gis_token must not be called when ACCESS_CODE "
                                           "takes the if-branch: the elif never runs")))
    monkeypatch.setattr(core, "email_allowed", lambda e: True)

    return TestClient(app)


def test_isolation_off__owner_resolves_to_demo_not_the_user(
        access_code_plus_gis_client, isolated_store):
    """THE invariant: when ACCESS_CODE is set alongside GOOGLE_CLIENT_ID, request.state.user_email
    is never stamped, so every authenticated user resolves to the shared 'demo' owner.

    Manifested concretely: a user who signed in with Basic auth sees the 'demo' scan list, not
    a personal estate. For a hospital this means patient A can read patient B's documents."""
    _seed_scan(isolated_store, "user-scan-001", USER)    # what the user EXPECTS to see
    _seed_scan(isolated_store, "demo-scan-001", OTHER)   # what they ACTUALLY get (the bug)

    r = access_code_plus_gis_client.get(
        "/scans", headers={"Authorization": _basic_header("s3cret-code")}
    )
    assert r.status_code == 200

    ids = [s["id"] for s in r.json()]
    assert "demo-scan-001" in ids, (
        "with ACCESS_CODE set the gate never stamps user_email, so _owner() returns 'demo' "
        "and every user lands in the shared demo estate"
    )
    assert "user-scan-001" not in ids, (
        f"the scan attributed to {USER!r} must NOT be visible — user_email was never stamped, "
        "so that owner never resolves; isolation is OFF and the caller is 'demo'"
    )


def test_isolation_off__wrong_access_code_is_refused(access_code_plus_gis_client):
    """Baseline: a wrong access code is still refused (the gate is not simply bypassed)."""
    r = access_code_plus_gis_client.get(
        "/scans", headers={"Authorization": _basic_header("wrong-code")}
    )
    assert r.status_code == 401


def test_isolation_off__no_auth_is_refused(access_code_plus_gis_client):
    """Without any Authorization header the gate must still return 401."""
    r = access_code_plus_gis_client.get("/scans")
    assert r.status_code == 401


def test_isolation_off__bearer_token_is_not_accepted_as_basic_auth(
        access_code_plus_gis_client):
    """When ACCESS_CODE is set the gate checks Basic only. A Bearer token — even a valid Google
    one — must NOT be accepted, because the if-branch only decodes Basic credentials."""
    # A Bearer token happens to equal the access code value after a colon, which could
    # theoretically pass a naive split(":", 1)[1] check. Use a distinct value to be sure.
    r = access_code_plus_gis_client.get(
        "/scans", headers={"Authorization": f"Bearer {USER}"}
    )
    assert r.status_code == 401, (
        "when ACCESS_CODE is set a Bearer token must be rejected — the gate does not fall "
        "through to the GOOGLE_CLIENT_ID branch, so verify_gis_token never runs"
    )
