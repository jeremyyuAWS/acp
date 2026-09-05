"""Just-in-time roster creation: a domain-admitted user becomes a person an administrator can see.

THE GAP. `core.email_allowed` admits three kinds of identity — the protected owner, an allow-listed
address, and anyone under `ACP_ALLOWED_DOMAINS`. Only the first two are ENUMERABLE. A domain is a
rule, not a list, so a domain-admitted user could sign in and use the product while appearing on no
screen an administrator could act from: no row on People, therefore no role dropdown, therefore no
way to narrow them.

AND THEY WERE NOT LOCKED OUT — THEY WERE SILENTLY ELEVATED, which is the half that makes this a
security fix rather than a usability one. `_enforced_decision` hands an unassigned signed-in user
the default Platform User role: every workflow tab at Operate. So `ACP_ALLOWED_DOMAINS=acme.com`
was, in effect, granting operator access to everyone at the company, from a variable that reads
like an authentication setting. test_the_old_behaviour_was_an_over_grant_not_a_lockout pins that,
because a fix nobody understands the shape of gets reverted by the next person who finds the extra
records surprising.

THE OWNER'S DECISION (2026-09-05), implemented here: "Domain-wide access permits authentication,
not automatic privileges. On first successful sign-in, create a workspace-person record. Assign a
configurable least-privilege default role, ideally Viewer. If no default is configured, show
'Access pending'... Do not enumerate or import the entire organization directory; only register
people who actually sign in or are explicitly invited."
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
NEWCOMER = "newcomer@hosp.org"       # admitted by the DOMAIN alone — on no list anywhere
OUTSIDER = "someone@elsewhere.test"


# NO `importlib.reload` ANYWHERE IN THIS FILE, DELIBERATELY.
#
# The first version of it reloaded `routes.system` and `routes.workspace_roles_admin` inside four
# tests, to be sure they saw the monkeypatched core. They already did: those modules do
# `import core` and read `core.store` / `core.OWNER_EMAIL` at CALL time, so patching the attribute
# is enough and the reloads bought nothing.
#
# What they cost was real and showed up nowhere near here. A reload rebinds the module object's
# globals while every module that already imported FROM it keeps the old references, so the suite
# ends up with two live copies of one module and no way to tell which a given caller holds. Two
# SharePoint cursor tests — test_sp_freshness and test_sp_live_coverage, which have nothing to do
# with roles — began failing in the full-suite run only, passing in isolation and passing next to
# this file, which is the signature of exactly that.
#
# If a test here ever seems to need a fresh module, the thing to reach for is another monkeypatch,
# not a reload.
@pytest.fixture
def env(monkeypatch):
    """A workspace with a domain rule, an owner, and a store nobody has touched.

    `default_role` is set per-test through `configure` rather than in the fixture, because the two
    interesting deployments differ by exactly that one variable and the difference is the feature.
    """
    import core
    import store as store_mod

    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "acp-test.db")
    st = store_mod.Store()
    monkeypatch.setattr(core, "store", st, raising=False)
    monkeypatch.setattr(core, "get_store", lambda: st, raising=False)
    monkeypatch.setattr(core, "OWNER_EMAIL", OWNER, raising=False)
    monkeypatch.setattr(core, "ALLOWED_DOMAINS", ["hosp.org"], raising=False)
    monkeypatch.setattr(core, "ALLOWED_EMAILS", set(), raising=False)
    monkeypatch.setattr(core, "ADMIN_EMAILS", set(), raising=False)
    monkeypatch.setenv("ACP_WORKSPACE_RBAC_MODE", "enforce")
    st.set_allowlist([OWNER])
    wr.seed_builtin_roles(st, tenant_id=OWNER)

    def configure(default_role):
        # The memo is process-local and this module is imported once for the whole session, so a
        # test that skipped this would inherit whatever the previous one remembered — and would
        # pass or fail depending on the order pytest happened to run them in.
        core.forget_rostered()
        monkeypatch.setattr(core, "DEFAULT_SIGNIN_ROLE", default_role, raising=False)
        return core, st

    return configure


def access(st, email):
    import core
    return wr.access_for_email(st, email, owner_email=core.OWNER_EMAIL)


def visible_tabs(payload):
    return sorted(k for k, v in (payload.get("tabs") or {}).items() if v != "hidden")


# ── the premise ───────────────────────────────────────────────────────────────

def test_the_old_behaviour_was_an_over_grant_not_a_lockout(env):
    """WHAT THIS FEATURE ACTUALLY FIXES, asserted so the reason survives.

    Before any record exists, the resolver reaches its unassigned branch and hands out Platform
    User — every workflow tab at Operate. That is the behaviour `ACP_ALLOWED_DOMAINS` alone used
    to buy, and it is why "they could not be given a role" understated the problem: they already
    had one, chosen by nobody.
    """
    _core, st = env("viewer")
    before = access(st, NEWCOMER)
    assert before["role"]["id"] == rbac.PLATFORM_USER
    assert before.get("defaulted") is True
    assert len(visible_tabs(before)) == 10, visible_tabs(before)


def test_a_domain_admitted_user_is_on_no_screen_until_they_sign_in(env):
    """The other half of the premise, and the reason the fix is JUST-IN-TIME rather than a sync.

    Nobody can be listed before they arrive: a domain is a rule over an address space, and this
    repository never sees the directory behind it. So the roster cannot be built in advance, only
    accumulated — which is also the privacy property the owner asked for ("do not enumerate or
    import the entire organization directory").
    """
    core, _st = env("viewer")
    assert core.person_with_access(NEWCOMER) is None
    assert core.email_allowed(NEWCOMER), "the premise: the domain admits them regardless"


# ── first sign-in ─────────────────────────────────────────────────────────────

def test_first_sign_in_creates_the_record_and_the_least_privilege_role(env):
    core, st = env("viewer")
    core.note_signed_in(NEWCOMER, provider="google")

    person = core.person_with_access(NEWCOMER)
    assert person is not None, "the newcomer is still invisible to an administrator"
    assert person["provider"] == "google"
    assert person["admitted_via"] == "domain"
    assert person["first_signed_in_at"]
    assert person[wr.ROLE_FIELD] == rbac.VIEWER

    granted = access(st, NEWCOMER)
    assert granted["role"]["id"] == rbac.VIEWER
    assert len(visible_tabs(granted)) < 10, "Viewer must not see everything Platform User does"


def test_the_default_role_is_configurable(env):
    """"Configurable least-privilege default role, IDEALLY Viewer" — ideally, not only. A
    deployment that wants new arrivals to land as Analysts says so in one variable."""
    core, _st = env(rbac.ANALYST)
    core.note_signed_in(NEWCOMER, provider="google")
    assert core.person_with_access(NEWCOMER)[wr.ROLE_FIELD] == rbac.ANALYST


def test_the_person_appears_on_the_people_screen_immediately(env):
    """The point of the whole exercise: a row for the administrator to act on. Asserted against
    the payload the screen actually renders, not against the store underneath it — those two
    disagreed once before (#1407) and the disagreement was invisible from either side alone."""
    core, _st = env("viewer")
    core.note_signed_in(NEWCOMER, provider="google")

    import routes.system as system
    listed = {p["email"] for p in system._people_payload()["people"]}
    assert NEWCOMER in listed


def test_an_administrator_can_then_change_the_role(env):
    """End to end, through the real endpoint. The dead end was that this call answered 404."""
    from types import SimpleNamespace

    core, st = env("viewer")
    core.note_signed_in(NEWCOMER, provider="google")

    import routes.workspace_roles_admin as adm
    adm.assign_person_role(NEWCOMER, {"role_id": rbac.REMEDIATION_REVIEWER},
                           request=SimpleNamespace(state=SimpleNamespace(user_email=OWNER)))
    assert core.person_with_access(NEWCOMER)[wr.ROLE_FIELD] == rbac.REMEDIATION_REVIEWER
    assert access(st, NEWCOMER)["role"]["id"] == rbac.REMEDIATION_REVIEWER


# ── what it must NOT do ───────────────────────────────────────────────────────

def test_it_does_not_add_anyone_to_the_allowlist(env):
    """THE ONE THAT WOULD BE HARD TO NOTICE AND EXPENSIVE TO UNDO.

    The allowlist is a GRANT that outlives the domain rule; a record is only a record. Writing
    domain arrivals into it would quietly convert "everyone at hosp.org may sign in, until we say
    otherwise" into a permanent per-person entitlement that SURVIVES removing the domain — so the
    administrator who revokes a company's access would find hundreds of individual grants still
    standing, and no reason to suspect it.
    """
    core, st = env("viewer")
    core.note_signed_in(NEWCOMER, provider="google")
    assert st.get_allowlist() == [OWNER]
    assert core.person_with_access(NEWCOMER) is not None, "the record was created all the same"


def test_a_later_sign_in_never_re_defaults_an_administrators_decision(env):
    """Assignment is a decision; sign-in is an event. If the event overwrote the decision, an
    administrator could narrow somebody on Monday and find them widened by Tuesday's login, with
    the audit trail showing `system` undoing a person's work.

    The memo is cleared first to simulate the restart that makes this reachable at all — with it
    warm the second call returns before touching anything, which would pass this test for a reason
    that has nothing to do with the guard being tested.
    """
    core, _st = env("viewer")
    core.note_signed_in(NEWCOMER, provider="google")
    import core as core_mod
    wr.assign_role(core_mod.store, email=NEWCOMER, role_id=rbac.ANALYST, actor=OWNER)

    core.forget_rostered()
    core.note_signed_in(NEWCOMER, provider="google")
    assert core.person_with_access(NEWCOMER)[wr.ROLE_FIELD] == rbac.ANALYST


def test_signing_in_twice_writes_one_record(env):
    core, st = env("viewer")
    core.note_signed_in(NEWCOMER, provider="google")
    core.note_signed_in(NEWCOMER, provider="google")
    core.forget_rostered()
    core.note_signed_in(NEWCOMER, provider="google")
    rows = [p for p in st.get_people() if p["email"] == NEWCOMER]
    assert len(rows) == 1
    first_sign_ins = [d for d in st.list_decisions() if d["action"] == "person.first_sign_in"]
    assert len(first_sign_ins) == 1, "first sign-in was logged more than once"


def test_an_empty_or_malformed_identity_creates_nothing(env):
    """The gate should never hand this an empty string, and "the other check happens to stop it"
    is not a reason for this one to be wrong — the same reasoning that put the `if not who` guard
    in the resolver after an anonymous caller reached its default branch."""
    core, st = env("viewer")
    for bad in (None, "", "   ", "not-an-email"):
        assert core.note_signed_in(bad) is None
    assert [p["email"] for p in st.get_people()] == []


# ── no default configured: pending, not Platform User ─────────────────────────

def test_with_no_default_the_person_is_held_pending(env):
    core, st = env("")
    core.note_signed_in(NEWCOMER, provider="microsoft")

    person = core.person_with_access(NEWCOMER)
    assert person["status"] == "pending"
    assert person.get(wr.ROLE_FIELD) is None

    held = access(st, NEWCOMER)
    assert held["pending"] is True
    assert held["capabilities"] == []
    assert visible_tabs(held) == []


def test_pending_does_not_fall_through_to_the_platform_user_default(env):
    """THE TRAP THIS FEATURE WOULD MOST EASILY FALL INTO, and it fails silently in the direction
    of more access. "Pending" and "unassigned" both have no role id, and the resolver's unassigned
    branch grants Platform User by an explicit earlier owner decision. Without the stored status
    to tell them apart, a deployment that configured no default — i.e. one that asked for arrivals
    to WAIT — would hand every arrival every workflow tab, and the screen would say Platform User
    while the operator believed nobody had been let in.
    """
    core, st = env("")
    core.note_signed_in(NEWCOMER, provider="microsoft")
    held = access(st, NEWCOMER)
    assert (held.get("role") or {}).get("id") != rbac.PLATFORM_USER
    assert held.get("defaulted") is not True


def test_an_unassigned_person_who_is_not_pending_still_gets_platform_user(env):
    """THE CONTROL. Without it, "pending yields nothing" is satisfiable by breaking the default
    for everyone — which would empty the product for every existing user the moment enforcement
    was turned on, the outcome PRD §15 forbids in the migration.
    """
    core, st = env("")
    core.store.upsert_person({"email": "legacy@hosp.org", "role": "user",
                              "status": "access_ready"})
    resolved = access(st, "legacy@hosp.org")
    assert resolved["role"]["id"] == rbac.PLATFORM_USER
    assert resolved.get("defaulted") is True


def test_an_administrator_can_lift_a_pending_person_out_of_the_queue(env):
    """The queue has to have an exit, and it is the ordinary role dropdown."""
    from types import SimpleNamespace

    core, st = env("")
    core.note_signed_in(NEWCOMER, provider="microsoft")

    import routes.workspace_roles_admin as adm
    adm.assign_person_role(NEWCOMER, {"role_id": rbac.VIEWER},
                           request=SimpleNamespace(state=SimpleNamespace(user_email=OWNER)))
    lifted = access(st, NEWCOMER)
    assert lifted["role"]["id"] == rbac.VIEWER
    assert lifted.get("pending") is not True


# ── the audit trail (PRD §12) ─────────────────────────────────────────────────

def test_first_sign_in_and_the_role_source_are_both_audited(env):
    """"Record first sign-in, role source, assignment changes, and assigning administrator."

    Two rows, not one, because they are two facts: a person arrived, and a role was granted. The
    grant goes through `wr.assign_role` — the same function an administrator's click uses — so
    there is exactly one way a role is ever recorded, and therefore one place the audit trail can
    be wrong.
    """
    core, st = env("viewer")
    core.note_signed_in(NEWCOMER, provider="google")
    rows = {(d["action"], d["actor"]): d.get("detail") or "" for d in st.list_decisions()}

    assert ("person.first_sign_in", "system") in rows
    detail = rows[("person.first_sign_in", "system")]
    assert "admitted via domain" in detail and rbac.VIEWER in detail

    assert ("role.assigned", "system:first-sign-in") in rows, (
        "the automatic grant is attributed to a person or to nobody; an audit reader cannot tell "
        "an administrator's decision from the system's default")


def test_an_administrators_later_change_names_the_administrator(env):
    from types import SimpleNamespace

    core, st = env("viewer")
    core.note_signed_in(NEWCOMER, provider="google")
    import routes.workspace_roles_admin as adm
    adm.assign_person_role(NEWCOMER, {"role_id": rbac.ANALYST},
                           request=SimpleNamespace(state=SimpleNamespace(user_email=OWNER)))
    assigned = [d for d in st.list_decisions() if d["action"] == "role.assigned"]
    assert OWNER in {d["actor"] for d in assigned}
    assert any(f"{rbac.VIEWER} → {rbac.ANALYST}" in (d.get("detail") or "") for d in assigned)


# ── removal ───────────────────────────────────────────────────────────────────

def test_removing_a_person_clears_the_memo_so_they_are_seen_again(env):
    """Removal must not make somebody permanently invisible to THIS process. The memo exists only
    to avoid a store read per request; if it outlived the record it would defeat the feature for
    exactly the people an administrator had most recently been looking at.

    Note what removal does NOT do: it does not revoke a domain admission. They come back with the
    configured default on their next sign-in — suspension is the action that withholds access,
    removal is the one that forgets.
    """
    core, st = env("viewer")
    core.note_signed_in(NEWCOMER, provider="google")
    st.remove_person(NEWCOMER)
    core.forget_rostered(NEWCOMER)

    core.note_signed_in(NEWCOMER, provider="google")
    assert core.person_with_access(NEWCOMER) is not None


def test_the_gate_is_where_this_runs(env):
    """A guard on the WIRING, not on the function. Everything above tests `note_signed_in` in
    isolation, and would pass just as happily if nobody ever called it — the feature would then be
    a well-tested function that never runs, which is the failure mode this repository has recorded
    more than once.
    """
    source = (ACP / "api" / "app.py").read_text(encoding="utf-8")
    assert "core.note_signed_in(" in source, (
        "the access gate no longer records sign-ins; just-in-time roster creation is dead code")
    gate = source[source.index("request.state.user_email = email"):]
    assert "core.note_signed_in(" in gate[:1200], (
        "note_signed_in moved away from the point where an identity has just been admitted")
