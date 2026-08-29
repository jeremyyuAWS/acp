"""Dedicated app-only Microsoft Graph credential for the scheduled SharePoint sweep (PRD Phase 3
incremental connector synchronization).

Ships DARK: with `ACP_SP_SYNC_*` unset, `sp_sync_configured()` is False and the scheduled
sweep's SharePoint path is exactly as inert as it is today — every per-request SharePoint call
in this codebase needs a live user token (api/scanner.py's `_sp_list`/`_sp_get`), and the
scheduled sweep has never had one to give it, so an unattended SharePoint sweep has never
actually worked. This module exists to make that possible, opt-in.

The credential is a DEDICATED app registration (client-credentials flow), never the invite
app's (api/invites.py, ADR 0033 — that one is scoped to User.Invite.All and nothing else) and
never a signed-in user's delegated token. Its permission need is `Sites.Read.All` (application),
granted with tenant admin consent — least-privilege for read-only sync, the same posture ADR
0033 established for guest invites. Its secret belongs in Key Vault. Mirrors api/invites.py's
ACP_INVITE_* pattern exactly, deliberately: two independent single-purpose app registrations
are safer than one shared credential whose blast radius grows with every feature that reuses it.
"""
from __future__ import annotations

import os

_LOGIN = "https://login.microsoftonline.com"


def _cfg(name: str) -> str:
    return (os.environ.get(name, "") or "").strip()


def sp_sync_configured() -> bool:
    """True only when the dedicated sync app credential AND the drive to sync are both set. When
    False the scheduled sweep's SharePoint path is fully inert — no Graph permission is ever
    exercised, and the sweep behaves exactly as it does today (fails with the same
    'no unattended credential' PermissionError it always has)."""
    return bool(_cfg("ACP_SP_SYNC_TENANT_ID") and _cfg("ACP_SP_SYNC_CLIENT_ID")
                and _cfg("ACP_SP_SYNC_CLIENT_SECRET") and _cfg("ACP_SP_SYNC_DRIVE_ID"))


def sync_drive_id() -> str:
    """The single Graph drive id the scheduled sweep syncs — e.g. a site's default document
    library. Scoped to exactly one drive deliberately: enumerating a whole site's libraries (or
    every site in a tenant) needs its own delta cursor per library and its own Sites-listing
    calls, a bigger reconstruction problem than this feature takes on. Empty when unset; callers
    must check sp_sync_configured() first."""
    return _cfg("ACP_SP_SYNC_DRIVE_ID")


def app_token() -> str:
    """A Graph app token via client credentials (this dedicated app's own identity, never a
    signed-in user's). Raises if unconfigured — callers must check sp_sync_configured() first,
    the same discipline api/invites.py's _app_token() establishes."""
    import httpx
    tenant = _cfg("ACP_SP_SYNC_TENANT_ID")
    r = httpx.post(
        f"{_LOGIN}/{tenant}/oauth2/v2.0/token",
        data={
            "client_id": _cfg("ACP_SP_SYNC_CLIENT_ID"),
            "client_secret": _cfg("ACP_SP_SYNC_CLIENT_SECRET"),
            "grant_type": "client_credentials",
            "scope": "https://graph.microsoft.com/.default",
        },
        timeout=20,
    )
    r.raise_for_status()
    return r.json()["access_token"]
