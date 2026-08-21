"""In-app admin management: the owner promotes/demotes additional Platform Admins from Settings.

Three tiers of admin (GET /admin/admins): the immutable `owner` (ACP_OWNER_EMAIL), permanent
`env_admins` (ACP_ADMIN_EMAILS, set at deploy), and the owner-managed `admins` set (store, edited
here). `core.is_admin` unions all three. Under test: is_admin consults the store; managing the set is
OWNER-only (an admin cannot grant admin, nor remove the owner); and the PUT keeps the owner/env grants
out of the managed set so it stays exactly "who the owner promoted."
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))


class _Store:
    """Setting-backed store double — get_admins/set_admins use the real get_setting/set_setting
    machinery, exactly as the production Store does."""
    def __init__(self):
        self.settings = {}
        self.decisions = []

    def get_setting(self, key, default=None):
        return self.settings.get(key, default)

    def set_setting(self, key, value):
        self.settings[key] = value

    def log_decision(self, who, what, **kw):
        self.decisions.append((who, what, kw.get("detail", "")))

    def get_admins(self):
        raw = self.get_setting("admin_emails", "") or ""
        return [e.strip().lower() for e in raw.split(",") if e.strip()]

    def set_admins(self, emails):
        clean = sorted({e.strip().lower() for e in (emails or []) if e and "@" in e})
        self.set_setting("admin_emails", ",".join(clean))
        return clean


@pytest.fixture
def env(monkeypatch):
    import core
    import routes.system as s
    store = _Store()
    monkeypatch.setattr(core, "OWNER_EMAIL", "owner@hosp.org", raising=False)
    monkeypatch.setattr(core, "ADMIN_EMAILS", {"env-admin@hosp.org"}, raising=False)
    # This file exercises the ROLE-BASED admin union (owner / env / owner-promoted store set) and its
    # promote/demote flow — which is precisely the OPEN_ACCESS=off behaviour. With open access on
    # (the default) every authenticated user is an admin, so the union/demote distinctions collapse;
    # that behaviour is covered separately in test_open_access_model.py. Pin the flag off here.
    monkeypatch.setattr(core, "OPEN_ACCESS", False, raising=False)
    monkeypatch.setattr(core, "store", store, raising=False)
    monkeypatch.setattr(core, "get_store", lambda: store, raising=False)
    return s, core, store


def _req(email):
    return SimpleNamespace(state=SimpleNamespace(user_email=email))


def test_is_admin_unions_owner_env_and_store(env):
    _, core, store = env
    store.set_admins(["deva@hosp.org"])
    assert core.is_admin("owner@hosp.org")       # tier 1: owner
    assert core.is_admin("env-admin@hosp.org")   # tier 2: env
    assert core.is_admin("deva@hosp.org")        # tier 3: owner-promoted (store)
    assert not core.is_admin("nurse@hosp.org")   # none


def test_is_owner_is_strict(env):
    _, core, _ = env
    assert core.is_owner("owner@hosp.org")
    assert not core.is_owner("env-admin@hosp.org")   # an admin is NOT the owner
    assert not core.is_owner("deva@hosp.org")


def test_get_admins_reports_three_tiers(env):
    s, core, store = env
    store.set_admins(["deva@hosp.org"])
    out = s.get_admins()
    assert out["owner"] == "owner@hosp.org"
    assert out["env_admins"] == ["env-admin@hosp.org"]
    assert out["admins"] == ["deva@hosp.org"]


def test_owner_can_promote_an_admin(env):
    s, core, store = env
    out = s.set_admins({"emails": ["deva@hosp.org"]}, request=_req("owner@hosp.org"))
    assert out["admins"] == ["deva@hosp.org"]
    assert core.is_admin("deva@hosp.org")          # promotion takes effect
    assert store.decisions and store.decisions[-1][1] == "settings.admins"


def test_a_non_owner_admin_cannot_manage_admins(env):
    s, core, store = env
    store.set_admins(["deva@hosp.org"])            # deva is an admin...
    with pytest.raises(HTTPException) as ei:
        s.set_admins({"emails": ["mallory@hosp.org"]}, request=_req("deva@hosp.org"))
    assert ei.value.status_code == 403             # ...but still can't grant admin
    with pytest.raises(HTTPException) as ei2:
        s.set_admins({"emails": []}, request=_req("nurse@hosp.org"))
    assert ei2.value.status_code == 403


def test_put_keeps_owner_and_env_admins_out_of_the_managed_set(env):
    s, core, store = env
    # Even if the client sends the owner and an env-admin, they must not land in the store set —
    # they're grants from elsewhere and are never removable via this path.
    out = s.set_admins({"emails": ["owner@hosp.org", "env-admin@hosp.org", "deva@hosp.org"]},
                       request=_req("owner@hosp.org"))
    assert out["admins"] == ["deva@hosp.org"]


def test_demote_removes_admin_rights(env):
    s, core, store = env
    s.set_admins({"emails": ["deva@hosp.org"]}, request=_req("owner@hosp.org"))
    assert core.is_admin("deva@hosp.org")
    s.set_admins({"emails": []}, request=_req("owner@hosp.org"))
    assert not core.is_admin("deva@hosp.org")      # demotion takes effect
