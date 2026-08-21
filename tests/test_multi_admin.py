"""Multi-admin: more than one email can be a Platform Admin (ACP_ADMIN_EMAILS), not just the single
protected ACP_OWNER_EMAIL.

`core.is_admin` is the single source of truth both the SPA flag (`is_scope_owner`, emitted on /me and
/config) and the API gate (`system._require_admin`) consult, so the UI and the server can never
disagree about who may edit scope / platform settings / access. Under test: the owner and every
ACP_ADMIN_EMAILS entry are admins; a merely allow-listed user is not; admins are always admitted by
email_allowed; and _require_admin 403s a non-admin but passes an additional admin.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))


@pytest.fixture
def owned(monkeypatch):
    """Owner = owner@hosp.org, with two additional admins. Case-insensitive on purpose."""
    import core
    monkeypatch.setattr(core, "OWNER_EMAIL", "owner@hosp.org", raising=False)
    monkeypatch.setattr(core, "ADMIN_EMAILS", {"deva@hosp.org", "sam@hosp.org"}, raising=False)
    # These tests exercise the ROLE-BASED admin union + gate (owner / additional admins vs a
    # non-admin). That distinction only exists with the open-access flag off; with it on (the
    # default) every authenticated user is an admin. Pin it off here; open access is covered in
    # test_open_access_model.py.
    monkeypatch.setattr(core, "OPEN_ACCESS", False, raising=False)
    return core


def test_owner_and_additional_admins_are_admins(owned):
    assert owned.is_admin("owner@hosp.org")
    assert owned.is_admin("deva@hosp.org")
    assert owned.is_admin("sam@hosp.org")


def test_admin_check_is_case_insensitive(owned):
    assert owned.is_admin("DEVA@HOSP.ORG")
    assert owned.is_admin("  Owner@Hosp.org ")


def test_a_non_admin_is_not_an_admin(owned):
    assert not owned.is_admin("nurse@hosp.org")
    assert not owned.is_admin(None)
    assert not owned.is_admin("")


def test_is_scope_owner_delegates_to_is_admin(owned):
    # The SPA reads is_scope_owner to show the scope editor; an additional admin must get it.
    assert owned.is_scope_owner("deva@hosp.org")
    assert not owned.is_scope_owner("nurse@hosp.org")


def test_no_owner_configured_makes_everyone_admin(monkeypatch):
    # local dev / demo / no-auth: _require_admin is a no-op, so everyone may edit.
    import core
    monkeypatch.setattr(core, "OWNER_EMAIL", "", raising=False)
    monkeypatch.setattr(core, "ADMIN_EMAILS", set(), raising=False)
    assert core.is_admin("anyone@anywhere.org")
    assert core.is_scope_owner(None)


def test_email_allowed_admits_an_admin_not_otherwise_listed(owned, monkeypatch):
    # An admin who is neither on the allowlist nor at an allowed domain must still sign in —
    # an admin who could not authenticate would be a contradiction.
    class _EmptyAllowlistStore:
        def get_allowlist(self):
            return set()
    monkeypatch.setattr(owned, "store", _EmptyAllowlistStore(), raising=False)
    monkeypatch.setattr(owned, "ALLOWED_DOMAINS", [], raising=False)
    monkeypatch.setattr(owned, "get_store", lambda: _EmptyAllowlistStore(), raising=False)
    assert owned.email_allowed("deva@hosp.org")     # additional admin
    assert owned.email_allowed("owner@hosp.org")    # the owner
    assert not owned.email_allowed("nurse@hosp.org")  # neither admin, allowlist, nor domain


def _req(email):
    return SimpleNamespace(state=SimpleNamespace(user_email=email))


def test_require_admin_passes_owner_and_admin_403s_others(owned):
    import routes.system as sysmod
    from fastapi import HTTPException

    sysmod._require_admin(_req("owner@hosp.org"))   # owner: no raise
    sysmod._require_admin(_req("deva@hosp.org"))    # additional admin: no raise
    with pytest.raises(HTTPException) as ei:
        sysmod._require_admin(_req("nurse@hosp.org"))
    assert ei.value.status_code == 403


def test_require_admin_is_noop_without_owner(monkeypatch):
    import core
    import routes.system as sysmod
    monkeypatch.setattr(core, "OWNER_EMAIL", "", raising=False)
    sysmod._require_admin(_req("anyone@anywhere.org"))   # no owner configured → no raise
