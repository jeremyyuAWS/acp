"""Whose problem is this Graph refusal, and what will this tenant answer? (Phase 4 / Phase 6)

THE DIAGNOSIS THIS REPLACES. Every SharePoint refusal in this codebase produced one message —
"grant Sites.Read.All on the app registration with tenant admin consent" — for every status and
every tenant. It is the right answer in exactly one of the three cases it was given for:

  * 401. Graph rejected the TOKEN: expired, revoked, issued for another resource. No consent
    changes it. The one refusal the signed-in user can fix themselves in five seconds was the one
    being escalated to their IT department.
  * 403 with the scope missing. The message was right, and now it says so with the token's own
    claims behind it rather than as a guess.
  * 403 with the scope PRESENT. A delegated Sites.Read.All is bounded by what the signed-in user
    can see, so a private site refuses a perfectly configured app. The old message sent a tenant
    admin to re-consent a permission that was already consented, while the actual blocker — site
    membership, which is the SITE OWNER's to fix — went unexamined. A wrong diagnosis costs more
    than none: it ends the investigation.

The second half is the metadata tiers. The walk asks for the wide $select and the listItem
expansion and falls back silently, so a tenant that refuses them yields a complete estate with
every content type unread — and says so only per document, only after the scan has finished.

WHAT IS DELIBERATELY NOT TESTED HERE: that a token is authentic. Nothing in sp_readiness verifies
a signature, and nothing may gate on it. The claims explain a refusal Graph has already made; a
forged token changes the explanation of a request that failed anyway. The test at the bottom pins
that the module has no such role rather than leaving it to the docstring.
"""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

import sp_readiness  # noqa: E402


