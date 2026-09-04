"""The default role every signed-in user gets, and the guard that keeps it from growing by itself.

OWNER DECISION, 2026-09-04, and the reason it needs its own test file rather than an edit to the
slice-1 tests: it REVERSES the unassigned case those files pin. Slices 1–3 resolved "no role
assigned" to no access, on the fail-closed principle. The decision is:

    All signed-in users receive a default `Platform User` RBAC role.
    That role grants visibility and access to every current tab.
    Administrators can later create restricted roles and reassign users.
    Access must still be enforced server-side; this is not merely hiding/showing tabs.
    Existing users should be backfilled automatically.
    New tabs should require an explicit capability decision rather than silently inheriting access.

THE REVERSAL IS NARROW, AND THE NARROWNESS IS THE POINT. Three situations produce "this user has
no role row", and they are not the same fact:

    nobody has narrowed them yet   -> Platform User. Being signed in is already an authorization
                                      decision (core.email_allowed admitted them); refusing here
                                      would mean turning enforcement on locks out the whole
                                      company until somebody assigns every person by hand.
    they were suspended            -> nothing. Access was deliberately withdrawn.
    they hold a role id that does
    not resolve                    -> nothing. Somebody DID narrow them and the row saying how is
                                      missing; defaulting to full access there would silently
                                      undo an administrator's decision.

The last two are still fail-closed, and this file checks all three rather than the happy one.

THE LAST CLAUSE IS THE ONE WITH TEETH. "New tabs should require an explicit capability decision
rather than silently inheriting access" is a claim about a tab that does not exist yet, which is
exactly the kind nobody remembers to keep true. test_a_new_tab_does_not_silently_join_the_default
_role makes it fail loudly at the moment a tab is added.
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
NEWCOMER = "new@hosp.org"
NARROWED = "narrow@hosp.org"


@pytest.fixture
def st(monkeypatch):
    import store as store_mod
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "acp-test.db")
    store = store_mod.Store()
    monkeypatch.setenv(wr.FLAG, "1")
    for email in (OWNER, NEWCOMER, NARROWED):
        store.upsert_person({"email": email, "role": "user", "status": "access_ready"})
    wr.seed_builtin_roles(store, tenant_id=OWNER)
    return store


def _suspended(store):
    def check(email):
        person = next((p for p in store.get_people() if p.get("email") == email), None)
        return (person or {}).get("status") == "suspended"
    return check


# ── the default itself ────────────────────────────────────────────────────────

def test_the_default_role_exists_and_covers_every_current_tab():
    """"That role grants visibility and access to every current tab." Asserted against TAB_KEYS
    so it cannot drift from what the product actually has."""
    role = rbac.BUILTIN_ROLES[rbac.PLATFORM_USER]
    assert set(role["tabs"]) == set(rbac.TAB_KEYS)
    assert set(role["tabs"].values()) == {rbac.OPERATE}


def test_a_signed_in_user_with_no_role_gets_it(st):
    access = wr.access_for_email(st, NEWCOMER, owner_email=OWNER, is_suspended=_suspended(st))
    assert access["enforced"] is True
    assert access["role"]["id"] == rbac.PLATFORM_USER
    assert access["defaulted"] is True, "the response should say the role was defaulted, not assigned"
    assert set(access["tabs"].values()) == {"operate"}


def test_the_default_is_not_platform_admin(st):
    """"Visibility and access to every current tab" is not "every administrative permission".
    PRD §5 keeps the seven grants separate on purpose, and a default that quietly included them
    would make managing people, roles and publishing available to everyone who can sign in."""
    access = wr.access_for_email(st, NEWCOMER, owner_email=OWNER, is_suspended=_suspended(st))
    caps = set(access["capabilities"])
    for grant in ("people.manage", "roles.manage", "release.publish", "workers.manage"):
        assert grant not in caps, f"the default role handed out {grant}"
    assert "remediate.run" in caps and "discover.run" in caps, "but the workflow must all work"


# ── the two cases that stay fail-closed ───────────────────────────────────────

def test_a_suspended_user_gets_nothing_not_the_default(st):
    st.upsert_person({"email": NEWCOMER, "status": "suspended"})
    access = wr.access_for_email(st, NEWCOMER, owner_email=OWNER, is_suspended=_suspended(st))
    assert access["capabilities"] == []
    assert set(access["tabs"].values()) == {"hidden"}


def test_a_role_that_does_not_resolve_gets_nothing_not_the_default(st):
    """The important half of the reversal. Somebody DID narrow this user; the row saying how is
    gone. Falling back to the default here would silently restore access an administrator
    deliberately removed — a fail-open dressed up as a sensible default."""
    st.upsert_workspace_role(tenant_id=OWNER, role_id="locked", name="Locked",
                             permissions={"overview": "view"}, expected_version=None)
    wr.assign_role(st, email=NARROWED, role_id="locked", actor=OWNER)
    st.delete_workspace_role(tenant_id=OWNER, role_id="locked")

    access = wr.access_for_email(st, NARROWED, owner_email=OWNER, is_suspended=_suspended(st))
    assert access["capabilities"] == []
    assert access.get("defaulted") is not True


def test_an_explicitly_narrowed_user_keeps_their_narrow_role(st):
    """The whole reason for having roles: an administrator's assignment must beat the default."""
    wr.assign_role(st, email=NARROWED, role_id=rbac.VIEWER, actor=OWNER)
    access = wr.access_for_email(st, NARROWED, owner_email=OWNER, is_suspended=_suspended(st))
    assert access["role"]["id"] == rbac.VIEWER
    assert access.get("defaulted") is not True
    assert "remediate.run" not in access["capabilities"]


