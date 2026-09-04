"""GET /me/access — what one identity may see and do, and what happens when that cannot be told.

THE FOUR WAYS THIS RESOLVES, and the order they are checked in, are the whole design:

  1. the protected owner   → everything, always, BEFORE the flag or any lookup can fail
  2. the flag is off       → today's access, unchanged, plus what the role WOULD give
  3. a role that resolves  → what that role grants
  4. anything else         → nothing

Case 4 is the one worth writing tests for, because it is three different situations — nobody has
assigned this person a role, the person is suspended, the assigned role id names a row that is not
there — and all three are cases where ACP CANNOT ESTABLISH what somebody may do. The tempting
reading of each is "so leave them as they were", and that is the reading PRD §14 forbids: "Failure
to load permissions must fail closed for sensitive operations."

Case 1 is checked first for a reason that only shows up in the failure: an owner locked out by a
bad row is the single state with no recovery path, because nobody else can grant the role back.

WHAT THIS FILE IS NOT. It does not prove any route enforces anything. `/me/access` describes
authorization; it is not authorization, and slice 4 is where routes start refusing. A green file
here is compatible with every API being wide open, which is why PRD §11 says hiding a tab is not
a security control.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

ACP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ACP / "api"))

import workspace_rbac as rbac        # noqa: E402
import workspace_roles as wr         # noqa: E402

OWNER = "owner@hosp.org"
REVIEWER = "rev@hosp.org"
NOBODY = "nobody@hosp.org"


def _req(email):
    return SimpleNamespace(state=SimpleNamespace(user_email=email))


@pytest.fixture
def env(monkeypatch):
    """A real Store, an owner, and one person carrying a real Remediation Reviewer role."""
    import core
    import store as store_mod
    import routes.system as s

    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "acp-test.db")
    st = store_mod.Store()
    monkeypatch.setattr(core, "OWNER_EMAIL", OWNER, raising=False)
    monkeypatch.setattr(core, "store", st, raising=False)
    monkeypatch.setattr(core, "get_store", lambda: st, raising=False)
    st.upsert_person({"email": OWNER, "role": "admin", "status": "access_ready"})
    st.upsert_person({"email": REVIEWER, "role": "user", "status": "access_ready"})
    st.upsert_person({"email": NOBODY, "role": "user", "status": "access_ready"})
    wr.seed_builtin_roles(st, tenant_id=OWNER)
    wr.assign_role(st, email=REVIEWER, role_id=rbac.REMEDIATION_REVIEWER, actor=OWNER)
    return s, core, st


@pytest.fixture
def enforcing(monkeypatch):
    monkeypatch.setenv(wr.FLAG, "1")


@pytest.fixture
def observing(monkeypatch):
    monkeypatch.delenv(wr.FLAG, raising=False)


# ── the payload PRD §13 specifies ─────────────────────────────────────────────

def test_it_returns_the_shape_the_prd_documents(env, enforcing):
    s, _core, _st = env
    out = s.my_access(request=_req(REVIEWER))
    assert set(out) >= {"role", "tabs", "capabilities", "version"}
    assert out["role"] == {"id": rbac.REMEDIATION_REVIEWER, "name": "Remediation Reviewer"}
    assert out["capabilities"] == sorted(out["capabilities"]), "capabilities must be stable-ordered"
    assert isinstance(out["version"], int)


def test_every_governed_tab_is_named_including_the_hidden_ones(env, enforcing):
    """The SPA has to tell "hidden by role" from "this build has no such tab". An omitted key
    answers neither, and the difference decides whether it renders a restricted screen or a 404."""
    s, _core, _st = env
    tabs = s.my_access(request=_req(REVIEWER))["tabs"]
    assert set(tabs) == set(rbac.TAB_KEYS)
    assert tabs["remediate"] == "operate"
    assert tabs["liveops"] == "hidden"
    assert tabs["settings"] == "hidden"


def test_the_capabilities_match_the_role_the_catalog_defines(env, enforcing):
    s, _core, _st = env
    out = s.my_access(request=_req(REVIEWER))
    assert set(out["capabilities"]) == rbac.builtin_capabilities(rbac.REMEDIATION_REVIEWER)


# ── 1. the owner carve-out, checked before anything can fail ──────────────────

def test_the_owner_has_everything_even_with_no_role_assigned(env, enforcing):
    """The anti-lockout guarantee (PRD §14). An owner who was never migrated must not be locked
    out by the migration not having been run — that is the one state nobody can rescue them from."""
    s, _core, st = env
    st.upsert_person({"email": OWNER, wr.ROLE_FIELD: None})
    out = s.my_access(request=_req(OWNER))
    assert out["owner"] is True
    assert set(out["capabilities"]) == rbac.CAPABILITIES
    assert set(out["tabs"].values()) == {"operate"}


def test_the_owner_survives_a_role_row_that_was_deleted_underneath_them(env, enforcing):
    """The carve-out is checked BEFORE the lookup, so a missing or corrupt row cannot reach it.
    Ordering this the other way round passes every happy-path test and fails exactly once, in the
    situation with no recovery path."""
    s, _core, st = env
    wr.assign_role(st, email=OWNER, role_id=rbac.OWNER, actor=OWNER)
    st.delete_workspace_role(tenant_id=OWNER, role_id=rbac.OWNER)
    out = s.my_access(request=_req(OWNER))
    assert set(out["capabilities"]) == rbac.CAPABILITIES


def test_owner_holds_capabilities_added_after_their_row_was_written(env, enforcing):
    """Read off the stored rows, Owner would only hold what the seed knew about — so a capability
    added by a later build would be one the anti-lockout role could not perform until somebody
    re-ran a migration. Asserted against the live catalog, which is what makes it survive."""
    s, _core, _st = env
    assert set(s.my_access(request=_req(OWNER))["capabilities"]) == rbac.CAPABILITIES


# ── 2. the flag off: nothing changes, and the diff is visible ─────────────────

def test_with_the_flag_off_everyone_keeps_exactly_what_they_have_today(env, observing):
    """The §15 rollout writes roles long before it enforces them. If this returned the ROLE's
    access while unenforced, turning on the migration would silently narrow the UI for everybody —
    the rollout's whole point is that step 1 changes nothing anyone can see."""
    s, _core, _st = env
    for who in (REVIEWER, NOBODY, ""):
        out = s.my_access(request=_req(who))
        assert out["enforced"] is False
        assert set(out["tabs"].values()) == {"operate"}, f"{who} lost access with RBAC off"
        assert set(out["capabilities"]) == rbac.CAPABILITIES


