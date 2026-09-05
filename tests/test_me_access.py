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
import workspace_rollout as rollout   # noqa: E402
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
    monkeypatch.delenv(rollout.MODE_VAR, raising=False)


@pytest.fixture
def observing(monkeypatch):
    """The rollout at `off`.

    BOTH variables are cleared, not just the legacy one. Slice 6 added a second way to select a
    rung, and a fixture that clears one of two switches is a fixture whose result depends on the
    environment the suite happens to run in — green locally, and something else on a machine that
    exports the other. The same reason `enforcing` clears MODE: it must mean enforce because it
    said so, not because nothing contradicted it.
    """
    monkeypatch.delenv(wr.FLAG, raising=False)
    monkeypatch.delenv(rollout.MODE_VAR, raising=False)


@pytest.fixture
def observe_rung(monkeypatch):
    """PRD §15 step 1 proper — roles resolved, nobody's access changed."""
    monkeypatch.delenv(wr.FLAG, raising=False)
    monkeypatch.setenv(rollout.MODE_VAR, rollout.OBSERVE)


@pytest.fixture
def navigation_rung(monkeypatch):
    monkeypatch.delenv(wr.FLAG, raising=False)
    monkeypatch.setenv(rollout.MODE_VAR, rollout.NAVIGATION)


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


def test_the_preview_for_an_unassigned_person_matches_what_enforcing_actually_does(env, observing):
    """Their EFFECTIVE access is untouched, and the preview shows what enforcement WOULD give.

    THIS TEST ASSERTED THE OPPOSITE UNTIL SLICE 6, and the two halves of this file disagreed
    without either failing. It required `calculated` to be nothing for an unassigned person,
    while test_an_unassigned_person_gets_the_default_role_once_enforcement_is_on — twelve lines
    below — required enforcement to hand that same person the full default Platform User role.
    Both passed, because the preview was computed by a SECOND code path that read only the
    assigned role and never learned about the default that slice 4 added.

    What that shipped was a rollout report saying every unassigned person was about to lose
    everything. The operator response to reading that is to halt the rollout, or to spend a day
    assigning roles nobody needed. A preview is only worth serving if it is the decision itself,
    which is now what it is: access_for_email calls _enforced_decision for both.
    """
    s, _core, _st = env
    out = s.my_access(request=_req(NOBODY))
    assert set(out["tabs"].values()) == {"operate"}, "today's access must be untouched"
    assert set(out["calculated"]["tabs"].values()) == {"operate"}
    assert out["calculated"]["role"]["id"] == rbac.PLATFORM_USER
    assert out["calculated"]["capabilities"], "the default role grants something"


def test_the_preview_is_the_same_object_the_enforcing_path_returns(env, monkeypatch):
    """The guarantee stated as a comparison rather than as two constants.

    Constants go stale independently — that is exactly how the contradiction above survived. This
    reads the preview at `observe` and the real answer at `enforce` for the same person and
    requires them equal, so a future change to either path fails here rather than in production.
    """
    s, _core, _st = env
    monkeypatch.delenv(wr.FLAG, raising=False)

    monkeypatch.setenv(rollout.MODE_VAR, rollout.OBSERVE)
    previewed = s.my_access(request=_req(NOBODY))["calculated"]

    monkeypatch.setenv(rollout.MODE_VAR, rollout.ENFORCE)
    actual = s.my_access(request=_req(NOBODY))

    assert previewed["tabs"] == actual["tabs"]
    assert previewed["capabilities"] == actual["capabilities"]
    assert previewed["role"]["id"] == actual["role"]["id"]


def test_a_narrowed_role_previews_the_loss_it_will_cause(env, observing):
    """The other direction: somebody an administrator DID narrow must preview as narrowed.

    Without this the test above is satisfiable by a preview that just echoes today's access —
    which would be a preview that can never report bad news, and bad news is the only reason to
    look at one.
    """
    s, _core, _st = env
    out = s.my_access(request=_req(REVIEWER))
    assert set(out["tabs"].values()) == {"operate"}, "today's access must be untouched"
    assert out["calculated"]["tabs"]["liveops"] == "hidden"
    assert out["calculated"]["role"]["id"] == rbac.REMEDIATION_REVIEWER


# ── 4. the three ways access cannot be established ────────────────────────────

def test_an_unassigned_person_gets_the_default_role_once_enforcement_is_on(env, enforcing):
    """CHANGED BY OWNER DECISION, 2026-09-04: "All signed-in users receive a default Platform
    User RBAC role." This test previously asserted the opposite — no role meant no access — on
    the fail-closed principle the rest of this file still follows.

    The reversal is narrow and deliberate: being signed in is already an authorization decision
    (core.email_allowed admitted them), so an unassigned user is not an unknown, they are a known
    user nobody has narrowed yet. The two cases below — suspended, and a role id that does not
    resolve — still get nothing, because in those a decision WAS recorded.
    """
    s, _core, _st = env
    out = s.my_access(request=_req(NOBODY))
    assert out["enforced"] is True
    assert out["role"]["id"] == rbac.PLATFORM_USER
    assert out["defaulted"] is True
    assert set(out["tabs"].values()) == {"operate"}


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
        assert out["capabilities"] == [], (
            "an anonymous caller was given the default role — 'all SIGNED-IN users' does not "
            "include a caller with no identity, and /me/access is exempt from the capability "
            "gate precisely so a signed-out browser can call it")
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