def _jwt(claims: dict) -> str:
    """A JWT-shaped token with these claims. UNSIGNED — the third segment is filler, because
    nothing here reads it and a test that produced a real signature would be asserting something
    the module deliberately does not do."""
    def seg(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")
    return f"{seg({'alg': 'none'})}.{seg(claims)}.signature-not-checked"


DELEGATED = _jwt({"scp": "User.Read Files.Read.All Sites.Read.All"})
NO_SITES = _jwt({"scp": "User.Read Files.Read.All"})
APP_ONLY = _jwt({"roles": ["Sites.Read.All"]})


# ── reading the claims ───────────────────────────────────────────────────────────────────────

def test_a_delegated_token_reports_its_scp_claim():
    scopes, why = sp_readiness.token_scopes(DELEGATED)
    assert why is None
    assert scopes == frozenset({"User.Read", "Files.Read.All", "Sites.Read.All"})


def test_an_application_token_reports_its_roles():
    """The sync worker signs in app-only (api/sp_sync.py) and hits the same refusals. Reading only
    `scp` would report a fully-permissioned app token as carrying nothing, which is the wrong
    diagnosis in the most confusing possible direction."""
    scopes, why = sp_readiness.token_scopes(APP_ONLY)
    assert why is None and scopes == frozenset({"Sites.Read.All"})


def test_an_opaque_token_says_so_rather_than_reporting_no_scopes():
    """Azure may issue a non-JWT access token, and a caller holding one is not misconfigured.
    "Could not read" and "carries nothing" lead to opposite next steps."""
    scopes, why = sp_readiness.token_scopes("opaque-token-value")
    assert scopes is None and "not a JWT" in why


def test_a_malformed_payload_never_raises():
    scopes, why = sp_readiness.token_scopes("aaa.!!!not-base64!!!.ccc")
    assert scopes is None and why


def test_a_token_with_no_scope_claim_is_distinguished_from_an_unreadable_one():
    scopes, why = sp_readiness.token_scopes(_jwt({"aud": "https://graph.microsoft.com"}))
    assert scopes is None and "no scope or role claim" in why


def test_none_and_empty_are_answered_not_crashed():
    for value in (None, "", 12345):
        scopes, why = sp_readiness.token_scopes(value)
        assert scopes is None and why


def test_a_fully_qualified_scope_still_matches():
    """Azure emits `https://graph.microsoft.com/Sites.Read.All` in some configurations. A match
    that missed on that would report a correctly-consented tenant as unconsented — the exact
    wrong diagnosis this module exists to remove, arrived at by string comparison."""
    scopes, _ = sp_readiness.token_scopes(
        _jwt({"scp": "https://graph.microsoft.com/Sites.Read.All"}))
    assert sp_readiness._has(scopes, "Sites.Read.All")
    assert sp_readiness._has(frozenset({"sites.read.all"}), "Sites.Read.All"), "case matters here"


# ── whose problem it is ──────────────────────────────────────────────────────────────────────

def test_a_401_is_the_users_own_expired_token_not_an_admin_grant():
    d = sp_readiness.diagnose_refusal(401, token=DELEGATED, on_site=True)
    assert d["owner"] == sp_readiness.SIGNED_IN_USER
    assert "sign in with Microsoft again" in d["message"]
    assert "admin consent will not change it" in d["message"]
    assert "Sites.Read.All" not in d["message"], (
        "a 401 was reported as a missing scope — no consent can fix a rejected token")


def test_a_403_without_the_scope_is_the_tenant_admins():
    d = sp_readiness.diagnose_refusal(403, token=NO_SITES, on_site=True)
    assert d["owner"] == sp_readiness.TENANT_ADMIN
    assert d["missing_scope"] == "Sites.Read.All"
    assert "tenant admin consent" in d["message"]


def test_a_403_WITH_the_scope_is_the_site_owners():
    """THE CASE THAT HAD NO DIAGNOSIS. The app registration is configured and the answer is still
    no, because a delegated grant is bounded by what the signed-in account can see."""
    d = sp_readiness.diagnose_refusal(403, token=DELEGATED, on_site=True)
    assert d["owner"] == sp_readiness.SITE_OWNER
    assert d["missing_scope"] is None
    assert "not a member of this site" in d["message"]
    assert "The app registration is configured" in d["message"]


def test_an_unreadable_token_names_both_readings_and_says_which_fact_is_missing():
    d = sp_readiness.diagnose_refusal(403, token="opaque", on_site=True)
    assert d["owner"] == sp_readiness.UNKNOWN_OWNER
    assert "not a JWT" in d["message"]
    assert "Sites.Read.All" in d["message"] and "not a member of" in d["message"]


def test_a_onedrive_refusal_does_not_send_anybody_to_an_admin():
    """A personal drive does not need Sites.Read.All, so naming it here would send the reader for
    a grant that cannot change the answer."""
    d = sp_readiness.diagnose_refusal(403, token=NO_SITES, on_site=False)
    assert d["owner"] == sp_readiness.SIGNED_IN_USER
    assert "is not involved" in d["message"]


def test_an_unknown_target_hedges_on_the_TARGET_and_not_on_the_token():
    """`_sp_get` is often handed a Graph-issued deltaLink whose target cannot be recovered from
    its shape. The honest answer names both resources — and still gives the definite scope
    verdict, which is true whichever one it was."""
    d = sp_readiness.diagnose_refusal(403, token=NO_SITES, on_site=None)
    assert d["owner"] == sp_readiness.TENANT_ADMIN
    assert "SharePoint or OneDrive resource" in d["message"]
    assert d["missing_scope"] == "Sites.Read.All"


# ── the message the scan itself prints ───────────────────────────────────────────────────────

class _Resp:
    def __init__(self, status):
        self.status_code = status

    def json(self):
        return {}

    def raise_for_status(self):
        raise RuntimeError(f"http {self.status_code}")


def _refuse(status):
    def get(url, headers=None, timeout=None, follow_redirects=None):
        return _Resp(status)
    return get


def test_the_scanner_raises_the_site_owner_diagnosis_for_a_scoped_token(monkeypatch):
    """End to end through the path a scan takes: the per-site exception report and the scan log
    both render this string verbatim, so it is the message that reaches a human."""
    import httpx
    import scanner
    monkeypatch.setattr(httpx, "get", _refuse(403))
    with pytest.raises(PermissionError, match="not a member of this site"):
        scanner._sp_drives(DELEGATED, "S1")


def test_the_scanner_still_names_the_scope_when_it_is_genuinely_missing(monkeypatch):
    import httpx
    import scanner
    monkeypatch.setattr(httpx, "get", _refuse(403))
    with pytest.raises(PermissionError, match="does not carry Sites.Read.All"):
        scanner._sp_drives(NO_SITES, "S1")


def test_the_scanner_does_not_send_a_401_to_an_admin(monkeypatch):
    import httpx
    import scanner
    monkeypatch.setattr(httpx, "get", _refuse(401))
    with pytest.raises(PermissionError, match="rejected the sign-in token"):
        scanner._sp_drives(DELEGATED, "S1")


def test_a_refusal_still_names_the_url_it_refused(monkeypatch):
    """Kept from the old message. "Which call was denied" is what turns a diagnosis into
    something checkable against the tenant's own audit log."""
    import httpx
    import scanner
    monkeypatch.setattr(httpx, "get", _refuse(403))
    with pytest.raises(PermissionError, match=r"URL: https://graph.microsoft.com/v1.0/sites/S1"):
        scanner._sp_drives(DELEGATED, "S1")


def test_a_permission_error_is_never_retried(monkeypatch):
    """Unchanged, and asserted here because this edit touched the branch that decides it. A scope
    problem's answer does not change on a second ask, and four slow refusals would delay the only
    thing the operator can act on."""
    import httpx
    import scanner
    calls: list = []

    def get(url, headers=None, timeout=None, follow_redirects=None):
        calls.append(url)
        return _Resp(403)
    monkeypatch.setattr(httpx, "get", get)
    monkeypatch.setattr(scanner, "_sp_sleep", lambda s: None)
    with pytest.raises(PermissionError):
        scanner._sp_drives(DELEGATED, "S1")
    assert len(calls) == 1


# ── which request shapes this tenant answers ─────────────────────────────────────────────────

def _tiers(accepts: set[int]):
    """A Graph stand-in that accepts only the listed tiers, identified by what the URL asks for —
    the same three shapes scanner._sp_children_url builds."""
    seen: list[str] = []

    def get(token, url, **kw):
        seen.append(url)
        import scanner
        expanded = scanner._SP_LIST_EXPAND.split("&", 1)[1] in url
        rich = "retentionLabel" in url
        tier = 0 if (expanded and rich) else 1 if expanded else 2
        if tier not in accepts:
            raise RuntimeError("http 400: unsupported query")
        return {"value": []}
    return get, seen


def test_a_generous_tenant_answers_the_widest_ask_first_time():
    get, seen = _tiers({0, 1, 2})
    out = sp_readiness.probe_metadata_tiers("tok", "d1", get=get)
    assert out["tier"] == 0 and out["refused"] == []
    assert "retention labels" in out["reads"]
    assert len(seen) == 1, "a tenant that answered was asked again"


def test_a_tenant_that_refuses_retention_labels_reports_tier_1():
    get, seen = _tiers({1, 2})
    out = sp_readiness.probe_metadata_tiers("tok", "d1", get=get)
    assert out["tier"] == 1 and out["refused"] == [0]
    assert "not retention labels" in out["reads"]


def test_a_tenant_that_refuses_the_expansion_reports_the_bare_listing():
    get, _ = _tiers({2})
    out = sp_readiness.probe_metadata_tiers("tok", "d1", get=get)
    assert out["tier"] == 2 and out["refused"] == [0, 1]
    assert "no SharePoint-native metadata" in out["reads"]


def test_a_tenant_that_refuses_everything_reports_no_tier_rather_than_the_last_one():
    get, _ = _tiers(set())
    out = sp_readiness.probe_metadata_tiers("tok", "d1", get=get)
    assert out["tier"] is None and out["refused"] == [0, 1, 2] and out["error"]


def test_the_probe_asks_EXACTLY_what_the_walk_asks():
    """The whole value of a preflight is that it predicts the run. A probe that composed its own
    request would prove something about the probe — the mistake this repo has paid for before."""
    import scanner
    get, seen = _tiers({0})
    sp_readiness.probe_metadata_tiers("tok", "d1", get=get)
    expected = scanner._sp_children_url(f"{scanner.GRAPH}/drives/d1", "root", 0)
    assert seen == [expected.replace("$top=200", "$top=1")]


def test_the_probe_is_bounded_to_one_item():
    get, seen = _tiers({2})
    sp_readiness.probe_metadata_tiers("tok", "d1", get=get)
    assert all("$top=1" in u for u in seen), (
        "the onboarding probe walked a page of a customer's library to answer a question about "
        "request shapes")


def test_a_permission_failure_is_not_reported_as_a_metadata_ceiling():
    """A 403 refuses the CREDENTIAL, not the shape. Falling through the tiers on one would ask the
    same unauthorised drive three times and report tier 2 as this tenant's ceiling — a metadata
    verdict invented out of a permissions failure, which is a lie in the direction that stops
    anybody looking."""
    def get(token, url, **kw):
        raise PermissionError("denied")
    with pytest.raises(PermissionError):
        sp_readiness.probe_metadata_tiers("tok", "d1", get=get)


def test_onedrive_is_probed_at_the_personal_drive_root():
    import scanner
    get, seen = _tiers({0})
    sp_readiness.probe_metadata_tiers("tok", None, get=get)
    assert seen[0].startswith(f"{scanner.GRAPH}/me/drive/root/children")


# ── the boundary the module must never cross ─────────────────────────────────────────────────

def test_nothing_here_verifies_a_signature_and_nothing_may_gate_on_it():
    """DELIBERATE, and pinned so it stays deliberate. The claims explain a refusal Graph has
    ALREADY made; they are not evidence of anything and must never decide what a caller may read.
    A future edit that reached for a crypto library here would be building an authorization
    decision on an unverified token, which is the failure this assertion exists to make loud."""
    import inspect
    src = inspect.getsource(sp_readiness)
    for banned in ("jwt.decode", "verify_signature", "import jwt", "cryptography"):
        assert banned not in src, (
            f"sp_readiness reached for {banned!r} — its claims are a diagnostic, and a module "
            f"that starts verifying tokens will be trusted to authorize with them")
    assert "DIAGNOSTIC ONLY" in sp_readiness.__doc__


# ── GET /sharepoint/readiness — the onboarding report ────────────────────────────────────────

class _FakeRequest:
    """Just enough of fastapi.Request for this endpoint — it reads .headers and nothing else."""
    def __init__(self, headers: dict):
        self.headers = headers


def _readiness(token=DELEGATED, **kw):
    from routes.sharepoint import sharepoint_readiness
    return sharepoint_readiness(_FakeRequest({"x-sp-token": token}), **kw)


def test_probe_false_issues_no_graph_call_at_all(monkeypatch):
    """"Am I signed in with the right scopes" is answerable from the token alone, and a caller
    asking only that must not spend a request against a customer's tenant to hear it."""
    import httpx

    def explode(*a, **kw):
        raise AssertionError("probe=false reached Microsoft Graph")
    monkeypatch.setattr(httpx, "get", explode)
    r = _readiness(probe=False)
    assert r["scopes"] == ["Files.Read.All", "Sites.Read.All", "User.Read"]
    assert r["has_sites_scope"] is True
    assert r["problems"] == []
    assert r["metadata"] is None


def test_a_token_without_the_site_scope_is_reported_before_any_site_is_picked():
    """The operator is about to select a SITE with a token that cannot read one. Saying so here is
    the whole point of an onboarding check — the alternative is a 403 they have to interpret."""
    r = _readiness(token=NO_SITES, probe=False)
    assert r["has_sites_scope"] is False
    [p] = r["problems"]
    assert p["owner"] == sp_readiness.TENANT_ADMIN
    assert p["missing_scope"] == "Sites.Read.All"


def test_an_opaque_token_is_not_reported_as_missing_the_scope():
    """`has_sites_scope` is None, not False. "We could not read it" and "it is not there" lead to
    opposite next steps, and collapsing them would send an admin to grant something already
    granted — the failure this whole module is about, reproduced one level up."""
    r = _readiness(token="opaque", probe=False)
    assert r["has_sites_scope"] is None
    assert r["scopes_unreadable"]
    assert r["problems"] == []


def test_a_readiness_report_names_the_libraries_and_the_metadata_tier(monkeypatch):
    import httpx
    import scanner

    def get(url, headers=None, timeout=None, follow_redirects=None):
        class R:
            status_code = 200

            def json(self_inner):
                if "/drives?" in url:
                    return {"value": [{"id": "d1", "name": "Documents"}]}
                return {"value": []}

            def raise_for_status(self_inner):
                pass
        if "/children" in url and scanner._SP_LIST_EXPAND.split("&", 1)[1] in url:
            class Bad:
                status_code = 400

                def json(self_inner):
                    return {}

                def raise_for_status(self_inner):
                    raise RuntimeError("http 400")
            return Bad()
        return R()
    monkeypatch.setattr(httpx, "get", get)
    r = _readiness(site="S1")
    assert r["libraries"] == [{"id": "d1", "name": "Documents"}]
    assert r["metadata"]["tier"] == 2 and r["metadata"]["refused"] == [0, 1]
    assert any("unavailable" in p["message"] for p in r["problems"]), (
        "a tenant that will produce a metadata-free estate was not told so")


def test_a_refused_site_reports_the_scanners_own_diagnosis(monkeypatch):
    """Carried through rather than re-derived. One place decides whose problem a refusal is; a
    second opinion here could disagree with the message the scan itself prints, and an operator
    reading two different explanations of one 403 has been given less than one."""
    import httpx
    monkeypatch.setattr(httpx, "get", _refuse(403))
    r = _readiness(site="S1")
    assert r["libraries"] is None
    assert any("not a member of this site" in p["message"] for p in r["problems"])


def test_a_site_with_no_libraries_is_a_problem_not_a_clean_report(monkeypatch):
    """It scans to zero. Reporting it ready hands the operator an empty run and no way to tell
    the site from the product."""
    import httpx

    class R:
        status_code = 200

        def json(self):
            return {"value": []}

        def raise_for_status(self):
            pass
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: R())
    r = _readiness(site="S1")
    assert r["libraries"] == []
    assert any(p["owner"] == sp_readiness.SITE_OWNER for p in r["problems"])