def test_unenforced_still_reports_what_the_role_would_give(env, observing):
    """PRD §15 step 1: "Calculate roles but preserve current access; log differences." The
    difference is only legible if both halves come back from one call — otherwise an operator has
    to reason about two code paths to answer "what changes when I flip this"."""
    s, _core, _st = env
    out = s.my_access(request=_req(REVIEWER))
    assert out["tabs"]["liveops"] == "operate", "effective access should be untouched"
    assert out["calculated"]["tabs"]["liveops"] == "hidden", "the role's real answer is missing"
    assert set(out["calculated"]["capabilities"]) == rbac.builtin_capabilities(
        rbac.REMEDIATION_REVIEWER)


def test_the_calculated_half_is_absent_once_enforcement_is_on(env, enforcing):
    """`calculated` exists to preview a change that has not happened. Once it has, the same field
    would be a second copy of the answer — and two copies is how a caller ends up reading the
    stale one."""
    s, _core, _st = env
    assert "calculated" not in s.my_access(request=_req(REVIEWER))


def test_an_unassigned_person_calculates_to_nothing_rather_than_to_everything(env, observing):
    """Their EFFECTIVE access is untouched (the flag is off), but the preview must show what they
    would get, and that is nothing — which is the signal an operator needs before flipping it."""
    s, _core, _st = env
    out = s.my_access(request=_req(NOBODY))
    assert set(out["tabs"].values()) == {"operate"}
    assert set(out["calculated"]["tabs"].values()) == {"hidden"}
    assert out["calculated"]["capabilities"] == []


# ── 4. the three ways access cannot be established ────────────────────────────

def test_an_unassigned_person_gets_nothing_once_enforcement_is_on(env, enforcing):
    s, _core, _st = env
    out = s.my_access(request=_req(NOBODY))
    assert out["enforced"] is True
    assert set(out["tabs"].values()) == {"hidden"}
    assert out["capabilities"] == []
    assert out["role"] is None


