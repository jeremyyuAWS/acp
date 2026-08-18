"""Tester guest-invite (ADR 0033) — opt-in, least-privilege Entra B2B invite.

The load-bearing properties: (a) the feature is DARK until the app credential is configured — no
Graph call, no permission held; (b) it sends a GUEST INVITE (User.Invite.All), never a user-create;
(c) it uses the app's OWN identity (client credentials), not a user's delegated token; (d) Graph's
error (e.g. missing admin consent) is surfaced readably. The endpoint is owner-gated and auto-adds
the invited email to the allowlist.
"""
import re
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import invites  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
_CREDS = ("ACP_INVITE_TENANT_ID", "ACP_INVITE_CLIENT_ID", "ACP_INVITE_CLIENT_SECRET")


class _Resp:
    def __init__(self, status=200, payload=None, text=""):
        self.status_code, self._payload, self.text = status, payload or {}, text

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


def _inject_httpx(monkeypatch, post_impl):
    """Inject a fake `httpx` so the lazy `import httpx` inside invites picks it up — the Graph path
    is testable with no real httpx and no network."""
    m = types.ModuleType("httpx")
    m.post = post_impl
    monkeypatch.setitem(sys.modules, "httpx", m)


def _configure(monkeypatch):
    monkeypatch.setenv("ACP_INVITE_TENANT_ID", "tid")
    monkeypatch.setenv("ACP_INVITE_CLIENT_ID", "cid")
    monkeypatch.setenv("ACP_INVITE_CLIENT_SECRET", "sec")


# ── dark-until-configured ─────────────────────────────────────────────────────────────────────
def test_configured_only_when_all_three_creds_present(monkeypatch):
    for k in _CREDS:
        monkeypatch.delenv(k, raising=False)
    assert invites.invite_configured() is False
    monkeypatch.setenv("ACP_INVITE_TENANT_ID", "t")
    monkeypatch.setenv("ACP_INVITE_CLIENT_ID", "c")
    assert invites.invite_configured() is False        # secret still missing → still dark
    monkeypatch.setenv("ACP_INVITE_CLIENT_SECRET", "s")
    assert invites.invite_configured() is True


def test_unconfigured_send_raises_before_any_http(monkeypatch):
    for k in _CREDS:
        monkeypatch.delenv(k, raising=False)
    # No httpx injected: if it tried to call Graph it would fail differently. It must refuse first.
    with pytest.raises(RuntimeError, match="not configured"):
        invites.send_guest_invite("x@y.com")


# ── the Graph invite path ─────────────────────────────────────────────────────────────────────
def test_send_invite_is_a_guest_invite_with_an_app_token(monkeypatch):
    _configure(monkeypatch)
    calls = {}

    def fake_post(url, **kw):
        if url.endswith("/oauth2/v2.0/token"):
            calls["token"] = kw
            return _Resp(200, {"access_token": "APP_TOKEN"})
        calls["url"] = url
        calls["body"] = kw.get("json")
        calls["headers"] = kw.get("headers")
        return _Resp(200, {"inviteRedeemUrl": "https://redeem", "status": "PendingAcceptance",
                           "invitedUser": {"id": "guest-1"}})

    _inject_httpx(monkeypatch, fake_post)
    out = invites.send_guest_invite("Tester@Example.com")

    assert out == {"redemption_url": "https://redeem", "invited_user_id": "guest-1",
                   "status": "PendingAcceptance"}
    # a GUEST INVITE, not a user-create; app's own identity (client credentials, .default scope)
    assert calls["url"].endswith("/invitations")
    assert calls["body"]["invitedUserEmailAddress"] == "Tester@Example.com"
    assert calls["headers"]["Authorization"] == "Bearer APP_TOKEN"
    assert calls["token"]["data"]["grant_type"] == "client_credentials"
    assert calls["token"]["data"]["scope"] == "https://graph.microsoft.com/.default"


def test_graph_error_is_surfaced_readably(monkeypatch):
    _configure(monkeypatch)

    def fake_post(url, **kw):
        if url.endswith("/oauth2/v2.0/token"):
            return _Resp(200, {"access_token": "t"})
        return _Resp(403, {"error": {"message": "Insufficient privileges: User.Invite.All not consented"}})

    _inject_httpx(monkeypatch, fake_post)
    with pytest.raises(RuntimeError, match="User.Invite.All"):
        invites.send_guest_invite("x@y.com")


# ── least privilege, pinned in source ─────────────────────────────────────────────────────────
def test_invites_module_invites_a_guest_never_creates_a_user():
    # Strip docstrings first: the module's prose says "deliberately NOT User.ReadWrite.All", so a
    # naive substring search matches the explanation, not the code. Same trap the repo already hit
    # (see test_control_plane_route.py) — assert against CODE, not comments.
    raw = (ROOT / "api" / "invites.py").read_text()
    code = re.sub(r'#.*', '', re.sub(r'"""(?:.|\n)*?"""', '', raw))
    assert "/invitations" in code                      # the one Graph write it makes
    assert "User.ReadWrite" not in code                # never the directory-write scope
    assert not re.search(r"/users\b", code)            # never the user-create endpoint


# ── endpoint wiring (source-level, matching the repo's route-test style) ───────────────────────
def test_invite_endpoint_is_owner_gated_dark_and_writes_the_allowlist():
    src = (ROOT / "api" / "routes" / "system.py").read_text()
    assert '@router.post("/admin/invite")' in src
    body = re.search(r"def invite_tester\(.*?(?=\n@router|\Z)", src, re.S).group(0)
    assert "_require_admin(request)" in body                       # owner-only
    assert "invites.invite_configured()" in body and "409" in body  # ships dark → 409
    assert "send_guest_invite" in body                             # sends the invite
    assert "set_allowlist" in body                                 # auto-adds to the allowlist
    # the UI learns whether to show the button from the allowlist payload
    assert '"invite_enabled": invites.invite_configured()' in src
