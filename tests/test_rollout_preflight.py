"""The preflight report — "who breaks if I advance a rung?"

THE REPORT'S JOB IS TO BE READ, NOT TO BE PASSED. An operator reaches for it once, at the moment
they are about to change other people's access, and the useful output is never a verdict: it is
the names. So most of what is tested here is that specific facts survive into the payload, and
that the two severities stay meaningfully different.

WHY THE BLOCKER/WARNING SPLIT IS TESTED SO HARD. It is the only thing standing between this report
and the fate of every over-eager check: if narrowing somebody's role — which is the ENTIRE POINT
of the feature — showed up as a blocker, then every real rollout would be blocked, operators would
learn to ignore the blockers, and the one that mattered would be ignored with them. §15 forbids
UNEXPECTED removal of access, not deliberate removal.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

ACP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ACP / "api"))

import workspace_preflight as preflight   # noqa: E402
import workspace_rbac as rbac             # noqa: E402
import workspace_rollout as rollout       # noqa: E402
import workspace_roles as wr              # noqa: E402

OWNER = "owner@hosp.org"
ANALYST = "analyst@hosp.org"
NOBODY = "nobody@hosp.org"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv(rollout.MODE_VAR, raising=False)
    monkeypatch.delenv(rollout.LEGACY_VAR, raising=False)


@pytest.fixture
def st(monkeypatch):
    """A seeded workspace: an owner, one person with a real narrow role, one unassigned."""
    import store as store_mod
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "acp-test.db")
    store = store_mod.Store()
    for email in (OWNER, ANALYST, NOBODY):
        store.upsert_person({"email": email, "role": "user", "status": "access_ready"})
    wr.seed_builtin_roles(store, tenant_id=OWNER)
    wr.assign_role(store, email=ANALYST, role_id=rbac.ANALYST, actor=OWNER)
    return store


def report(store, **kw):
    return preflight.report(store, owner_email=OWNER, **kw)


def codes(out, severity=None):
    return [f["code"] for f in out["findings"]
            if severity is None or f["severity"] == severity]


def finding(out, code):
    return next(f for f in out["findings"] if f["code"] == code)


# ── what the report is for ────────────────────────────────────────────────────

def test_it_names_the_rung_being_advanced_to(st):
    out = report(st)
    assert out["rollout"]["mode"] == rollout.OFF
    assert out["target"] == rollout.OBSERVE
    assert out["at_top"] is False


def test_at_the_top_there_is_nothing_to_advance_to(st, monkeypatch):
    """`ready: false` at the top rung would read as a problem. It is the finished state, and the
    report has to say which of the two it is."""
    monkeypatch.setenv(rollout.MODE_VAR, rollout.ENFORCE)
    out = report(st)
    assert out["at_top"] is True
    assert out["target"] is None
    assert out["ready"] is False, "there is no next rung, so there is nothing to be ready for"


def test_a_narrowed_role_is_a_warning_and_names_what_is_lost(st):
    """AN ADMINISTRATOR CHOSE THIS. An Analyst has Live Operations hidden by design, so they lose
    operations.view relative to today's open access — that is the feature working, and blocking on
    it would block every rollout that ever narrows anybody, which is all of them."""
    out = report(st)
    assert "assigned_people_lose_access" in codes(out, "warning")
    assert "assigned_people_lose_access" not in codes(out, "blocker")
    people = finding(out, "assigned_people_lose_access")["people"]
    entry = next(p for p in people if p["email"] == ANALYST)
    assert entry["role"] == rbac.ANALYST
    assert "operations.view" in entry["loses"], "the report must say WHAT is lost, not just that"


def test_a_narrowed_default_role_is_a_blocker(st):
    """NOBODY CHOSE THIS. Every unassigned person resolves through Platform User, so a default
    that grants less than its own definition narrows people no administrator narrowed.

    THIS CHECK WAS WRITTEN THE WRONG WAY FIRST, and the test above is why it changed. The original
    blocked whenever an unassigned person would lose ANY capability — which is every workspace,
    always: Platform User deliberately grants the ten tabs and not the seven administrative grants
    that OPEN_ACCESS hands everybody today. A blocker that cannot be cleared is one operators
    learn to click past, taking the real ones with it. So the comparison is against the role's
    DEFINITION, not against today's open access.
    """
    assert "default_role_narrowed" not in codes(report(st)), "baseline: the seeded default is intact"

    st.upsert_workspace_role(tenant_id=OWNER, role_id=rbac.PLATFORM_USER, name="Platform User",
                             description="", permissions={"overview": rbac.VIEW},
                             is_system=True, is_protected=False, actor=OWNER)
    out = report(st)
    assert "default_role_narrowed" in codes(out, "blocker")
    assert out["ready"] is False
    found = finding(out, "default_role_narrowed")
    assert "remediate.run" in found["missing"], "it must name what the default no longer grants"
    assert NOBODY in found["affects"], "and who depends on it"


def test_the_expected_narrowing_of_unassigned_people_is_a_warning(st):
    """The seven administrative grants every signed-in user holds under OPEN_ACCESS today and will
    not hold as a Platform User. Real, intended by the owner's default-role decision, and still
    worth one line somebody reads before it happens."""
    out = report(st)
    assert "unassigned_people_lose_access" in codes(out, "warning")
    entry = next(p for p in finding(out, "unassigned_people_lose_access")["people"]
                 if p["email"] == NOBODY)
    assert "roles.manage" in entry["loses"]
    assert out["blockers"] == 0, "expected narrowing must not block the rollout"


def test_the_owner_is_never_reported_as_losing_access(st):
    """The carve-out means they cannot be locked out at all. Listing them would be a false alarm
    on the one person the design guarantees is safe, and a report that cries wolf about the owner
    is a report an operator stops reading."""
    st.delete_workspace_role(tenant_id=OWNER, role_id=rbac.OWNER)
    out = report(st)
    listed = [p["email"] for f in out["findings"] for p in f.get("people", [])]
    assert OWNER not in listed
    owner_row = next(p for p in out["people"]["people"] if p["email"] == OWNER)
    assert owner_row["loses"] == []


def test_an_unseeded_workspace_blocks(st):
    """Every unassigned person resolves through the default role. Without it they resolve to
    nothing, so advancing refuses the whole workspace at once — the failure this check exists to
    catch before it happens rather than after."""
    st.delete_workspace_role(tenant_id=OWNER, role_id=rbac.PLATFORM_USER)
    out = report(st)
    assert "roles_not_seeded" in codes(out, "blocker")
    assert rbac.PLATFORM_USER in finding(out, "roles_not_seeded")["missing"]
    assert out["ready"] is False


def test_an_unreadable_mode_blocks_and_says_what_is_actually_running(st, monkeypatch):
    """The dangerous typo. The workspace runs unenforced while its operator believes otherwise,
    and nothing else in the product looks different — so the report has to name both the value
    they set and the rung they actually got."""
    monkeypatch.setenv(rollout.MODE_VAR, "enfoce")
    out = report(st)
    assert "mode_unreadable" in codes(out, "blocker")
    detail = finding(out, "mode_unreadable")["detail"]
    assert "enfoce" in detail
    assert rollout.OFF in detail, "it must say which rung is really in effect"


def test_a_stale_legacy_variable_is_a_warning_not_a_blocker(st, monkeypatch):
    """Two variables saying different things is a configuration somebody should tidy, not a reason
    to stop. Blocking would make an incident rollback — set MODE=observe, leave the old flag —
    fail its own preflight."""
    monkeypatch.setenv(rollout.LEGACY_VAR, "1")
    monkeypatch.setenv(rollout.MODE_VAR, rollout.OBSERVE)
    out = report(st)
    assert "legacy_flag_shadowed" in codes(out, "warning")
    assert out["blockers"] == 0


def test_an_unmapped_route_blocks(st):
    """The gate lets an unmapped route through, so an unmapped route is open to every role. This
    is the runtime half of the owner's decision that a new tab must require an explicit capability
    decision rather than silently inheriting access — CI checks the code, this checks the image
    that is actually running."""
    fake = SimpleNamespace(path="/totally/new/thing", methods={"POST"})
    out = report(st, routes=[fake])
    assert "routes_unmapped" in codes(out, "blocker")
    assert "POST /totally/new/thing" in finding(out, "routes_unmapped")["routes"]


def test_routes_are_only_checked_when_they_are_supplied(st):
    """`routes=None` means "not asked", not "none exist". Treating an absent argument as an empty
    route table would report a clean bill of health for a check that never ran."""
    assert "routes_unmapped" not in codes(report(st))


# ── the observe evidence ──────────────────────────────────────────────────────

def test_advancing_to_enforcement_with_no_observations_warns(st, monkeypatch):
    """The specific mistake the observe rung exists to prevent, called out at the moment it would
    be made. The report cannot tell "observe found nothing" from "observe never ran", and says so
    rather than implying the reassuring one."""
    monkeypatch.setenv(rollout.MODE_VAR, rollout.NAVIGATION)
    out = report(st)
    assert out["target"] == rollout.ENFORCE
    assert "no_observations" in codes(out, "warning")


def test_recorded_would_denies_are_surfaced_before_enforcing(st, monkeypatch):
    """Each one is a real request by a real user that is about to start returning 403. They are
    the entire product of running observe mode, so they must reach the operator who is deciding."""
    monkeypatch.setenv(rollout.MODE_VAR, rollout.NAVIGATION)
    st.log_decision(ANALYST, "role.access_would_deny", detail="analyst would be refused GET /x")
    out = report(st)
    assert "observed_would_deny" in codes(out, "warning")
    assert "no_observations" not in codes(out)
    assert finding(out, "observed_would_deny")["count"] == 1
    assert out["observed"]["counts"]["role.access_would_deny"] == 1
    assert out["observed"]["samples"][0]["detail"].startswith("analyst")


def test_observations_are_not_demanded_before_the_lower_rungs(st):
    """Advancing off -> observe cannot require observations; that is what the rung is for. A check
    that fires at every step would be noise at three of the four."""
    out = report(st)
    assert out["target"] == rollout.OBSERVE
    assert "no_observations" not in codes(out)


def test_an_unreadable_decision_log_does_not_block_the_report(st, monkeypatch):
    """The access diff is what decides the rollout and does not depend on history. Failing the
    whole call because the log is busy would make a loaded database look like a blocked rollout."""
    def boom(*a, **k):
        raise RuntimeError("decision log unavailable")
    monkeypatch.setattr(st, "list_decisions", boom)
    out = report(st)
    assert out["observed"]["readable"] is False
    assert out["people"]["total"] == 3, "the part that matters still ran"


# ── the shape an operator reads ───────────────────────────────────────────────

def test_ready_is_false_whenever_any_blocker_exists(st):
    st.delete_workspace_role(tenant_id=OWNER, role_id=rbac.PLATFORM_USER)
    out = report(st)
    assert out["blockers"] >= 1
    assert out["ready"] is False


def test_a_clean_workspace_is_ready_and_still_reports_its_warnings(st):
    """`ready` must not mean "nothing to read". The Analyst's narrowing is still listed — an
    operator who advances without reading it is choosing to, rather than not being told."""
    out = report(st)
    assert out["ready"] is True
    assert out["blockers"] == 0
    assert out["warnings"] >= 1
    assert "assigned_people_lose_access" in codes(out)


def test_every_person_is_accounted_for_with_their_effective_role(st):
    """Including the one nobody assigned — reported as resolving to the default rather than
    omitted, because "not in the list" and "has no role" read identically and only one of them is
    a problem."""
    out = report(st)["people"]
    assert out["total"] == 3
    assert out["unassigned"] == 2, "the owner and NOBODY carry no explicit assignment"
    rows = {p["email"]: p for p in out["people"]}
    assert rows[NOBODY]["assigned_role"] is None
    assert rows[NOBODY]["effective_role"] == rbac.PLATFORM_USER
    assert rows[NOBODY]["defaulted"] is True
    assert rows[ANALYST]["effective_role"] == rbac.ANALYST


def test_a_suspended_person_is_counted(st):
    """PRD §14 gives them nothing, so they appear as losing everything — which is correct and
    would be alarming if the report did not also say they are suspended."""
    st.upsert_person({"email": NOBODY, "status": "suspended"})
    out = report(st, is_suspended=lambda e: e == NOBODY)
    assert out["people"]["suspended"] == 1
    row = next(p for p in out["people"]["people"] if p["email"] == NOBODY)
    assert row["keeps"] == 0