def test_a_suspended_person_gets_nothing_even_holding_a_real_role(env, enforcing):
    """PRD §14. Suspension is checked BEFORE the role because a suspended person usually still
    carries a perfectly valid one — reading the role first would hand them its access."""
    s, _core, st = env
    st.upsert_person({"email": REVIEWER, "status": "suspended"})
    out = s.my_access(request=_req(REVIEWER))
    assert out["capabilities"] == []
    assert set(out["tabs"].values()) == {"hidden"}
    assert out["role"] == {"id": rbac.REMEDIATION_REVIEWER, "name": "Remediation Reviewer"}, \
        "the role should still be reported — the refusal is about status, and hiding why is worse"


def test_a_role_id_naming_a_row_that_is_gone_refuses(env, enforcing):
    """The failure that looks most like success. A deleted or never-seeded role leaves an id that
    reads fine; resolving it to "no permissions" and carrying on would be a silent deny, and
    resolving it to a default would be a silent grant."""
    s, _core, st = env
    st.delete_workspace_role(tenant_id=OWNER, role_id=rbac.REMEDIATION_REVIEWER)
    out = s.my_access(request=_req(REVIEWER))
    assert out["capabilities"] == []
    assert set(out["tabs"].values()) == {"hidden"}


def test_an_anonymous_caller_gets_nothing_when_enforcing(env, enforcing):
    """The SPA calls this during sign-in bootstrapping, so it answers rather than 401ing. What it
    must not do is answer generously."""
    s, _core, _st = env
    for who in ("", None):
        out = s.my_access(request=_req(who))
        assert out["capabilities"] == []
        assert set(out["tabs"].values()) == {"hidden"}


def test_a_role_that_grants_nothing_is_not_the_same_as_a_role_that_is_missing(env, enforcing):
    """Both produce an empty capability list, and they are different facts: one is a Viewer whose
    every tab was hidden by an administrator, the other is a lookup that failed. The `role` field
    is what distinguishes them, and it is what an operator reads when a user reports seeing
    nothing."""
    s, _core, st = env
    st.upsert_workspace_role(tenant_id=OWNER, role_id="locked-down", name="Locked Down",
                             permissions={}, expected_version=None)
    wr.assign_role(st, email=NOBODY, role_id="locked-down", actor=OWNER)
    out = s.my_access(request=_req(NOBODY))
    assert out["capabilities"] == []
    assert out["role"] == {"id": "locked-down", "name": "Locked Down"}


# ── the version, which is how a live session notices a change (PRD §9) ────────

def test_the_version_moves_when_the_role_is_edited(env, enforcing):
    """§9: "Users whose permissions change during an active session receive the new permissions on
    their next API request." The SPA cannot notice that without something to compare."""
    s, _core, st = env
    before = s.my_access(request=_req(REVIEWER))["version"]
    role = st.get_workspace_role(tenant_id=OWNER, role_id=rbac.REMEDIATION_REVIEWER)
    st.upsert_workspace_role(tenant_id=OWNER, role_id=rbac.REMEDIATION_REVIEWER,
                             name="Remediation Reviewer", permissions={"remediate": "view"},
                             expected_version=role["version"])
    after = s.my_access(request=_req(REVIEWER))
    assert after["version"] > before
    assert after["tabs"]["remediate"] == "view", "the new access did not take effect"


# ── it rides the bootstrap the SPA already makes ──────────────────────────────

def test_the_workspace_bootstrap_carries_the_same_answer(env, enforcing, monkeypatch):
    """One round trip, and — the part that matters — computed by the SAME function. Two endpoints
    deriving access separately is how the navigation and the admin screen come to disagree about
    what a role means, with neither obviously wrong."""
    import routes.workspace as w
    s, core, _st = env
    monkeypatch.setattr(w, "_owner", lambda request: REVIEWER, raising=False)
    monkeypatch.setattr(w.core.store, "list_finished_scans", lambda owner=None: [], raising=False)
    boot = w.bootstrap(request=_req(REVIEWER))
    assert boot["me"]["access"] == s.my_access(request=_req(REVIEWER))
