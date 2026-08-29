"""Dedicated app-only Graph credential for the scheduled SharePoint sweep (PRD Phase 3).

Mirrors tests/test_invites.py's structure deliberately — same load-bearing properties: (a) the
feature is DARK until the app credential AND the drive to sync are both configured — no Graph
call, no permission held; (b) it uses the app's OWN identity (client credentials), never a
signed-in user's; (c) it is a SEPARATE credential from api/invites.py's, never reused.
"""
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import sp_sync  # noqa: E402

_CREDS = ("ACP_SP_SYNC_TENANT_ID", "ACP_SP_SYNC_CLIENT_ID", "ACP_SP_SYNC_CLIENT_SECRET",
         "ACP_SP_SYNC_DRIVE_ID")


class _Resp:
    def __init__(self, status=200, payload=None):
        self.status_code, self._payload = status, payload or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


def _inject_httpx(monkeypatch, post_impl):
    m = types.ModuleType("httpx")
    m.post = post_impl
    monkeypatch.setitem(sys.modules, "httpx", m)


def _configure(monkeypatch):
    monkeypatch.setenv("ACP_SP_SYNC_TENANT_ID", "tid")
    monkeypatch.setenv("ACP_SP_SYNC_CLIENT_ID", "cid")
    monkeypatch.setenv("ACP_SP_SYNC_CLIENT_SECRET", "sec")
    monkeypatch.setenv("ACP_SP_SYNC_DRIVE_ID", "drv-1")


# ── dark-until-configured ─────────────────────────────────────────────────────────────────────

def test_configured_only_when_all_four_settings_present(monkeypatch):
    for k in _CREDS:
        monkeypatch.delenv(k, raising=False)
    assert sp_sync.sp_sync_configured() is False
    monkeypatch.setenv("ACP_SP_SYNC_TENANT_ID", "t")
    monkeypatch.setenv("ACP_SP_SYNC_CLIENT_ID", "c")
    monkeypatch.setenv("ACP_SP_SYNC_CLIENT_SECRET", "s")
    assert sp_sync.sp_sync_configured() is False        # drive id still missing → still dark
    monkeypatch.setenv("ACP_SP_SYNC_DRIVE_ID", "d")
    assert sp_sync.sp_sync_configured() is True


def test_sync_drive_id_is_empty_when_unset(monkeypatch):
    monkeypatch.delenv("ACP_SP_SYNC_DRIVE_ID", raising=False)
    assert sp_sync.sync_drive_id() == ""


def test_sync_drive_id_returns_the_configured_value(monkeypatch):
    monkeypatch.setenv("ACP_SP_SYNC_DRIVE_ID", "drv-42")
    assert sp_sync.sync_drive_id() == "drv-42"


# ── the app token ────────────────────────────────────────────────────────────────────────────

def test_app_token_uses_client_credentials_with_the_default_scope(monkeypatch):
    _configure(monkeypatch)
    calls = {}

    def fake_post(url, **kw):
        calls["url"] = url
        calls["data"] = kw.get("data")
        return _Resp(200, {"access_token": "APP_TOKEN"})

    _inject_httpx(monkeypatch, fake_post)
    assert sp_sync.app_token() == "APP_TOKEN"
    assert calls["url"].endswith("/tid/oauth2/v2.0/token")
    assert calls["data"]["grant_type"] == "client_credentials"
    assert calls["data"]["scope"] == "https://graph.microsoft.com/.default"
    assert calls["data"]["client_id"] == "cid"
    assert calls["data"]["client_secret"] == "sec"


def test_app_token_failure_propagates(monkeypatch):
    _configure(monkeypatch)
    _inject_httpx(monkeypatch, lambda url, **kw: _Resp(403, {"error": "consent required"}))
    with pytest.raises(RuntimeError):
        sp_sync.app_token()


# ── independence from the invite app's credential ───────────────────────────────────────────

def test_never_reads_the_invite_apps_env_vars(monkeypatch):
    """Two independent single-purpose app registrations — this must never fall back to the
    invite app's credential (api/invites.py, User.Invite.All) even if only that one is set."""
    for k in _CREDS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ACP_INVITE_TENANT_ID", "t")
    monkeypatch.setenv("ACP_INVITE_CLIENT_ID", "c")
    monkeypatch.setenv("ACP_INVITE_CLIENT_SECRET", "s")
    assert sp_sync.sp_sync_configured() is False


def test_module_never_reads_the_invite_env_var_names_in_code():
    # Strip docstrings/comments first: the module's own prose deliberately explains its
    # relationship to ACP_INVITE_* (two independent credentials) — that explanation living in
    # the docstring is fine; what must never happen is the CODE reading that variable name.
    import re
    raw = Path(__file__).resolve().parent.parent.joinpath("api", "sp_sync.py").read_text()
    code = re.sub(r'#.*', '', re.sub(r'"""(?:.|\n)*?"""', '', raw))
    assert "ACP_INVITE_" not in code
