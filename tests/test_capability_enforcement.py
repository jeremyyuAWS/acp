"""Routes actually refuse — through the real app, over real HTTP, with a real role.

WHY THROUGH THE ASGI STACK AND NOT BY CALLING HANDLERS. Slices 1–3 tested decision tables and
route functions directly, which is right for what they were about. This slice's claim is
different: it is that a REQUEST is refused, and that claim lives in middleware ordering, route
matching and response shape — none of which a direct function call exercises. A handler test would
pass against an app where the middleware was never registered.

THE FOUR THINGS THAT COULD BE WRONG, and each is checked here rather than reasoned about:

  1. the flag is off and something changed anyway   (the whole rollout depends on it not)
  2. the gate runs OUTSIDE the auth gate, so an unauthenticated request gets 403 "you lack
     permission" instead of 401 "we do not know who you are" — which tells an expired session
     it has been demoted
  3. an SSE stream is not covered, because it never returns and nobody polls it (PRD §16)
  4. the owner is locked out, which is the one failure with no recovery path

WHAT THIS FILE DOES NOT CLAIM. It does not prove per-object isolation — that a Remediation
Reviewer cannot read ANOTHER tenant's scan. That is the routes' own owner-scoped reads
(get_scan(..., owner=...)), it predates this feature, and tests/test_foreign_scan_404.py owns it.
Conflating the two would let a green run here be read as evidence of something this gate does not
do: it checks the CAPABILITY, not the object.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ACP / "api"))

import workspace_rbac as rbac        # noqa: E402
import workspace_roles as wr         # noqa: E402

OWNER = "owner@hosp.org"
REVIEWER = "rev@hosp.org"          # Remediation Reviewer: remediate=operate, liveops=hidden
ANALYST = "analyst@hosp.org"       # Analyst: discover/assess=operate, publish=hidden
UNASSIGNED = "nobody@hosp.org"


@pytest.fixture
def client(monkeypatch):
    """The real app, a real Store, an owner configured, OPEN_ACCESS on — and the REAL access gate.

    Identity arrives the way it does in production: `Authorization: Bearer <token>`, verified by
    core.verify_gis_token. That function is stubbed to treat the token AS the email, which is the
    smallest possible seam — everything else (the gate's ordering, its 401, its
    request.state.user_email stamping) is the shipped code. Injecting the identity with an extra
    middleware instead would have tested a stack that does not exist, and would have made the
    401-vs-403 distinction below untestable, since there would be no unauthenticated path left.

    OPEN_ACCESS is explicitly ON because that is the configuration this gate exists to survive:
    under it core.is_admin() is True for every authenticated user, so anything that passed by
    accident on `is_admin` would pass here too.
    """
    import core
    import store as store_mod

    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "acp-test.db")
    st = store_mod.Store()
    monkeypatch.setattr(core, "store", st, raising=False)
    monkeypatch.setattr(core, "get_store", lambda: st, raising=False)
    monkeypatch.setattr(core, "OWNER_EMAIL", OWNER, raising=False)
    monkeypatch.setattr(core, "OPEN_ACCESS", True, raising=False)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "test-client", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    monkeypatch.setattr(core, "verify_gis_token", lambda t: (t or "").strip().lower() or None,
                        raising=False)
    monkeypatch.setattr(core, "email_allowed", lambda e: bool(e), raising=False)

    for email in (OWNER, REVIEWER, ANALYST, UNASSIGNED):
        st.upsert_person({"email": email, "role": "user", "status": "access_ready"})
    wr.seed_builtin_roles(st, tenant_id=OWNER)
    wr.assign_role(st, email=REVIEWER, role_id=rbac.REMEDIATION_REVIEWER, actor=OWNER)
    wr.assign_role(st, email=ANALYST, role_id=rbac.ANALYST, actor=OWNER)

    from fastapi.testclient import TestClient
    from app import app
    return TestClient(app), core, st


def get(client, path, who):
    tc = client[0] if isinstance(client, tuple) else client
    return tc.get(path, headers={"Authorization": f"Bearer {who}"})


def anonymous(client, path):
    tc = client[0] if isinstance(client, tuple) else client
    return tc.get(path)


# ── 1. the flag ───────────────────────────────────────────────────────────────

def test_with_the_flag_off_nothing_is_refused(client, monkeypatch):
    """The rollout's whole premise. Step 1 writes roles; step 3 turns this on. If enforcement
    happened at step 1, the migration would take access away from everyone the morning it ran."""
    tc, _core, _st = client
    monkeypatch.delenv(wr.FLAG, raising=False)
    for who in (UNASSIGNED, ANALYST, REVIEWER):
        r = get(tc, "/hitl/queue", who)
        assert r.status_code != 403, f"{who} was refused with the flag off"


def test_with_the_flag_on_a_role_without_the_capability_is_refused(client, monkeypatch):
    tc, _core, _st = client
    monkeypatch.setenv(wr.FLAG, "1")
    # An Analyst has Live Operations hidden (PRD §7), so operations.view is not theirs.
    r = get(tc, "/admin/activity", ANALYST)
    assert r.status_code == 403
    body = r.json()
    assert body["capability_denied"] is True
    assert "operations.view" in body["required"]
    assert "Analyst" in body["detail"], "the refusal should name the role, so the user can ask"


# ── 2. 403 vs 401, and vs 404 (PRD §11) ───────────────────────────────────────

def test_an_unassigned_user_gets_the_default_role_and_is_admitted(client, monkeypatch):
    """Owner decision, 2026-09-04. This test asserted a 403 when it was written; the default role
    reverses that for the unassigned case specifically — see the two tests below for the cases
    that still refuse, which are the ones where a decision was actually recorded."""
    tc, _core, _st = client
    monkeypatch.setenv(wr.FLAG, "1")
    assert get(tc, "/hitl/queue", UNASSIGNED).status_code != 403


def test_a_user_whose_assigned_role_is_gone_is_still_refused(client, monkeypatch):
    """Somebody narrowed this user and the row saying how is missing. Defaulting here would
    silently restore access an administrator deliberately removed."""
    tc, _core, st = client
    monkeypatch.setenv(wr.FLAG, "1")
    st.upsert_workspace_role(tenant_id=OWNER, role_id="locked", name="Locked",
                             permissions={"overview": "view"}, expected_version=None)
    wr.assign_role(st, email=UNASSIGNED, role_id="locked", actor=OWNER)
    st.delete_workspace_role(tenant_id=OWNER, role_id="locked")
    r = get(tc, "/hitl/queue", UNASSIGNED)
    assert r.status_code == 403
    assert r.json()["capability_denied"] is True


def test_the_refusal_is_403_and_not_404(client, monkeypatch):
    """PRD §11 reserves 404 for "confirming another tenant's object exists would disclose
    information" — a per-OBJECT decision the routes already make with owner-scoped reads. This
    gate is about the CAPABILITY; answering 404 would make every permission error look like a
    missing page, which the user cannot act on and an operator cannot distinguish in a log."""
    tc, _core, _st = client
    monkeypatch.setenv(wr.FLAG, "1")
    assert get(tc, "/admin/activity", ANALYST).status_code == 403


def test_a_capability_the_role_does_hold_still_works(client, monkeypatch):
    """The other direction, and the one that matters most in practice: enforcement that refuses
    everybody is trivially 'secure' and useless. A Reviewer's own queue must still open."""
    tc, _core, _st = client
    monkeypatch.setenv(wr.FLAG, "1")
    assert get(tc, "/hitl/queue", REVIEWER).status_code != 403


