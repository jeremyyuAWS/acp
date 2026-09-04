"""Why Microsoft Graph refused, and what this tenant will actually answer (Phase 4 / Phase 6).

TWO QUESTIONS AN ONBOARDING RUN HAS TO ANSWER BEFORE IT IS WORTH STARTING, and this repo answered
neither.

**Whose problem is this 403?** Every Graph refusal in this codebase produced one message: grant
`Sites.Read.All` on the app registration, with tenant admin consent. That is the right answer when
the scope is missing and the WRONG answer whenever it is not — and when it is wrong it is worse
than silence, because it sends a tenant admin to re-consent a permission that is already consented
while the actual blocker (this user is not a member of that site) goes unexamined. A pilot that
loses a day to that has lost it to the diagnosis, not the permission. `Sites.Read.All` is a
tenant-wide grant an admin makes once; site membership is per user and per site and is the site
owner's to fix. Different person, different screen, different day.

Worse, a 401 got the same message. A 401 is Graph rejecting the TOKEN — expired, wrong audience,
signed out — and no amount of admin consent fixes it. The one refusal a signed-in user can resolve
themselves in five seconds was the one being escalated to their IT department.

**What will this tenant actually hand back?** The walk asks for the wide `$select` and the
`listItem` expansion and falls back when they are refused (scanner._sp_children_url's tiers), so a
tenant that refuses them produces a complete, correct, and quietly metadata-free estate. Nothing
says so until a scan has finished and every content type reads `unavailable` per document. Three
bounded requests against one library answer it before a thirty-site run is committed to.

THE CLAIMS ARE READ FROM THE TOKEN, AND THAT IS DIAGNOSTIC ONLY. `token_scopes` base64-decodes a
JWT payload and does NOT verify its signature. That is sound for exactly one purpose — explaining a
refusal Graph has ALREADY made — and unsound for every other: nothing here may gate access, decide
what a caller may read, or be trusted as proof of anything. The authority on what this token can do
is Graph's own answer, which we already have; these claims only say which of several explanations
for that answer is the plausible one. A forged token changes the explanation and changes nothing
else, because the request it explains has already failed.
"""
from __future__ import annotations

import base64
import binascii
import json

#: The delegated permission a SharePoint SITE needs. `Files.Read.All` alone reaches only the
#: signed-in user's own OneDrive, which is why a tenant can look correctly configured right up to
#: the moment a site id is used.
SITES_SCOPE = "Sites.Read.All"

#: Whose problem each verdict is. Named rather than boolean because "blocked" is not a state
#: anybody can act on and "the tenant admin has to grant a scope" is.
TENANT_ADMIN = "tenant_admin"
SITE_OWNER = "site_owner"
SIGNED_IN_USER = "signed_in_user"
UNKNOWN_OWNER = "unknown"


def _b64url(segment: str) -> bytes:
    """One JWT segment. Padding is stripped in the wire format and `b64decode` insists on it."""
    return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))


