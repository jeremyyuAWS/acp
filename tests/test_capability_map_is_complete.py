"""Every route this app dispatches is mapped to a capability, or exempt with a stated reason.

THIS IS THE TEST PRD §18 IS ASKING FOR — "100% of workflow routes mapped to a capability" — and
the reason it exists as a test rather than as an assertion in a document is that the claim decays
on its own. There are 236 routes. Somebody adds the 237th next week; nothing about writing a new
endpoint reminds them that an authorization table exists somewhere else, and an unmapped route is
not an error at runtime. It just answers, to everybody.

So the invariant is enforced against the REAL registered route table — the same objects the
middleware matches against, obtained through the same core.enumerate_api_routes() the existing
access gate uses. Two implementations of "what routes exist" is how one of them ends up checking
a different set than the gate does, and core.py's own docstring records that this happened before:
a hand-maintained prefix allowlist "silently missed five route groups over five weeks".

WHAT A FAILURE HERE MEANS. Not "the map is out of date" — that phrasing invites adding the route
to whichever table makes the test pass. It means nobody has yet decided whether that endpoint
needs a permission, and the two answers have different consequences: mapping it wrongly locks out
roles that should reach it, and exempting it wrongly leaves customer data reachable by a role that
should not see it. The test exists to force the decision, not to be satisfied.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ACP / "api"))

import core                              # noqa: E402
import workspace_capability_map as capmap  # noqa: E402
import workspace_rbac as rbac            # noqa: E402


@pytest.fixture(scope="module")
def routes():
    from app import app
    return core.enumerate_api_routes(app)


# ── the premise ───────────────────────────────────────────────────────────────

def test_there_really_are_routes_to_check(routes):
    """If enumerate_api_routes returned nothing, every assertion below would pass by finding
    nothing — which is exactly the failure mode this whole file exists to prevent, one layer up.
    """
    assert len(routes) > 150, f"only {len(routes)} routes enumerated — the app did not load"


def test_the_map_is_not_empty():
    assert len(capmap.ROUTE_CAPABILITIES) > 100
    assert capmap.EXEMPT


# ── the invariant ─────────────────────────────────────────────────────────────

def test_every_route_is_mapped_or_exempt(routes):
    unmapped = capmap.unmapped_routes(routes)
    assert unmapped == [], (
        "these endpoints have no capability and no exemption — decide which, in "
        "api/workspace_capability_map.py:\n  "
        + "\n  ".join(f"{m} {p}" for m, p in unmapped))


def test_the_map_names_only_capabilities_that_exist(routes):
    """A typo produces a route NOBODY can reach: no role can hold a capability the catalog does
    not define, so the middleware denies every caller including the owner — who is only spared
    because their carve-out short-circuits the lookup entirely."""
    assert capmap.unknown_capabilities() == []


def test_the_map_does_not_name_routes_the_app_does_not_have(routes):
    """The other direction, and the one that rots quietly. A mapping for a deleted endpoint is
    dead weight that reads as coverage — it makes the table look more complete than it is, and
    the next person greps it to see whether something is protected."""
    real = {(m.upper(), r.path) for r in routes for m in (r.methods or ())}
    mapped = set(capmap.ROUTE_CAPABILITIES)
    stale = sorted(mapped - real)
    assert stale == [], f"mapped but no longer registered: {stale}"


def test_every_exemption_carries_a_reason():
    """An exemption with an empty reason is indistinguishable from an oversight that somebody
    silenced. The reason is what a reviewer reads to decide whether it is still true."""
    for key, reason in capmap.EXEMPT.items():
        assert reason and len(reason) > 20, f"{key} is exempt with no real reason: {reason!r}"


# ── the mutating half, which is where the damage is ───────────────────────────

def test_no_mutating_route_is_exempt_except_the_ones_that_must_be(routes):
    """A GET that slips through leaks; a POST that slips through CHANGES something. The exempt
    list should therefore be almost entirely reads, and every write on it needs to be a
    deliberate, nameable exception rather than a category."""
    allowed_writes = {
        ("POST", "/alerts/webhook"),          # authenticated by its own shared secret
        ("POST", "/me/reset-data"),           # scoped to the caller's own scans by construction
        ("PUT", "/settings/mine"),            # the caller's own preferences
        ("DELETE", "/settings/mine"),
    }
    exempt_writes = {k for k in capmap.EXEMPT if k[0] in ("POST", "PUT", "PATCH", "DELETE")}
    assert exempt_writes <= allowed_writes, (
        f"a mutating route was exempted without being on the short list: "
        f"{sorted(exempt_writes - allowed_writes)}")


def test_the_destructive_actions_are_behind_an_administrative_grant(routes):
    """Publishing, executing a disposition, wiping the workspace. Each is irreversible against the
    customer's real estate, and none may be reachable by tab access alone — PRD §5's whole point.
    """
    for method, path in [("POST", "/scans/{sid}/publish"),
                         ("POST", "/disposition/approvals/{audit_id}/approve"),
                         ("POST", "/disposition/policies/{policy_id}/execute"),
                         ("POST", "/admin/reset")]:
        needed = capmap.required_capabilities(method, path)
        assert needed, f"{method} {path} is unmapped"
        assert needed <= set(rbac.GRANT_CAPABILITIES), (
            f"{method} {path} is reachable via tab access ({sorted(needed)}) — PRD §5 requires "
            f"a separate administrative permission for actions like this")


# ── SSE (PRD §16) ─────────────────────────────────────────────────────────────

def test_every_stream_requires_what_its_status_endpoint_requires(routes):
    """§16: "SSE streams enforce the same permissions as their corresponding status endpoints."

    A stream is the one place where forgetting is INVISIBLE. A 403 on a status poll shows up in
    the UI immediately; an unguarded stream simply keeps delivering — the data flows, nobody sees
    an error, and the leak is indistinguishable from the feature working.
    """
    for stream, twin in capmap.STREAM_TWINS.items():
        stream_caps = capmap.required_capabilities(*stream)
        twin_caps = capmap.required_capabilities(*twin)
        assert twin_caps, f"the twin {twin} is itself unmapped"
        assert stream_caps == twin_caps, (
            f"{stream[1]} requires {sorted(stream_caps or ())} but its status endpoint "
            f"{twin[1]} requires {sorted(twin_caps)}")


def test_every_registered_stream_route_is_in_the_twin_table(routes):
    """The list of streams is derived from the ROUTES, not hand-maintained — otherwise a new
    stream endpoint is protected only if somebody remembered to add it to the twin table, which
    is the same forgetting this file exists to prevent, one level down."""
    streams = {(m.upper(), r.path) for r in routes for m in (r.methods or ())
               if r.path.endswith("/stream")}
    missing = sorted(streams - set(capmap.STREAM_TWINS))
    assert missing == [], (
        f"these SSE endpoints have no declared status twin: {missing}. §16 requires each to "
        f"enforce what its status endpoint enforces; declare the pair in STREAM_TWINS.")


# ── the ACR boundary must stay separate (PRD §3, §14) ─────────────────────────

def test_no_acr_route_is_governed_by_a_workspace_capability(routes):
    """PRD §3: workspace roles "must not replace or silently change ACR approval roles, which
    govern a different authorization boundary." §14 repeats it. An /acr route with a workspace
    capability would mean a workspace role could deny an ACR approver their own report — the
    exact interference both sections forbid.
    """
    acr = sorted(k for k in capmap.ROUTE_CAPABILITIES if k[1].startswith("/acr"))
    assert acr == [], f"workspace capabilities were attached to ACR routes: {acr}"


def test_the_acr_routes_really_exist_so_the_exemption_is_about_something(routes):
    """Otherwise the test above passes on a build with no ACR at all, and would keep passing
    after somebody attached a capability to the first ACR route they added."""
    acr = [r for r in routes if r.path.startswith("/acr")]
    assert len(acr) > 10, f"only {len(acr)} ACR routes found — the exemption guards nothing"


# ── the identity endpoints must stay reachable, or the SPA cannot recover ─────

@pytest.mark.parametrize("key", [
    ("GET", "/me"), ("GET", "/me/access"), ("GET", "/workspace/bootstrap"),
    ("GET", "/workspace/active-workflows"), ("GET", "/config"),
])
def test_identity_is_never_gated_on_a_capability(key):
    """Circularity: the SPA cannot learn that it has no access without being allowed to ask. Gate
    these and a user with no role gets a blank screen and no explanation — the Access restricted
    screen slice 2 built needs this answer in order to render at all.
    """
    assert capmap.required_capabilities(*key) is None
    assert capmap.is_exempt(*key)
