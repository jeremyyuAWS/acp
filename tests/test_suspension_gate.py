"""The suspension refusal, through the REAL access gate rather than through `email_allowed` alone.

tests/test_suspension_perimeter.py holds the predicate; this file holds the request. Split because
the two need different fixtures — one wants a bare core, the other wants the app assembled with
its middleware stack — and because the gate is where the two things a user actually experiences
live: the status code, and what it says.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ACP / "api"))

from test_suspension_perimeter import (  # noqa: E402  — one definition of the workspace
    DOMAIN_USER, ENV_ADMIN, LISTED, OUTSIDER, OWNER, suspend,
)


@pytest.fixture
def client(monkeypatch):
    """The real app and the REAL access gate, identity arriving as it does in production.

    `verify_gis_token` is stubbed to treat the token AS the email — the smallest possible seam,
    the same one tests/test_capability_enforcement.py uses. Everything else is shipped code: the
    gate's ordering, its 401/403 split, its request.state stamping, and `email_allowed` itself,
    which is the thing under test and is deliberately NOT stubbed.
    """
    import core
    import store as store_mod

    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "acp-test.db")
    st = store_mod.Store()
    monkeypatch.setattr(core, "store", st, raising=False)
    monkeypatch.setattr(core, "get_store", lambda: st, raising=False)
    monkeypatch.setattr(core, "OWNER_EMAIL", OWNER, raising=False)
    monkeypatch.setattr(core, "ALLOWED_DOMAINS", ["hosp.org"], raising=False)
    monkeypatch.setattr(core, "ALLOWED_EMAILS", set(), raising=False)
    monkeypatch.setattr(core, "ADMIN_EMAILS", {ENV_ADMIN}, raising=False)
    monkeypatch.setattr(core, "OPEN_ACCESS", True, raising=False)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "test-client", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    monkeypatch.setattr(core, "verify_gis_token", lambda t: (t or "").strip().lower() or None,
                        raising=False)
    st.set_allowlist([OWNER, LISTED])
    core.forget_rostered()

    from fastapi.testclient import TestClient
    from app import app
    return TestClient(app), core, st


# `/rubric` rather than `/me`: it is protected (not in core.ALWAYS_PUBLIC) and needs nothing from
# the caller beyond having passed the gate. `/me` answers 401 for its OWN reason when no Drive
# integration is connected — the exact confusion app.py's `_GATE_401` header exists to resolve —
# which made an admitted user look refused here on the first draft of this file.
def _get(tc, who):
    return tc.get("/rubric", headers={"Authorization": f"Bearer {who}"})


def test_a_suspended_person_is_refused_by_the_gate_not_the_route(client):
    tc, _core, st = client
    assert _get(tc, DOMAIN_USER).status_code == 200, "premise: admitted while active"
    suspend(st, DOMAIN_USER)
    assert _get(tc, DOMAIN_USER).status_code == 403


def test_the_gate_tells_a_suspended_person_that_they_are_suspended(client):
    """"Access restricted to authorized accounts" is true of somebody never admitted; said to a
    colleague an administrator suspended this morning it reads as a bug in the product rather
    than the deliberate act it is. No enumeration risk in the difference: this branch is reached
    only AFTER the bearer verified, so a caller can only ever learn the state of their own
    account."""
    tc, _core, st = client
    suspend(st, DOMAIN_USER)
    assert "suspended" in _get(tc, DOMAIN_USER).json()["detail"].lower()


def test_someone_never_admitted_gets_the_other_message(client):
    """THE CONTROL for the message. Without it, "the suspended message appears" is satisfiable by
    a gate that says suspended to everyone it turns away."""
    tc, _core, _st = client
    body = _get(tc, OUTSIDER).json()["detail"].lower()
    assert "suspended" not in body
    assert "authorized accounts" in body


def test_the_owner_still_gets_in_through_the_real_gate(client):
    """Anti-lockout, end to end. The owner is the identity that has to be able to UNDO a
    suspension, so a change that could lock them out breaks its own recovery path."""
    tc, _core, st = client
    st.upsert_person({"email": OWNER, "role": "owner", "status": "suspended"})
    assert _get(tc, OWNER).status_code == 200


def test_a_suspended_person_never_reaches_just_in_time_roster_creation(client):
    """Roster creation runs AFTER the gate admits, so a refusal has to come first — a suspended
    address must not be able to re-create its own person record by knocking."""
    tc, core, st = client
    st.upsert_person({"email": "ghost@hosp.org", "role": "user", "status": "suspended"})
    core.forget_rostered()
    calls = []
    original = core.note_signed_in
    try:
        core.note_signed_in = lambda *a, **k: (calls.append(a), original(*a, **k))[1]
        assert _get(tc, "ghost@hosp.org").status_code == 403
        assert calls == [], "roster creation ran for somebody the gate refused"
    finally:
        core.note_signed_in = original