def token_scopes(token: str | None) -> tuple[frozenset[str] | None, str | None]:
    """What the token SAYS was consented, as (scopes, why_not) — exactly one is None.

    A delegated Graph token carries `scp` (a space-separated string); an application token carries
    `roles` (a list). Both are read: the sync worker uses an app-only token and hits the same
    refusals, and reporting "no scopes found" for a perfectly good app token would send the reader
    down the wrong path — the failure this whole module exists to stop.

    Returns `(None, reason)` when the claims cannot be read at all, and the reason is meant to be
    shown: "opaque token" and "no scope claim" are different facts, and a caller that collapses
    them into "unknown" cannot tell an ordinary configuration from a token issued for a different
    resource. NEVER raises — this runs on a path that is already failing.

    DIAGNOSTIC ONLY. The signature is not verified; see this module's docstring for why that is
    sound here and nowhere else.
    """
    if not token or not isinstance(token, str):
        return None, "no token"
    parts = token.split(".")
    if len(parts) != 3:
        # A Graph access token is a JWT today, but Azure can issue an opaque one, and a caller
        # holding one is not misconfigured. Say what was seen rather than implying a fault.
        return None, "the token is not a JWT, so its scopes cannot be read from it"
    try:
        claims = json.loads(_b64url(parts[1]))
    except (ValueError, binascii.Error, UnicodeDecodeError):
        return None, "the token's claims could not be decoded"
    if not isinstance(claims, dict):
        return None, "the token's claims are not an object"
    scp = claims.get("scp")
    roles = claims.get("roles")
    found: set[str] = set()
    if isinstance(scp, str):
        found.update(s for s in scp.split() if s)
    elif isinstance(scp, list):
        # Undocumented but observed: some issuers emit `scp` as a list. Accepting both costs one
        # branch; accepting only the documented one reports a fully-scoped token as unscoped.
        found.update(str(s) for s in scp if s)
    if isinstance(roles, list):
        found.update(str(r) for r in roles if r)
    elif isinstance(roles, str):
        found.update(r for r in roles.split() if r)
    if not found:
        return None, "the token carries no scope or role claim"
    return frozenset(found), None


def _has(granted: frozenset[str] | None, scope: str) -> bool:
    """Case-insensitively, and tolerating the fully-qualified spelling Azure sometimes emits
    (`https://graph.microsoft.com/Sites.Read.All`). A scope match that missed on capitalisation
    would produce the exact wrong diagnosis this module is about."""
    if not granted:
        return False
    want = scope.lower()
    return any(g.lower() == want or g.lower().endswith("/" + want) for g in granted)


def diagnose_refusal(status: int, *, token: str | None = None,
                    on_site: bool | None = None) -> dict:
    """Why Graph refused, and whose problem it is.

    `on_site` says whether the request named a SharePoint SITE (or something inside one) rather
    than the signed-in user's own OneDrive, and **None means the caller does not know** — which is
    the honest answer for `_sp_get`, whose argument is often a Graph-issued deltaLink whose target
    is not recoverable from its shape. Guessing it from the URL was the first version of this and
    it was the same class of mistake the function exists to fix: a plausible inference presented
    as a diagnosis. The unknown branch names both readings and leads with the one fact that is
    true either way — what the token carries.

    Returns `{"owner", "message", "missing_scope", "scopes_read"}`. `message` is a complete
    sentence for a human, because it is rendered verbatim in the per-site exception report and the
    scan log — the two places somebody reads while trying to get a pilot moving.
    """
    granted, why_not = token_scopes(token)
    scopes_read = sorted(granted) if granted else None

    if status == 401:
        # THE TOKEN, not the tenant. Graph rejected the credential itself — expired, revoked,
        # issued for another resource, or the user signed out in another tab. No consent changes
        # it, and the person who can fix it is the one holding the browser. This refusal used to
        # be reported as a missing tenant-admin grant, which is the one diagnosis that cannot be
        # right for it.
        return {"owner": SIGNED_IN_USER, "missing_scope": None, "scopes_read": scopes_read,
                "message": ("Microsoft Graph rejected the sign-in token (401). It has expired or "
                            "was issued for a different resource — sign in with Microsoft again. "
                            "This is not a permissions grant and admin consent will not change "
                            "it.")}

    if on_site is False:
        return {"owner": SIGNED_IN_USER, "missing_scope": None, "scopes_read": scopes_read,
                "message": (f"Microsoft Graph denied access to this OneDrive item (403). "
                            f"{SITES_SCOPE} is not involved — a personal drive does not need it — "
                            f"so the signed-in account simply cannot read this item; check that "
                            f"it still exists and is shared with them.")}

    where = ("this SharePoint site" if on_site
             else "this SharePoint or OneDrive resource")

    if granted is None:
        # Both explanations stand. Say both, and say which fact is missing — a reader who knows
        # the scopes could not be read knows to check the app registration first rather than
        # treating this as a settled answer.
        return {"owner": UNKNOWN_OWNER, "missing_scope": None, "scopes_read": None,
                "message": (f"Microsoft Graph denied access to {where} (403), and {why_not}, so "
                            f"this is either a missing {SITES_SCOPE} grant on the app "
                            f"registration (tenant admin consent) or a site the signed-in account "
                            f"is not a member of. Check the app registration first.")}

    if not _has(granted, SITES_SCOPE):
        return {"owner": TENANT_ADMIN, "missing_scope": SITES_SCOPE, "scopes_read": scopes_read,
                "message": (f"Microsoft Graph denied access to {where} (403), and the sign-in "
                            f"token does not carry {SITES_SCOPE}. SharePoint sites need that "
                            f"delegated permission on the Azure app registration, granted with "
                            f"tenant admin consent; Files.Read.All alone only reaches the "
                            f"signed-in user's own OneDrive.")}

    # The grant is there and the answer is still no. This is the case that had no diagnosis at
    # all, and it is the common one in a large tenant: a delegated Sites.Read.All is bounded by
    # what the SIGNED-IN USER can see, so a private or restricted site refuses a perfectly
    # configured app. The remedy is site membership, from the site's own owner — a different
    # person and a different screen from the admin the old message sent everybody to.
    return {"owner": SITE_OWNER, "missing_scope": None, "scopes_read": scopes_read,
            "message": (f"Microsoft Graph denied access to {where} (403) even though the sign-in "
                        f"token carries {SITES_SCOPE}. The app registration is configured; a "
                        f"delegated grant is still bounded by what the signed-in account can see, "
                        f"so that account is not a member of this site. Ask the site owner to add "
                        f"them, or scan a site they can already open.")}