def test_a_tenant_whose_roles_were_never_seeded_fails_closed(st, monkeypatch):
    """No default row means the tenant was never bootstrapped, and nothing about it can be
    trusted. Inventing the role from the catalog would paper over exactly the misconfiguration an
    operator needs to see — and the recovery is one owner-only bootstrap call away."""
    st.delete_workspace_role(tenant_id=OWNER, role_id=rbac.PLATFORM_USER)
    access = wr.access_for_email(st, NEWCOMER, owner_email=OWNER, is_suspended=_suspended(st))
    assert access["capabilities"] == []
    assert access["default_missing"] is True


# ── the backfill ──────────────────────────────────────────────────────────────

def test_the_migration_backfills_standard_users_onto_the_default(st):
    st.upsert_person({"email": "admin2@hosp.org", "role": "admin"})
    plan = {r["email"]: r["to"] for r in
            wr.migrate_people(st, tenant_id=OWNER, owner_email=OWNER)}
    assert plan[NEWCOMER] == rbac.PLATFORM_USER
    assert plan["admin2@hosp.org"] == rbac.PLATFORM_ADMIN
    assert plan[OWNER] == rbac.OWNER


def test_the_backfill_takes_nothing_away(st):
    """§15's rule, and the reason the backfill target changed from Compliance Manager: that role
    has Live Operations at View and Settings HIDDEN, so it would have removed two surfaces a
    standard user can reach today under OPEN_ACCESS."""
    default = rbac.builtin_capabilities(rbac.PLATFORM_USER)
    for tab_capability in (f"{t}.view" for t in ("overview", "sources", "discover", "assess",
                                                 "remediate", "release", "monitor", "operations",
                                                 "analytics", "settings")):
        assert tab_capability in default, f"the backfill would have removed {tab_capability}"


# ── the clause with teeth ─────────────────────────────────────────────────────

# Transcribed, not derived. A test that computed this from BUILTIN_ROLES would assert only that
# the code equals itself, and would keep passing when a new tab joined the role automatically —
# which is the exact thing it exists to prevent.
TABS_THE_DEFAULT_ROLE_WAS_GRANTED = {
    "overview", "integrations", "discover", "assess", "remediate",
    "publish", "monitor", "liveops", "analytics", "settings",
}


def test_a_new_tab_does_not_silently_join_the_default_role():
    """"New tabs should require an explicit capability decision rather than silently inheriting
    access" (owner, 2026-09-04).

    WHEN THIS FAILS, THE FIX IS A DECISION, NOT AN EDIT TO THIS SET. A tab was added to
    workspace_rbac.TABS. Someone has to say whether every signed-in user should reach it by
    default — and for a tab holding something sensitive the answer may well be no, in which case
    Platform User's grid changes and this set does not.

    Written as a set comparison rather than a subset check so it bites in BOTH directions: a tab
    silently gaining default access fails, and a tab silently losing it fails too.
    """
    granted = {tab for tab, level in rbac.BUILTIN_ROLES[rbac.PLATFORM_USER]["tabs"].items()
               if level != rbac.HIDDEN}
    assert granted == TABS_THE_DEFAULT_ROLE_WAS_GRANTED, (
        "the default role's tab set changed. If a tab was added to workspace_rbac.TABS, decide "
        "whether every signed-in user should reach it before adding it here.")


def test_the_guard_is_about_the_tabs_that_actually_exist():
    """If TAB_KEYS and the transcribed set drifted apart, the guard above would be checking a
    historical list — passing while saying nothing about the product as it is now."""
    assert set(rbac.TAB_KEYS) == TABS_THE_DEFAULT_ROLE_WAS_GRANTED, (
        "a governed tab exists that the default role has no recorded decision about")
