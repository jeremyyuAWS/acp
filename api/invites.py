"""Entra B2B guest invite (ADR 0033) — opt-in, least-privilege tester onboarding.

Sends a Microsoft Graph guest invitation so an external tester can sign in with their OWN identity,
then the caller adds them to the ACP allowlist. Deliberately NOT `User.ReadWrite.All` / user-create:
the only Graph permission this needs is `User.Invite.All`, which can invite an external guest and
nothing else (no directory read, no member create, no password reset).

Ships DARK: with the `ACP_INVITE_*` app credential unset, `invite_configured()` is False, the API
endpoint 409s, and the Settings button hides — behaviour is exactly today's hand-edited allowlist.
The credential is a DEDICATED app registration (client-credentials flow), never the signed-in user's
delegated token, and its secret belongs in Key Vault. See docs/adr/0033-tester-guest-invite.md.
"""
from __future__ import annotations

import os

GRAPH = "https://graph.microsoft.com/v1.0"
_LOGIN = "https://login.microsoftonline.com"


def _cfg(name: str) -> str:
    return (os.environ.get(name, "") or "").strip()


def invite_configured() -> bool:
    """True only when the dedicated invite app credential is fully configured. When False the whole
    feature is inert (endpoint 409s, UI hides) — no Graph permission is held."""
    return bool(_cfg("ACP_INVITE_TENANT_ID") and _cfg("ACP_INVITE_CLIENT_ID")
                and _cfg("ACP_INVITE_CLIENT_SECRET"))


def _redirect_url() -> str:
    """Where a redeemed guest lands. The ACP app URL when set, else the generic My Apps portal
    (always a valid `inviteRedirectUrl`)."""
    return _cfg("ACP_INVITE_REDIRECT_URL") or "https://myapps.microsoft.com"


def _app_token() -> str:
    """A Graph app token via client credentials (the invite app's own identity, not a user)."""
    import httpx
    tenant = _cfg("ACP_INVITE_TENANT_ID")
    r = httpx.post(
        f"{_LOGIN}/{tenant}/oauth2/v2.0/token",
        data={
            "client_id": _cfg("ACP_INVITE_CLIENT_ID"),
            "client_secret": _cfg("ACP_INVITE_CLIENT_SECRET"),
            "grant_type": "client_credentials",
            "scope": "https://graph.microsoft.com/.default",
        },
        timeout=20,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def send_guest_invite(email: str, redirect_url: str | None = None) -> dict:
    """Invite `email` as an Entra B2B guest. Returns
    {redemption_url, invited_user_id, status}. Raises RuntimeError with a readable message when the
    feature is unconfigured or Graph rejects the invite — the caller turns that into a 4xx/5xx."""
    if not invite_configured():
        raise RuntimeError("guest invite is not configured (ACP_INVITE_* unset)")
    import httpx
    token = _app_token()
    body = {
        "invitedUserEmailAddress": email,
        "inviteRedirectUrl": redirect_url or _redirect_url(),
        "sendInvitationMessage": True,
    }
    r = httpx.post(f"{GRAPH}/invitations", json=body,
                   headers={"Authorization": f"Bearer {token}"}, timeout=30)
    if r.status_code >= 400:
        # Surface Graph's own message (e.g. missing admin consent for User.Invite.All) rather than a
        # bare status, so the operator can fix the app registration.
        try:
            msg = (r.json().get("error") or {}).get("message") or r.text
        except Exception:
            msg = r.text
        raise RuntimeError(f"Graph rejected the invite ({r.status_code}): {msg}")
    d = r.json()
    return {
        "redemption_url": d.get("inviteRedeemUrl"),
        "invited_user_id": (d.get("invitedUser") or {}).get("id"),
        "status": d.get("status"),
    }