#: What each walk tier costs when the tenant refuses the one above it. Keyed by the tier that
#: ANSWERED, so a reader sees what they get rather than what they lost.
TIER_MEANING = {
    0: "content types, managed columns, versions, check-out state and retention labels",
    1: "content types, managed columns, versions and check-out state, but not retention labels",
    2: "file names, sizes and timestamps only — no SharePoint-native metadata",
}


def probe_metadata_tiers(token: str, drive_id: str | None, *, get=None) -> dict:
    """Which of the walk's three request tiers this drive actually answers.

    THE PROBE ASKS WHAT THE WALK ASKS — `scanner._sp_children_url`, the same builder, so a tenant
    that refuses the expansion refuses the identical string here. A probe that composed its own
    request would prove something about the probe; this repo has paid for that mistake before
    (CLAUDE.md, the .pdf ground-truth corpus), and the whole value of an onboarding check is that
    it predicts the run.

    At most THREE requests, each capped at one item: the question is which shapes are accepted,
    and it is settled by the first page. Returns `{"tier", "reads", "refused", "error"}` —
    `refused` lists the tiers this drive turned down, which is the part an operator acts on.

    `get` is the seam the tests use; production passes None and gets `scanner._sp_get`.
    """
    import scanner
    fetch = get or scanner._sp_get
    root = f"{scanner.GRAPH}/drives/{drive_id}" if drive_id else f"{scanner.GRAPH}/me/drive"
    refused: list[int] = []
    for tier in (0, 1, 2):
        url = scanner._sp_children_url(root, "root", tier).replace("$top=200", "$top=1")
        try:
            fetch(token, url)
        except PermissionError:
            # A refusal of the CREDENTIAL, not of the shape. Falling to the next tier would ask
            # the same unauthorised drive three times and report tier 2 as this tenant's ceiling —
            # a metadata verdict invented out of a permissions failure.
            raise
        except Exception as e:  # noqa: BLE001 — a 400 is Graph declining the shape, which is data
            refused.append(tier)
            last = e
            continue
        return {"tier": tier, "reads": TIER_MEANING[tier], "refused": refused, "error": None}
    return {"tier": None, "reads": None, "refused": refused,
            "error": f"every request shape was refused by this drive: {last}"}