# ── 3. SSE (PRD §16) ──────────────────────────────────────────────────────────

def test_a_stream_is_refused_exactly_as_its_status_endpoint_is(client, monkeypatch):
    """The failure this prevents is silent: a stream that skips the check keeps delivering, with
    no error anywhere, which is indistinguishable from the feature working."""
    tc, _core, _st = client
    monkeypatch.setenv(wr.FLAG, "1")
    status = get(tc, "/admin/activity", ANALYST)
    assert status.status_code == 403

    # Requested as a STREAM with a timeout, even though a refusal completes immediately, because
    # of how this test fails when it fails. A plain GET here is fine while the gate works and
    # HANGS FOREVER the moment it stops — the endpoint is an endless SSE feed, so a regression
    # would take the whole CI job out on a timeout instead of reporting one red test. Found by
    # bite-checking this very file: disabling the middleware produced a hang, not a failure.
    with tc.stream("GET", "/admin/activity/stream", timeout=5,
                   headers={"Authorization": f"Bearer {ANALYST}"}) as stream:
        assert stream.status_code == 403, "the SSE twin was not gated"
        stream.close()


def test_a_stream_the_role_may_have_is_not_refused(client, monkeypatch):
    """The allowed direction for SSE, asserted at the GATE rather than over HTTP — and the reason
    is worth recording rather than hiding behind a passing test.

    An SSE endpoint that the gate lets through never finishes. TestClient runs the app in-process
    through a blocking portal, so both a plain GET and a `with tc.stream(...)` hang on close: the
    suite was killed twice before this was written this way. There is no allowed stream in this
    app that terminates on its own, so there is nothing to request that would end.

    What can still be checked is the decision the middleware would reach, from the same two inputs
    it uses — the caller's capabilities and the route's requirement. That is weaker than an HTTP
    round trip and it is stated as such: the REFUSED direction above IS an HTTP test, and that is
    the direction where being wrong is a data leak. Being wrong here only over-blocks, which is
    visible the moment anybody opens Live Operations.
    """
    import workspace_capability_map as capmap
    _tc, core, st = client
    monkeypatch.setenv(wr.FLAG, "1")
    access = wr.access_for_email(st, OWNER, owner_email=core.OWNER_EMAIL)
    needed = capmap.required_capabilities("GET", "/admin/activity/stream")
    assert needed, "the stream is unmapped — the completeness test should have caught this"
    assert set(access["capabilities"]) & needed, (
        "the owner would be refused their own activity stream")


