"""Only an approver may publish an ACR — under OPEN_ACCESS, which is the default (PRD §21.11).

THIS FILE IS THE POINT OF api/acr_authz.py, so it is worth saying why it looks paranoid.

ACP's default access model is `ACP_OPEN_ACCESS=1` (api/core.py). Under it, `core.is_admin()`
returns True for ANY authenticated, admitted user — deliberately, because the rest of the product
has no separate admin view. Verified on unmodified `main`:

    OPEN_ACCESS           = True
    is_admin(owner)       = True
    is_admin(random user) = True     <-- anyone who can sign in
    is_owner(random user) = False

So an ACR feature that gated publication on `is_admin` would satisfy "only an approver may
publish" on paper and not at all in fact. Worse, it would PASS a naive test: on a dev box with no
ACP_OWNER_EMAIL configured, `is_admin` returns True for everyone including the empty string, so
a test that simply checked "the approver can publish" would go green against a gate that admits
the world.

Every test here therefore sets OPEN_ACCESS explicitly ON. That is the configuration the gate
exists to survive, and a gate only tested with it off is untested.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import acr_authz  # noqa: E402

OWNER = "owner@acp.test"       # the protected ACP_OWNER_EMAIL
EVALUATOR = "eve@acp.test"
EDITOR = "ed@acp.test"
APPROVER = "app@acp.test"
RANDOM = "random@acp.test"     # authenticated and admitted, holds no ACR role


@pytest.fixture()
def open_access_client(monkeypatch, isolated_store):
    """A TestClient with OPEN_ACCESS explicitly ON and an owner configured.

    Mirrors tests/test_content_workspace_upload.py's gated_client, with the one difference this
    file is about: core.OPEN_ACCESS is forced True rather than left at whatever the environment
    happens to give.
    """
    import core
    from fastapi.testclient import TestClient
    from app import app

    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "test-client-id", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    monkeypatch.setattr(core, "OWNER_EMAIL", OWNER, raising=False)
    monkeypatch.setattr(core, "OPEN_ACCESS", True, raising=False)
    monkeypatch.setattr(core, "verify_gis_token", lambda tok: tok or None)
    monkeypatch.setattr(core, "email_allowed",
                        lambda e: e in (OWNER, EVALUATOR, EDITOR, APPROVER, RANDOM))

    client = TestClient(app)

    def as_user(email):
        client.headers.update({"Authorization": f"Bearer {email}"})
        return client

    return as_user


def _report(client) -> str:
    r = client(OWNER).post("/acr", json={"product_version": "1.4.0"})
    assert r.status_code == 200, r.text
    return r.json()["report_id"]


# ── the precondition this whole file rests on ─────────────────────────────────────────────────

def test_open_access_really_does_make_everyone_an_admin(monkeypatch):
    """The gap, asserted directly. If this ever stops being true, the elaborate carve-out in
    acr_authz is no longer necessary and this file should be revisited — so the assumption is
    pinned rather than described in a comment."""
    import core
    monkeypatch.setattr(core, "OWNER_EMAIL", OWNER, raising=False)
    monkeypatch.setattr(core, "OPEN_ACCESS", True, raising=False)

    assert core.is_admin(RANDOM) is True, "core.is_admin is no longer open under OPEN_ACCESS"
    assert core.is_owner(RANDOM) is False, "is_owner is the carve-out acr_authz relies on"
    assert core.is_admin("") is False, "the login perimeter itself must be unchanged"


# ── the gate ──────────────────────────────────────────────────────────────────────────────────

def test_a_random_authenticated_user_cannot_approve_a_criterion(open_access_client):
    """The headline. This user is an admin by core.is_admin's reckoning and still cannot sign
    off a conformance claim."""
    rid = _report(open_access_client)
    r = open_access_client(RANDOM).post(f"/acr/{rid}/criteria/1.4.3/approve")
    assert r.status_code == 403
    assert "approver" in r.json()["detail"]


def test_a_random_authenticated_user_cannot_record_evidence(open_access_client):
    rid = _report(open_access_client)
    r = open_access_client(RANDOM).post(
        f"/acr/{rid}/criteria/1.4.3/evidence",
        json={"criterion_num": "1.4.3", "source_kind": "manual", "result": "pass"})
    assert r.status_code == 403


def test_a_random_authenticated_user_cannot_decide_a_criterion(open_access_client):
    rid = _report(open_access_client)
    r = open_access_client(RANDOM).post(f"/acr/{rid}/criteria/1.4.3/decision",
                                        json={"final_status": "Does Not Support",
                                              "remarks": "a limitation"})
    assert r.status_code == 403


def test_a_random_authenticated_user_cannot_grant_themselves_a_role(open_access_client):
    """The escalation path. If this returned 200 the whole model would be decorative."""
    rid = _report(open_access_client)
    r = open_access_client(RANDOM).put(f"/acr/{rid}/roles",
                                       json={"email": RANDOM, "role": "approver"})
    assert r.status_code == 403


def test_an_evaluator_cannot_approve(open_access_client):
    """Roles are distinct, not a single "logged in" bit. PRD §18."""
    rid = _report(open_access_client)
    open_access_client(OWNER).put(f"/acr/{rid}/roles",
                                  json={"email": EVALUATOR, "role": "evaluator"})
    r = open_access_client(EVALUATOR).post(f"/acr/{rid}/criteria/1.4.3/approve")
    assert r.status_code == 403


def test_an_editor_cannot_approve(open_access_client):
    rid = _report(open_access_client)
    open_access_client(OWNER).put(f"/acr/{rid}/roles", json={"email": EDITOR, "role": "editor"})
    r = open_access_client(EDITOR).post(f"/acr/{rid}/criteria/1.4.3/approve")
    assert r.status_code == 403


def test_a_granted_approver_can_approve(open_access_client):
    """The gate refuses by default and admits on an explicit grant — not the other way round."""
    rid = _report(open_access_client)
    open_access_client(OWNER).put(f"/acr/{rid}/roles",
                                  json={"email": APPROVER, "role": "approver"})
    c = open_access_client(APPROVER)
    c.post(f"/acr/{rid}/criteria/1.4.3/evidence",
           json={"criterion_num": "1.4.3", "source_kind": "manual", "result": "pass"})
    c.post(f"/acr/{rid}/criteria/1.4.3/decision",
           json={"final_status": "Does Not Support", "remarks": "known limitation"})
    r = c.post(f"/acr/{rid}/criteria/1.4.3/approve")
    assert r.status_code == 200, r.text
    assert r.json()["approval_state"] == "approved"


def test_the_protected_owner_is_the_anti_lockout_carve_out(open_access_client):
    """On a fresh deploy nobody holds an ACR role, so without this the feature could never be
    administered at all. It is core.is_owner (one configured email), never core.is_admin."""
    rid = _report(open_access_client)
    r = open_access_client(OWNER).put(f"/acr/{rid}/roles",
                                      json={"email": APPROVER, "role": "approver"})
    assert r.status_code == 200


# ── owner isolation, on top of the role model ─────────────────────────────────────────────────

def test_an_acr_is_visible_to_every_admitted_user_not_only_its_creator(open_access_client):
    """The tenancy decision, pinned — and it is a DEPARTURE from the rest of the app.

    Everywhere else `owner_email` is per-user isolation and a second person's request 404s. An ACR
    cannot work that way: PRD §6 names five distinct humans and §18 recommends the approver not be
    the person who made most of the decisions, so an approver who cannot open the report is not an
    approver. ACR rows therefore live in ONE namespace per deployment (see routes/acr.py::_tenant).

    This test is what stops a well-meaning change "restoring consistency" by keying ACR rows on the
    caller: doing so makes every cross-person workflow in the PRD unreachable, and the symptom is a
    404 that reads like a missing report rather than a broken permission model.
    """
    rid = _report(open_access_client)
    r = open_access_client(APPROVER).get(f"/acr/{rid}")
    assert r.status_code == 200, r.text
    assert r.json()["report"]["id"] == rid


def test_reading_is_open_but_writing_is_not(open_access_client):
    """core.py's own split, applied here: OPEN_ACCESS gives everyone the same screens and the same
    non-destructive features, and does not open the irreversible ones. Publishing a conformance
    claim is irreversible in the way that matters — it reaches a customer's procurement file."""
    rid = _report(open_access_client)
    c = open_access_client(RANDOM)
    assert c.get(f"/acr/{rid}").status_code == 200
    assert c.get(f"/acr/{rid}/criteria").status_code == 200
    assert c.get(f"/acr/{rid}/validation").status_code == 200
    assert c.post(f"/acr/{rid}/criteria/1.4.3/approve").status_code == 403


