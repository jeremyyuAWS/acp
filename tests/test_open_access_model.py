"""Open-access model (ACP_OPEN_ACCESS, default on): there is no separate admin view — every
AUTHENTICATED, admitted user gets the same screens and non-destructive features (including the
lifecycle rule builder). What stays owner-only is exactly the destructive/irreversible surface:
wiping all data, managing who can log in, and authorising/performing a file move-or-trash.

These tests pin BOTH halves — that the surface opened for ordinary users, and that the dangerous
few did NOT — plus that turning the flag off restores role-based admin, and that an unauthenticated
caller is still nobody.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))


def _req(email):
    return SimpleNamespace(state=SimpleNamespace(user_email=email))


class _Store:
    def __init__(self):
        self.settings = {}
    def get_setting(self, key, default=None):
        return self.settings.get(key, default)
    def set_setting(self, key, value):
        self.settings[key] = value
    def get_admins(self):
        raw = self.get_setting("admin_emails", "") or ""
        return [e.strip().lower() for e in raw.split(",") if e.strip()]
    def set_admins(self, emails):
        self.set_setting("admin_emails", ",".join(sorted(emails)))


@pytest.fixture
def owned(monkeypatch):
    import core
    monkeypatch.setattr(core, "OWNER_EMAIL", "owner@hosp.org", raising=False)
    monkeypatch.setattr(core, "ADMIN_EMAILS", set(), raising=False)
    monkeypatch.setattr(core, "OPEN_ACCESS", True, raising=False)
    return core


# ── is_admin ──────────────────────────────────────────────────────────────────────────────────

def test_open_access_makes_any_authenticated_user_admin(owned):
    core = owned
    assert core.is_admin("owner@hosp.org")        # owner, as ever
    assert core.is_admin("deva@movate.com")       # any signed-in, admitted user — same view
    assert core.is_admin("nurse@hosp.org")


def test_open_access_never_admits_the_unauthenticated(owned):
    core = owned
    assert not core.is_admin("")                  # empty email = nobody signed in
    assert not core.is_admin(None)                # login perimeter is unchanged


def test_owner_tier_is_unchanged_under_open_access(owned):
    core = owned
    assert core.is_owner("owner@hosp.org")
    assert not core.is_owner("deva@movate.com")   # everyone is admin, but the OWNER is still one identity


def test_open_access_off_restores_role_based_admin(monkeypatch):
    import core
    store = _Store()
    store.set_admins(["promoted@hosp.org"])
    monkeypatch.setattr(core, "OWNER_EMAIL", "owner@hosp.org", raising=False)
    monkeypatch.setattr(core, "ADMIN_EMAILS", {"env@hosp.org"}, raising=False)
    monkeypatch.setattr(core, "OPEN_ACCESS", False, raising=False)
    monkeypatch.setattr(core, "get_store", lambda: store, raising=False)
    assert core.is_admin("owner@hosp.org")        # tier 1
    assert core.is_admin("env@hosp.org")          # tier 2
    assert core.is_admin("promoted@hosp.org")     # tier 3
    assert not core.is_admin("nurse@hosp.org")    # role-based again: not an admin


# ── the gates ─────────────────────────────────────────────────────────────────────────────────

def test_require_admin_opens_for_authenticated_but_not_anon(owned):
    from routes.system import _require_admin
    assert _require_admin(_req("nurse@hosp.org")) is None   # any signed-in user passes
    with pytest.raises(HTTPException) as ei:
        _require_admin(_req(""))                            # unauthenticated is refused
    assert ei.value.status_code == 403


def test_require_owner_blocks_non_owner(owned):
    from routes.system import _require_owner
    assert _require_owner(_req("owner@hosp.org")) is None
    with pytest.raises(HTTPException) as ei:
        _require_owner(_req("nurse@hosp.org"))
    assert ei.value.status_code == 403


# ── the destructive few stay owner-only (a signed-in non-owner is refused at the gate) ──────────

@pytest.mark.parametrize("call", [
    lambda: __import__("routes.system", fromlist=["admin_reset"]).admin_reset(
        request=_req("nurse@hosp.org"), scope="all", confirm=True),
    lambda: __import__("routes.system", fromlist=["set_allowlist"]).set_allowlist(
        {"emails": []}, request=_req("nurse@hosp.org")),
    lambda: __import__("routes.system", fromlist=["invite_tester"]).invite_tester(
        {"email": "x@y.com"}, request=_req("nurse@hosp.org")),
    lambda: __import__("routes.disposition", fromlist=["execute_policy"]).execute_policy(
        "p1", _req("nurse@hosp.org")),
    lambda: __import__("routes.disposition", fromlist=["approve_disposition"]).approve_disposition(
        "a1", _req("nurse@hosp.org"), execute=True),
])
def test_destructive_actions_are_owner_only(owned, call):
    with pytest.raises(HTTPException) as ei:
        call()
    assert ei.value.status_code == 403          # refused at the owner gate, before any effect