# ── 4. the owner is never locked out ──────────────────────────────────────────

@pytest.mark.parametrize("path", ["/admin/activity", "/hitl/queue", "/admin/roles", "/settings"])
def test_the_owner_reaches_everything(client, monkeypatch, path):
    """The one failure with no recovery path. Checked across several capabilities rather than one,
    because the carve-out is a single branch and a bug in it would be total."""
    tc, _core, _st = client
    monkeypatch.setenv(wr.FLAG, "1")
    assert get(tc, path, OWNER).status_code != 403


def test_the_owner_reaches_everything_even_with_no_role_row(client, monkeypatch):
    tc, _core, st = client
    monkeypatch.setenv(wr.FLAG, "1")
    st.delete_workspace_role(tenant_id=OWNER, role_id=rbac.OWNER)
    assert get(tc, "/admin/roles", OWNER).status_code != 403


# ── the identity endpoints stay reachable (or the SPA cannot explain itself) ──

@pytest.mark.parametrize("path", ["/me/access", "/config"])
def test_identity_answers_even_for_a_user_with_no_role(client, monkeypatch, path):
    """Circular otherwise: the SPA cannot learn it has no access without being allowed to ask,
    and slice 2's Access restricted screen needs that answer to render at all."""
    tc, _core, _st = client
    monkeypatch.setenv(wr.FLAG, "1")
    assert get(tc, path, UNASSIGNED).status_code != 403


# ── suspension (PRD §14) ──────────────────────────────────────────────────────

def test_a_suspended_user_is_refused_despite_holding_a_real_role(client, monkeypatch):
    tc, _core, st = client
    monkeypatch.setenv(wr.FLAG, "1")
    assert get(tc, "/hitl/queue", REVIEWER).status_code != 403
    st.upsert_person({"email": REVIEWER, "status": "suspended"})
    assert get(tc, "/hitl/queue", REVIEWER).status_code == 403


# ── the ACR boundary is untouched (PRD §3) ────────────────────────────────────

def test_acr_routes_are_not_gated_by_workspace_capabilities(client, monkeypatch):
    """A workspace role must not be able to deny an ACR approver their own report. Asserted as a
    REQUEST rather than from the map, because the map being right does not prove the middleware
    reads it the way the map intends."""
    tc, _core, _st = client
    monkeypatch.setenv(wr.FLAG, "1")
    r = get(tc, "/acr", UNASSIGNED)
    assert r.status_code != 403 or not r.json().get("capability_denied"), (
        "an ACR route was refused by the workspace gate")


# ── a role change takes effect on the next request (PRD §9) ───────────────────

def test_a_revoked_role_stops_working_on_the_very_next_request(client, monkeypatch):
    """§9: "Users whose permissions change during an active session receive the new permissions on
    their next API request." That is only true if nothing caches the answer — which is why the
    middleware deliberately does not, and why this asserts across two requests in one test rather
    than trusting the absence of a cache to stay absent."""
    tc, _core, st = client
    monkeypatch.setenv(wr.FLAG, "1")

    # POST .../remediate, not GET /hitl/queue. The first draft demoted a Reviewer to Viewer and
    # expected the QUEUE to close, which was wrong about the product rather than about the code:
    # a Viewer has Remediate at View (PRD §7), so `remediate.view` survives the demotion and
    # reading the queue is still theirs. The capability that genuinely disappears is
    # `remediate.run` — Reviewer has Remediate at Operate, Viewer does not — so that is the pair
    # that actually demonstrates a narrowing.
    before = tc.post("/scans/s1/remediate", headers={"Authorization": f"Bearer {REVIEWER}"})
    assert before.status_code != 403, "the Reviewer should be able to attempt this"

    wr.assign_role(st, email=REVIEWER, role_id=rbac.VIEWER, actor=OWNER)

    after = tc.post("/scans/s1/remediate", headers={"Authorization": f"Bearer {REVIEWER}"})
    assert after.status_code == 403
    assert after.json()["capability_denied"] is True