def test_no_token_is_a_400_rather_than_an_empty_report():
    from fastapi import HTTPException
    from routes.sharepoint import sharepoint_readiness
    with pytest.raises(HTTPException) as e:
        sharepoint_readiness(_FakeRequest({}))
    assert e.value.status_code == 400


def test_the_endpoint_never_refuses_a_scan():
    """DELIBERATELY NOT A GATE. A tenant that answers only tier 2 can still be scanned and should
    be — it produces a real estate with less metadata. This endpoint exists so that outcome is a
    decision somebody made rather than one they discover afterwards, so it reports and never
    blocks."""
    import inspect
    from routes import sharepoint
    src = inspect.getsource(sharepoint.sharepoint_readiness)
    body = src[src.index('"""', src.index('"""') + 3):]
    assert "raise HTTPException" not in body, (
        "the readiness report grew a refusal — it reports, the operator decides")


def test_the_discovery_preflight_groups_a_refused_site_by_owner(monkeypatch):
    """An operator selecting thirty sites gets a verdict they can act on in one pass — "two need
    the site owner, one needs your admin" — rather than thirty sentences to read individually."""
    import httpx
    from routes.sharepoint import describe_sharepoint_readiness
    monkeypatch.setattr(httpx, "get", _refuse(403))
    r = describe_sharepoint_readiness(_FakeRequest({"x-sp-token": DELEGATED}), ["S1"])
    assert r["ready"] is False
    [root] = r["roots"]
    assert root["owner"] == sp_readiness.SITE_OWNER
    assert "not a member of this site" in root["error"]


def test_the_same_refusal_with_no_scope_is_grouped_to_the_admin(monkeypatch):
    import httpx
    from routes.sharepoint import describe_sharepoint_readiness
    monkeypatch.setattr(httpx, "get", _refuse(403))
    r = describe_sharepoint_readiness(_FakeRequest({"x-sp-token": NO_SITES}), ["S1"])
    assert r["roots"][0]["owner"] == sp_readiness.TENANT_ADMIN
