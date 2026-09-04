"""Zero Owner-lockout paths (PRD §18), enumerated rather than sampled.

WHY THIS FILE EXISTS SEPARATELY from the four RBAC test files that already touch the owner. Each
of those checks the owner survives one thing — a missing role row, a deleted role, an unseeded
tenant — as a detail of whatever else it was testing. What none of them establishes is the claim
§18 actually makes, which is a UNIVERSAL: there is no sequence of legitimate administrative
actions that ends with nobody able to administer.

That is not provable by sampling, and it is the one failure with no recovery path. Every other
mistake in this feature is undoable by somebody with `roles.manage`; a lockout is the state where
that somebody does not exist. So the tests below walk the ways in DELIBERATELY — the destructive
operations, in the order an administrator would reach them — rather than checking the owner in
passing.

TWO DISTINCT GUARANTEES, and conflating them is how a reviewer concludes the feature is safer
than it is:

  1. WITH AN OWNER CONFIGURED (ACP_OWNER_EMAIL) lockout is IMPOSSIBLE, not merely unlikely. The
     carve-out in access_for_email returns every capability before any lookup runs, so no row, no
     assignment and no deletion can take it away. That is what the first block checks.
  2. WITHOUT ONE — local dev, demo, a deployment that never set the variable — there is no
     standing holder, and the only thing between the workspace and a permanent lockout is the
     "at least one non-suspended user must retain roles.manage" guard. That is a weaker
     guarantee and the second block treats it as such.

A DEPLOYMENT WITH NO OWNER IS THE DANGEROUS ONE, which is worth saying out loud because it is
also the default in development, where most of this code gets exercised.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

ACP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ACP / "api"))

import workspace_rbac as rbac        # noqa: E402
import workspace_roles as wr         # noqa: E402

OWNER = "owner@hosp.org"
ADMIN = "admin@hosp.org"
USER = "user@hosp.org"


def _req(email):
    return SimpleNamespace(state=SimpleNamespace(user_email=email))


def _suspended(store):
    def check(email):
        p = next((x for x in store.get_people() if x.get("email") == email), None)
        return (p or {}).get("status") == "suspended"
    return check


def _can_administer(store, email, owner_email):
    """Does this identity still hold roles.manage — i.e. can they undo whatever just happened?"""
    access = wr.access_for_email(store, email, owner_email=owner_email,
                                 is_suspended=_suspended(store))
    return "roles.manage" in (access.get("capabilities") or [])


@pytest.fixture
def env(monkeypatch):
    import core
    import store as store_mod
    import routes.workspace_roles_admin as adm

    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "acp-test.db")
    st = store_mod.Store()
    monkeypatch.setattr(core, "OWNER_EMAIL", OWNER, raising=False)
    monkeypatch.setattr(core, "store", st, raising=False)
    monkeypatch.setattr(core, "get_store", lambda: st, raising=False)
    monkeypatch.setattr(core, "OPEN_ACCESS", True, raising=False)
    monkeypatch.setenv(wr.FLAG, "1")
    for email in (OWNER, ADMIN, USER):
        st.upsert_person({"email": email, "role": "user", "status": "access_ready"})
    wr.seed_builtin_roles(st, tenant_id=OWNER)
    wr.assign_role(st, email=ADMIN, role_id=rbac.PLATFORM_ADMIN, actor=OWNER)
    wr.assign_role(st, email=USER, role_id=rbac.VIEWER, actor=OWNER)
    return adm, core, st


# ── 1. with an owner configured, lockout is impossible ────────────────────────

def test_the_owner_can_administer_at_the_start(env):
    """The premise. Every test below asserts this is STILL true after something destructive, and
    each of them would pass vacuously if it were false from the beginning."""
    _adm, core, st = env
    assert _can_administer(st, OWNER, core.OWNER_EMAIL)


def test_deleting_every_role_in_the_tenant_does_not_lock_the_owner_out(env):
    """The most destructive thing the Roles screen can do, done exhaustively. Owner is refused at
    the route, so this goes through the store directly — which is the point: even a database in
    that state must leave the owner able to fix it."""
    _adm, core, st = env
    for role in st.list_workspace_roles(tenant_id=OWNER):
        st.delete_workspace_role(tenant_id=OWNER, role_id=role["id"])
    assert st.list_workspace_roles(tenant_id=OWNER) == []
    assert _can_administer(st, OWNER, core.OWNER_EMAIL)


def test_unassigning_the_owners_own_role_does_not_lock_them_out(env):
    _adm, core, st = env
    wr.assign_role(st, email=OWNER, role_id=None, actor=OWNER)
    assert _can_administer(st, OWNER, core.OWNER_EMAIL)


def test_assigning_the_owner_the_narrowest_role_does_not_lock_them_out(env):
    """A Viewer holds no administrative permission at all. The carve-out has to beat an explicit
    assignment, or an administrator could demote the owner by accident."""
    _adm, core, st = env
    wr.assign_role(st, email=OWNER, role_id=rbac.VIEWER, actor=OWNER)
    assert _can_administer(st, OWNER, core.OWNER_EMAIL)


def test_a_corrupt_owner_role_row_does_not_lock_them_out(env):
    """Not a hypothetical shape: a partially-applied migration, or a role edited to nothing."""
    _adm, core, st = env
    st.upsert_workspace_role(tenant_id=OWNER, role_id=rbac.OWNER, name="Owner",
                             permissions={}, is_system=True, is_protected=True,
                             expected_version=None)
    assert _can_administer(st, OWNER, core.OWNER_EMAIL)


def test_marking_the_owner_suspended_does_not_lock_them_out(env):
    """Deliberate, and worth stating because it cuts against §14's suspension rule. Suspension is
    an administrative action taken ON somebody; applied to the anti-lockout identity it would end
    the workspace, and the People screen already refuses to change the owner. Checked here so the
    two cannot drift apart — if suspension ever started reaching the owner, this fails."""
    _adm, core, st = env
    st.upsert_person({"email": OWNER, "status": "suspended"})
    assert _can_administer(st, OWNER, core.OWNER_EMAIL)


def test_the_tenant_being_unseeded_does_not_lock_the_owner_out(env):
    """A fresh deploy where the bootstrap never ran. Every other identity fails closed here — the
    owner is what makes running the bootstrap possible at all."""
    _adm, core, st = env
    for role in st.list_workspace_roles(tenant_id=OWNER):
        st.delete_workspace_role(tenant_id=OWNER, role_id=role["id"])
    assert not _can_administer(st, USER, core.OWNER_EMAIL), "the premise: others ARE locked out"
    assert _can_administer(st, OWNER, core.OWNER_EMAIL)


def test_the_owner_role_cannot_be_edited_or_deleted_through_the_route(env):
    """The route-level half. The two tests above prove the owner survives a database in a bad
    state; these prove the supported path cannot PUT it in one."""
    adm, _core, _st = env
    with pytest.raises(HTTPException) as edit:
        adm.update_role(rbac.OWNER, {"name": "Owner", "tabs": {}, "grants": [], "version": 1},
                        request=_req(OWNER))
    assert edit.value.status_code == 409
    with pytest.raises(HTTPException) as delete:
        adm.delete_role(rbac.OWNER, request=_req(OWNER))
    assert delete.value.status_code == 409


def test_no_administrator_can_reassign_the_owner_role_away_from_the_owner(env):
    """Only the current Owner may assign Owner (PRD §4) — so a Platform Admin cannot hand it to
    themselves, and by the carve-out the real owner keeps it regardless of who holds the role."""
    adm, core, st = env
    with pytest.raises(HTTPException) as exc:
        adm.assign_person_role(ADMIN, {"role_id": rbac.OWNER}, request=_req(ADMIN))
    assert exc.value.status_code == 403
    assert _can_administer(st, OWNER, core.OWNER_EMAIL)


def test_a_sequence_of_every_destructive_action_still_leaves_the_owner_able_to_recover(env):
    """The universal claim, run as one sequence rather than as isolated cases — because the
    failure §18 is about is a COMBINATION nobody tested, not any single step.

    Ends by actually recovering: re-seeding through the owner's own route, which is the recovery
    path an operator would use. A test that only asserted `_can_administer` would prove they hold
    a capability, not that anything can be done with it.
    """
    adm, core, st = env
    wr.assign_role(st, email=OWNER, role_id=rbac.VIEWER, actor=ADMIN)
    st.upsert_person({"email": OWNER, "status": "suspended"})
    wr.assign_role(st, email=ADMIN, role_id=None, actor=OWNER)
    for role in st.list_workspace_roles(tenant_id=OWNER):
        st.delete_workspace_role(tenant_id=OWNER, role_id=role["id"])

    assert _can_administer(st, OWNER, core.OWNER_EMAIL)
    recovered = adm.list_roles(request=_req(OWNER))
    assert {r["id"] for r in recovered["roles"]} == set(rbac.BUILTIN_ROLES), (
        "the owner could not re-seed the tenant, so holding the capability was not enough")


# ── 2. WITHOUT an owner, the guarantee is weaker and rests on one guard ───────

@pytest.fixture
def ownerless(monkeypatch):
    import core
    import store as store_mod
    import routes.workspace_roles_admin as adm

    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "acp-test.db")
    st = store_mod.Store()
    monkeypatch.setattr(core, "OWNER_EMAIL", "", raising=False)
    monkeypatch.setattr(core, "store", st, raising=False)
    monkeypatch.setattr(core, "get_store", lambda: st, raising=False)
    monkeypatch.setattr(core, "OPEN_ACCESS", True, raising=False)
    monkeypatch.setenv(wr.FLAG, "1")
    tenant = wr.tenant_id_for("")
    for email in (ADMIN, USER):
        st.upsert_person({"email": email, "role": "user", "status": "access_ready"})
    wr.seed_builtin_roles(st, tenant_id=tenant)
    wr.assign_role(st, email=ADMIN, role_id=rbac.PLATFORM_ADMIN, actor=ADMIN)
    wr.assign_role(st, email=USER, role_id=rbac.VIEWER, actor=ADMIN)
    return adm, core, st


def test_without_an_owner_the_last_administrator_cannot_demote_themselves(ownerless):
    adm, _core, _st = ownerless
    with pytest.raises(HTTPException) as exc:
        adm.assign_person_role(ADMIN, {"role_id": rbac.VIEWER}, request=_req(ADMIN))
    assert exc.value.status_code == 409
    assert "nobody able to manage roles" in str(exc.value.detail)


def test_without_an_owner_they_still_hold_it_after_the_refusal(ownerless):
    """A refusal that had already half-applied would be worse than no guard: the message says the
    change was rejected while the workspace is locked anyway."""
    adm, core, st = ownerless
    with pytest.raises(HTTPException):
        adm.assign_person_role(ADMIN, {"role_id": rbac.VIEWER}, request=_req(ADMIN))
    assert _can_administer(st, ADMIN, "")


def test_without_an_owner_deleting_the_last_admin_role_is_refused_while_it_is_held(ownerless):
    """The other route to the same end state. Blocking self-demotion is not enough if the role
    itself can be deleted out from under everyone who holds it."""
    adm, _core, _st = ownerless
    with pytest.raises(HTTPException) as exc:
        adm.delete_role(rbac.PLATFORM_ADMIN, request=_req(ADMIN))
    assert exc.value.status_code == 409
    assert ADMIN in str(exc.value.detail)


def test_without_an_owner_a_second_administrator_makes_demotion_legitimate(ownerless):
    """The guard must prevent self-destruction, not delegation — otherwise the first
    administrator can never hand over."""
    adm, core, st = ownerless
    wr.assign_role(st, email=USER, role_id=rbac.PLATFORM_ADMIN, actor=ADMIN)
    assert adm.assign_person_role(ADMIN, {"role_id": rbac.VIEWER}, request=_req(ADMIN))
    assert _can_administer(st, USER, "")


def test_the_ownerless_guarantee_is_weaker_and_this_records_how(ownerless):
    """WHAT IS NOT PROTECTED WITHOUT AN OWNER, asserted so the gap is visible rather than assumed
    away. The route guard covers the supported paths; a direct store write does not go through it,
    and there is no carve-out to fall back on. On a deployment with ACP_OWNER_EMAIL set this state
    is unreachable — which is the argument for setting it, and the reason this test says so here
    rather than leaving the difference to be inferred.
    """
    _adm, core, st = ownerless
    wr.assign_role(st, email=ADMIN, role_id=rbac.VIEWER, actor=ADMIN)   # bypasses the route guard
    assert not _can_administer(st, ADMIN, "")
    assert not _can_administer(st, USER, "")