def test_a_user_with_no_role_cannot_create_a_report(open_access_client):
    r = open_access_client(RANDOM).post("/acr", json={"product_version": "1.4.0"})
    assert r.status_code == 403


# ── the role algebra ──────────────────────────────────────────────────────────────────────────

def test_role_implications_are_explicit_and_one_directional():
    assert acr_authz.has_role("evaluator", ["approver"])
    assert acr_authz.has_role("editor", ["approver"])
    assert not acr_authz.has_role("approver", ["editor"])
    assert not acr_authz.has_role("approver", ["evaluator"])
    assert not acr_authz.has_role("approver", [])


def test_the_platform_owner_holds_every_role():
    assert acr_authz.effective_roles([], is_platform_owner=True) == acr_authz.ROLES


def test_publishing_a_published_report_is_refused():
    ok, why = acr_authz.may_publish(APPROVER, ["approver"], report={"status": "published"})
    assert not ok and "already published" in why


def test_the_separation_of_duties_warning_is_advisory_and_conditional():
    """PRD §18 words it as a recommendation conditioned on a second reviewer being available.
    A hard block would stop a one-person team publishing at all; silence would let the
    sole-decider case pass unremarked. It warns, and only when there is someone else to ask."""
    # Sole approver on the team — no warning, because there is no alternative to recommend.
    assert acr_authz.separation_warning(APPROVER, {APPROVER: 40}, other_approvers=0) is None
    # A second approver exists and this person made most of the decisions — warn.
    warn = acr_authz.separation_warning(APPROVER, {APPROVER: 40, EDITOR: 10}, other_approvers=1)
    assert warn and "second qualified reviewer" in warn
    # They made a minority of the decisions — no warning.
    assert acr_authz.separation_warning(APPROVER, {APPROVER: 10, EDITOR: 40},
                                        other_approvers=1) is None


def test_an_unknown_role_confers_nothing():
    assert acr_authz.effective_roles(["superuser"]) == frozenset()
    with pytest.raises(acr_authz.AcrForbidden):
        acr_authz.require("approver", ["superuser"], email=RANDOM)
