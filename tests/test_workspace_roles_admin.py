"""Role administration, and the six §14 rules that stop an administrator destroying their own
ability to administer.

THE CRUD IS NOT THE INTERESTING PART. Creating and listing roles is a handful of lines that either
work or obviously do not. What this file is about is that every rule in PRD §14 names a specific
way the Roles screen could hand somebody a locked workspace, and each one fails in a way that
looks like the feature working:

    editing Owner              the anti-lockout role stops being one, and nothing says so until
                               the day it is needed
    deleting a role in use     every holder's id resolves to nothing, which the gate correctly
                               reads as a refusal — a mass lockout that looks like enforcement
    duplicate names            the audit trail names two different things by one name
    a stale version            two administrators, two tabs, and one of them silently loses
    granting beyond yourself   a role-manager escalates to Owner in two clicks: build a role with
                               everything, assign it to self
    the last roles.manage      the rule that makes every refusal above recoverable

THE GATE IS `roles.manage`, NOT is_admin, and that is checked here explicitly. Under ACP's default
OPEN_ACCESS model core.is_admin() is True for EVERY authenticated user (api/core.py), so a naive
gate would let anyone who can sign in grant themselves anything — and would pass a test written on
a dev box with no owner configured, where is_admin returns True for everybody including the empty
string. Every test below configures an owner for exactly that reason.
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
MANAGER = "manager@hosp.org"      # holds roles.manage + people.manage, not everything
REVIEWER = "rev@hosp.org"
NOBODY = "nobody@hosp.org"


def _req(email):
    return SimpleNamespace(state=SimpleNamespace(user_email=email))


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
    # OPEN_ACCESS explicitly ON — the configuration these gates exist to survive.
    monkeypatch.setattr(core, "OPEN_ACCESS", True, raising=False)
    monkeypatch.setenv(wr.FLAG, "1")

    for email in (OWNER, MANAGER, REVIEWER, NOBODY):
        st.upsert_person({"email": email, "role": "user", "status": "access_ready"})
    wr.seed_builtin_roles(st, tenant_id=OWNER)
    # A role-manager who is NOT the owner and does NOT hold everything: the caller every
    # "cannot grant beyond yourself" test needs.
    st.upsert_workspace_role(
        tenant_id=OWNER, role_id="role-manager", name="Role Manager",
        permissions={"overview": "view", "remediate": "view",
                     "roles.manage": "granted", "people.manage": "granted"},
        expected_version=None)
    wr.assign_role(st, email=MANAGER, role_id="role-manager", actor=OWNER)
    wr.assign_role(st, email=REVIEWER, role_id=rbac.REMEDIATION_REVIEWER, actor=OWNER)
    return adm, core, st


# ── the gate ──────────────────────────────────────────────────────────────────

def test_being_an_admin_is_not_enough_to_manage_roles(env):
    """Under OPEN_ACCESS every signed-in user is an admin. If that were the gate, the Roles screen
    would be a self-service permission dispenser."""
    adm, core, _st = env
    assert core.is_admin(NOBODY), "the premise: OPEN_ACCESS makes everyone an admin"
    with pytest.raises(HTTPException) as exc:
        adm.list_roles(request=_req(NOBODY))
    assert exc.value.status_code == 403


def test_the_owner_and_a_role_manager_may_both_manage(env):
    adm, _core, _st = env
    assert adm.list_roles(request=_req(OWNER))["roles"]
    assert adm.list_roles(request=_req(MANAGER))["roles"]


def test_the_list_reports_how_many_users_hold_each_role(env):
    """On the role, not derived separately by the client — it is what decides whether Delete is
    offered, and a count the UI computes is one that can disagree with the one DELETE checks."""
    adm, _core, _st = env
    roles = {r["id"]: r for r in adm.list_roles(request=_req(OWNER))["roles"]}
    assert roles[rbac.REMEDIATION_REVIEWER]["users"] == 1
    assert roles["role-manager"]["users"] == 1
    assert roles[rbac.ANALYST]["users"] == 0


# ── Owner is immutable (PRD §4, §14) ──────────────────────────────────────────

def test_owner_cannot_be_edited_even_by_the_owner(env):
    """Refused outright rather than restricted to the owner. There is no edit that leaves the
    anti-lockout guarantee intact, so permitting one would only let the owner remove their own
    last resort — the single action with no recovery path."""
    adm, _core, _st = env
    with pytest.raises(HTTPException) as exc:
        adm.update_role(rbac.OWNER, {"name": "Owner", "tabs": {}, "grants": [], "version": 1},
                        request=_req(OWNER))
    assert exc.value.status_code == 409
    assert "lockout" in str(exc.value.detail).lower()


def test_owner_cannot_be_deleted(env):
    adm, _core, _st = env
    with pytest.raises(HTTPException) as exc:
        adm.delete_role(rbac.OWNER, request=_req(OWNER))
    assert exc.value.status_code == 409


def test_owner_can_be_duplicated_and_the_copy_is_ordinary(env):
    """PRD §4 allows duplicating a built-in. The COPY must be editable — that is what makes Owner
    duplicable without making it editable — and must actually carry Owner's capabilities rather
    than the subset its stored rows happen to list."""
    adm, _core, _st = env
    copy = adm.create_role({"name": "Deputy", "duplicate_of": rbac.OWNER}, request=_req(OWNER))
    assert copy["is_protected"] is False
    assert copy["is_system"] is False
    assert set(copy["capabilities"]) == rbac.CAPABILITIES
    adm.update_role(copy["id"], {"name": "Deputy", "tabs": {"overview": "view"}, "grants": [],
                                 "version": copy["version"]}, request=_req(OWNER))


# ── a role in use cannot be deleted (PRD §14) ─────────────────────────────────

def test_a_role_with_users_cannot_be_deleted_and_the_message_names_them(env):
    """Deleting it would leave every holder pointing at an id that resolves to nothing — which the
    gate reads as a refusal, so the result is a mass lockout that looks like enforcement."""
    adm, _core, _st = env
    with pytest.raises(HTTPException) as exc:
        adm.delete_role(rbac.REMEDIATION_REVIEWER, request=_req(OWNER))
    assert exc.value.status_code == 409
    assert REVIEWER in str(exc.value.detail)


def test_deleting_works_once_the_last_holder_is_reassigned(env):
    adm, _core, _st = env
    adm.assign_person_role(REVIEWER, {"role_id": rbac.ANALYST}, request=_req(OWNER))
    assert adm.delete_role(rbac.REMEDIATION_REVIEWER, request=_req(OWNER)) == {
        "deleted": rbac.REMEDIATION_REVIEWER}


# ── names are unique per tenant (PRD §14) ─────────────────────────────────────

@pytest.mark.parametrize("name", ["Analyst", "analyst", "  ANALYST  "])
def test_a_duplicate_name_is_refused_however_it_is_cased(env, name):
    """To a human reading the role list "Reviewer" and "reviewer" are the same name, and an audit
    row naming one of two identical roles identifies neither."""
    adm, _core, _st = env
    with pytest.raises(HTTPException) as exc:
        adm.create_role({"name": name, "tabs": {}, "grants": []}, request=_req(OWNER))
    assert exc.value.status_code == 409


def test_renaming_onto_another_roles_name_is_refused_but_keeping_your_own_is_fine(env):
    adm, _core, _st = env
    role = adm.get_role(rbac.ANALYST, request=_req(OWNER))
    with pytest.raises(HTTPException):
        adm.update_role(rbac.ANALYST, {"name": "Viewer", "tabs": {}, "grants": [],
                                       "version": role["version"]}, request=_req(OWNER))
    same = adm.update_role(rbac.ANALYST, {"name": "Analyst", "tabs": {"assess": "view"},
                                          "grants": [], "version": role["version"]},
                           request=_req(OWNER))
    assert same["name"] == "Analyst"


# ── concurrency (PRD §14) ─────────────────────────────────────────────────────

def test_a_second_administrator_cannot_silently_overwrite_the_first(env):
    adm, _core, _st = env
    role = adm.get_role(rbac.ANALYST, request=_req(OWNER))
    adm.update_role(rbac.ANALYST, {"name": "Analyst", "tabs": {"assess": "operate"},
                                   "grants": [], "version": role["version"]}, request=_req(OWNER))
    with pytest.raises(HTTPException) as exc:
        adm.update_role(rbac.ANALYST, {"name": "Analyst", "tabs": {"assess": "hidden"},
                                       "grants": [], "version": role["version"]},
                        request=_req(OWNER))
    assert exc.value.status_code == 409
    assert adm.get_role(rbac.ANALYST, request=_req(OWNER))["tabs"]["assess"] == "operate"


def test_omitting_the_version_is_refused_rather_than_treated_as_no_check(env):
    """A client that does not send a version has not read the role, and defaulting to "no check"
    is how the check stops being applied at the one call site that forgot it."""
    adm, _core, _st = env
    with pytest.raises(HTTPException) as exc:
        adm.update_role(rbac.ANALYST, {"name": "Analyst", "tabs": {}, "grants": []},
                        request=_req(OWNER))
    assert exc.value.status_code == 400


# ── you cannot grant what you do not hold (PRD §14) ───────────────────────────

def test_a_role_manager_cannot_build_a_role_more_powerful_than_their_own(env):
    """THE ESCALATION THIS CLOSES: without it, anyone with roles.manage creates a role holding
    everything, assigns it to themselves, and is Owner in two clicks — which makes every other
    rule in this file decorative."""
    adm, _core, _st = env
    with pytest.raises(HTTPException) as exc:
        adm.create_role({"name": "Superuser", "tabs": {k: "operate" for k in rbac.TAB_KEYS},
                         "grants": list(rbac.GRANT_CAPABILITIES)}, request=_req(MANAGER))
    assert exc.value.status_code == 403
    assert "do not hold yourself" in str(exc.value.detail)


def test_a_role_manager_can_build_a_role_within_their_own_ceiling(env):
    """The other direction — the rule must not make delegation impossible, only escalation."""
    adm, _core, _st = env
    made = adm.create_role({"name": "Junior", "tabs": {"overview": "view", "remediate": "view"},
                            "grants": []}, request=_req(MANAGER))
    assert set(made["capabilities"]) <= set(adm.list_capabilities(request=_req(MANAGER))["mine"])


def test_a_role_manager_cannot_escalate_by_duplicating_owner_either(env):
    """The same escalation with an extra step. Duplicating copies capabilities, so the ceiling has
    to apply to the copy — checking it only on the hand-built path leaves the door open."""
    adm, _core, _st = env
    with pytest.raises(HTTPException) as exc:
        adm.create_role({"name": "Deputy", "duplicate_of": rbac.OWNER}, request=_req(MANAGER))
    assert exc.value.status_code == 403


def test_a_role_manager_cannot_assign_a_role_beyond_their_own_ceiling(env):
    """And the same again through assignment, which is the shortest path of the three: no role
    needs building if an existing one already holds more than you do."""
    adm, _core, _st = env
    with pytest.raises(HTTPException) as exc:
        adm.assign_person_role(NOBODY, {"role_id": rbac.PLATFORM_ADMIN}, request=_req(MANAGER))
    assert exc.value.status_code == 403


def test_only_the_owner_may_assign_the_owner_role(env):
    adm, _core, _st = env
    with pytest.raises(HTTPException) as exc:
        adm.assign_person_role(NOBODY, {"role_id": rbac.OWNER}, request=_req(MANAGER))
    assert exc.value.status_code == 403
    assert adm.assign_person_role(NOBODY, {"role_id": rbac.OWNER}, request=_req(OWNER))


# ── assignment is a different permission from role design (PRD §5) ────────────

def test_designing_roles_and_deciding_who_holds_them_are_separate_permissions(env):
    adm, _core, st = env
    st.upsert_workspace_role(tenant_id=OWNER, role_id="designer", name="Designer",
                             permissions={"overview": "view", "roles.manage": "granted"},
                             expected_version=None)
    wr.assign_role(st, email=NOBODY, role_id="designer", actor=OWNER)
    assert adm.list_roles(request=_req(NOBODY))["roles"]      # may design
    with pytest.raises(HTTPException) as exc:                 # may not assign
        adm.assign_person_role(REVIEWER, {"role_id": rbac.ANALYST}, request=_req(NOBODY))
    assert exc.value.status_code == 403


# ── validation refuses rather than drops ──────────────────────────────────────

@pytest.mark.parametrize("body", [
    {"name": "X", "tabs": {"teleport": "operate"}, "grants": []},
    {"name": "X", "tabs": {"assess": "supervise"}, "grants": []},
    {"name": "X", "tabs": {}, "grants": ["nonsense.manage"]},
])
def test_an_unknown_tab_level_or_permission_is_refused_not_silently_dropped(env, body):
    """Dropping them would let a drawer built against a newer build save a role that means
    something different from what it displayed — the administrator reads one thing and the
    database stores another, with nothing to say so."""
    adm, _core, _st = env
    with pytest.raises(HTTPException) as exc:
        adm.create_role(body, request=_req(OWNER))
    assert exc.value.status_code == 400


@pytest.mark.parametrize("name", ["", "   ", "x" * 61])
def test_a_missing_or_overlong_name_is_refused(env, name):
    adm, _core, _st = env
    with pytest.raises(HTTPException) as exc:
        adm.create_role({"name": name, "tabs": {}, "grants": []}, request=_req(OWNER))
    assert exc.value.status_code == 400


# ── the catalog the drawer renders from ───────────────────────────────────────

def test_the_capability_catalog_is_served_rather_than_hardcoded_in_the_spa(env):
    """Two lists diverging is how a checkbox comes to do nothing — visibly ticked, silently
    ignored — which is worse than the permission not existing."""
    adm, _core, _st = env
    cat = adm.list_capabilities(request=_req(OWNER))
    assert [t["key"] for t in cat["tabs"]] == list(rbac.TAB_KEYS)
    assert {g["key"] for g in cat["grants"]} == set(rbac.GRANT_CAPABILITIES)
    assert cat["levels"] == list(rbac.ACCESS_LEVELS)
    assert cat["ungoverned_tabs"] == sorted(rbac.UNGOVERNED_TABS)


def test_the_catalog_tells_the_caller_what_they_may_grant(env):
    """So the drawer can disable what they cannot, rather than letting them design a role around
    a permission and be refused on save."""
    adm, _core, _st = env
    assert set(adm.list_capabilities(request=_req(OWNER))["mine"]) == rbac.CAPABILITIES
    mine = set(adm.list_capabilities(request=_req(MANAGER))["mine"])
    assert "roles.manage" in mine and "release.publish" not in mine


# ── the impact confirmation (PRD §9) ──────────────────────────────────────────

def test_the_impact_preview_says_what_is_gained_and_lost(env):
    """§9's confirmation. Computed server-side from the same resolver the gate uses — a preview
    that disagrees with what actually happens is worse than none, because it is read and
    approved."""
    adm, _core, _st = env
    out = adm.role_impact(REVIEWER, request=_req(OWNER), role_id=rbac.ANALYST)
    assert "discover.run" in out["gains"]
    assert "remediate.run" in out["loses"]
    assert out["role_id"] == rbac.ANALYST


def test_the_impact_of_removing_a_role_is_everything_lost(env):
    adm, _core, _st = env
    out = adm.role_impact(REVIEWER, request=_req(OWNER), role_id="")
    assert out["gains"] == []
    assert set(out["loses"]) == rbac.builtin_capabilities(rbac.REMEDIATION_REVIEWER)


# ── the rule that makes the others recoverable (PRD §14) ──────────────────────
# These run against an OWNERLESS deployment, and that is not a contrivance to make the guard
# fire — it is the only deployment where it can. With ACP_OWNER_EMAIL configured, `core.is_owner`
# grants that identity every capability unconditionally, so somebody who can manage roles always
# exists and the guard would only obstruct legitimate changes.
#
# A SEPARATE FIXTURE, because the tenant id is derived from the owner email (workspace_roles.
# tenant_id_for): an ownerless deployment is the tenant "default", not the same tenant with the
# owner blanked. Reusing `env` and clearing OWNER_EMAIL mid-test made every role 404 — which is
# itself worth knowing, and is pinned as its own test at the end of this block.

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
    assert tenant == "default"
    for email in (MANAGER, REVIEWER, NOBODY):
        st.upsert_person({"email": email, "role": "user", "status": "access_ready"})
    wr.seed_builtin_roles(st, tenant_id=tenant)
    st.upsert_workspace_role(
        tenant_id=tenant, role_id="role-manager", name="Role Manager",
        permissions={"overview": "view", "roles.manage": "granted", "people.manage": "granted"},
        expected_version=None)
    wr.assign_role(st, email=MANAGER, role_id="role-manager", actor=MANAGER)
    wr.assign_role(st, email=REVIEWER, role_id=rbac.VIEWER, actor=MANAGER)
    wr.assign_role(st, email=NOBODY, role_id=rbac.VIEWER, actor=MANAGER)
    return adm, core, st


def test_the_last_role_manager_cannot_demote_themselves(ownerless):
    """Every other refusal in this file is undoable by somebody with roles.manage. This is the one
    that keeps such a person existing — without it the last manager demoting themselves locks the
    workspace permanently, with no owner to appeal to."""
    adm, _core, _st = ownerless
    with pytest.raises(HTTPException) as exc:
        adm.assign_person_role(MANAGER, {"role_id": rbac.VIEWER}, request=_req(MANAGER))
    assert exc.value.status_code == 409
    assert "nobody able to manage roles" in str(exc.value.detail)


def test_demoting_is_allowed_once_somebody_else_holds_roles_manage(ownerless):
    """The guard must not make delegation impossible, only self-destruction."""
    adm, _core, st = ownerless
    wr.assign_role(st, email=NOBODY, role_id="role-manager", actor=MANAGER)
    assert adm.assign_person_role(MANAGER, {"role_id": rbac.VIEWER}, request=_req(MANAGER))


def test_a_suspended_role_manager_does_not_count_as_cover(ownerless):
    """§14 says "at least one NON-SUSPENDED user". A suspended holder has no effective
    permissions, so counting them is counting somebody who cannot act."""
    adm, _core, st = ownerless
    wr.assign_role(st, email=NOBODY, role_id="role-manager", actor=MANAGER)
    st.upsert_person({"email": NOBODY, "status": "suspended"})
    with pytest.raises(HTTPException) as exc:
        adm.assign_person_role(MANAGER, {"role_id": rbac.VIEWER}, request=_req(MANAGER))
    assert exc.value.status_code == 409


def test_a_configured_owner_makes_the_lockout_impossible_so_the_rule_does_not_bite(env):
    """With an owner, there is always a way back, so the guard would only be obstructing."""
    adm, _core, _st = env
    assert adm.assign_person_role(MANAGER, {"role_id": rbac.VIEWER}, request=_req(OWNER))


def test_changing_the_owner_email_rehomes_every_role_to_a_new_tenant(env, monkeypatch):
    """FOUND BY A TEST THAT WAS WRONG ABOUT SOMETHING ELSE, and worth pinning because the
    consequence is severe and non-obvious.

    The tenant id is the owner email (workspace_roles.tenant_id_for), following this repo's own
    convention — api/store.py says owner_email is the tenant identifier until a real one exists.
    So changing ACP_OWNER_EMAIL moves the whole role set out from under every assignment: each
    person's role id resolves to nothing, which PRD §14 requires the gate to read as a refusal.
    The result is a workspace-wide lockout produced by an environment-variable edit.

    It is RECOVERABLE — the new owner holds every capability by the `core.is_owner` carve-out, and
    re-running the bootstrap re-seeds — and it is consistent with how scans already behave here.
    Pinned rather than fixed because changing the tenancy model is its own change, not something
    to smuggle into a Roles screen.
    """
    adm, core, _st = env
    assert adm.list_roles(request=_req(OWNER))["roles"], "roles exist under the original owner"
    monkeypatch.setattr(core, "OWNER_EMAIL", "someone-else@hosp.org", raising=False)
    with pytest.raises(HTTPException) as exc:
        adm.get_role(rbac.ANALYST, request=_req("someone-else@hosp.org"))
    assert exc.value.status_code == 404


# ── audit (PRD §12) ───────────────────────────────────────────────────────────

def test_every_role_change_is_recorded_with_an_actor(env):
    adm, _core, st = env
    made = adm.create_role({"name": "Temp", "tabs": {"overview": "view"}, "grants": []},
                           request=_req(OWNER))
    adm.update_role(made["id"], {"name": "Temp", "tabs": {"overview": "operate"}, "grants": [],
                                 "version": made["version"]}, request=_req(OWNER))
    adm.delete_role(made["id"], request=_req(OWNER))
    actions = [(d["action"], d["actor"]) for d in st.list_decisions()
               if d["action"].startswith("role.")]
    for action in ("role.created", "role.updated", "role.deleted"):
        assert (action, OWNER) in actions, f"{action} missing from the audit trail"
