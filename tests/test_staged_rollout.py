"""The rollout ladder, and the one property that makes a staged rollout worth staging.

PRD §15's steps are not four names for "on". Each rung permits strictly more than the one below,
and the value of the middle two is that they let a workspace learn what enforcement would do
BEFORE it does it. So the tests here are mostly about the differences:

    off          the store is never touched; no row is written; nothing is refused
    observe      the decision is computed and RECORDED; nobody is refused; tabs unchanged
    navigation   tabs are governed; the server still allows the call
    enforce      the server refuses

THE FAILURE THIS FILE IS BUILT AROUND is the vacuous observe run: a rung that reports nothing
because it never asked the question. It is invisible — an operator reads "no would-denies" as
"nothing to worry about", advances, and discovers the wrong capability map from a support ticket.
`test_observe_actually_records...` and its control below exist to make that failure loud, and the
first draft of the gate HAD it: access_for_email returns today's access below `navigation`, so
reading `capabilities` off it meant the check could never fail. The gate reads `calculated`.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ACP / "api"))

import workspace_denials as denials   # noqa: E402
import workspace_rbac as rbac         # noqa: E402
import workspace_rollout as rollout   # noqa: E402
import workspace_roles as wr          # noqa: E402

OWNER = "owner@hosp.org"
ANALYST = "analyst@hosp.org"       # Analyst: liveops hidden, so operations.view is not theirs
UNASSIGNED = "nobody@hosp.org"

# One route an Analyst genuinely cannot reach at `enforce`. Chosen rather than assumed: Live
# Operations is hidden for that role in the catalog, so /admin/activity needs a capability the
# role does not hold. A route the role DOES hold would make every assertion below vacuous.
FORBIDDEN = "/admin/activity"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Neither switch set, and the coalescing window cleared.

    The window is process-global (see api/workspace_denials.py), so a test that does not clear it
    inherits whatever the previous test suppressed — and would then record nothing and pass for
    the wrong reason.
    """
    monkeypatch.delenv(rollout.MODE_VAR, raising=False)
    monkeypatch.delenv(rollout.LEGACY_VAR, raising=False)
    denials.reset()
    yield
    denials.reset()


@pytest.fixture
def client(monkeypatch):
    """The real app and the real access gate — same construction as test_capability_enforcement.

    OPEN_ACCESS is on because that is the configuration this feature exists to survive:
    core.is_admin() is True for every authenticated user under it, so anything that passed on
    `is_admin` would pass here too and prove nothing.
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

    for email in (OWNER, ANALYST, UNASSIGNED):
        st.upsert_person({"email": email, "role": "user", "status": "access_ready"})
    wr.seed_builtin_roles(st, tenant_id=OWNER)
    wr.assign_role(st, email=ANALYST, role_id=rbac.ANALYST, actor=OWNER)

    from fastapi.testclient import TestClient
    from app import app
    return TestClient(app), core, st


def get(tc, path, who):
    return tc.get(path, headers={"Authorization": f"Bearer {who}"})


def role_rows(st, action):
    return [d for d in st.list_decisions(limit=500) if d["action"] == action]


# ── the ladder itself ─────────────────────────────────────────────────────────

def test_the_rungs_are_ordered_and_each_permits_more_than_the_one_below(monkeypatch):
    """The ordering is the contract every at_least() call depends on. Asserted directly because a
    reordering would silently invert individual permission checks rather than failing anywhere
    obvious."""
    assert rollout.LADDER == (rollout.OFF, rollout.OBSERVE, rollout.NAVIGATION, rollout.ENFORCE)
    seen = []
    for rung in rollout.LADDER:
        monkeypatch.setenv(rollout.MODE_VAR, rung)
        seen.append((rollout.roles_resolved(), rollout.navigation_active(),
                     rollout.enforcement_active()))
    assert seen == [(False, False, False), (True, False, False),
                    (True, True, False), (True, True, True)]
    # Monotonic in every column: no rung takes back what a lower one permitted.
    for column in range(3):
        values = [row[column] for row in seen]
        assert values == sorted(values), f"column {column} is not monotonic: {values}"


def test_the_legacy_variable_still_means_enforce(monkeypatch):
    """THE DEPLOYED CONTRACT. Slices 1–5 shipped ACP_WORKSPACE_RBAC_ENABLED and an operator may
    already have it set. A release that quietly stopped honouring it would turn enforcement OFF in
    a workspace that believed it was enforcing — a security control removed by renaming its
    switch, with nothing anywhere reporting the change."""
    monkeypatch.setenv(rollout.LEGACY_VAR, "1")
    assert rollout.mode() == rollout.ENFORCE
    assert rollout.enforcement_active() is True


def test_an_explicit_mode_overrides_the_legacy_variable(monkeypatch):
    """Rolling BACK from enforcement is the case that matters here: an operator in an incident
    sets MODE=observe, and it must take effect even though the old variable is still in the
    environment. Requiring them to find and unset a second variable mid-incident is how a rollback
    fails to roll back."""
    monkeypatch.setenv(rollout.LEGACY_VAR, "1")
    monkeypatch.setenv(rollout.MODE_VAR, rollout.OBSERVE)
    assert rollout.mode() == rollout.OBSERVE
    assert rollout.enforcement_active() is False


def test_an_unreadable_mode_falls_back_to_the_readable_variable_and_is_reported(monkeypatch):
    """A typo must not silently DISABLE a control that another variable still asks for.

    Both halves are the test. Falling through to the legacy flag keeps enforcement on for the
    deployment that had it; keeping the bad string in invalid_mode() is what lets the preflight
    report say so, because the state this produces — running unenforced while an operator believes
    otherwise — looks exactly like a workspace nobody has got to yet.
    """
    monkeypatch.setenv(rollout.MODE_VAR, "enfoce")
    monkeypatch.setenv(rollout.LEGACY_VAR, "1")
    assert rollout.mode() == rollout.ENFORCE
    assert rollout.invalid_mode() == "enfoce"

    monkeypatch.delenv(rollout.LEGACY_VAR)
    assert rollout.mode() == rollout.OFF, "with nothing readable left, do not guess"
    assert rollout.invalid_mode() == "enfoce", "and still say the value was unreadable"


def test_an_unknown_minimum_does_not_grant(monkeypatch):
    """at_least('opreate') is a caller's typo. Answering True would grant on a misspelling — the
    one direction a permission helper must never fail in."""
    monkeypatch.setenv(rollout.MODE_VAR, rollout.ENFORCE)
    assert rollout.at_least("opreate") is False


def test_next_stage_walks_up_and_stops(monkeypatch):
    assert rollout.next_stage(rollout.OFF) == rollout.OBSERVE
    assert rollout.next_stage(rollout.NAVIGATION) == rollout.ENFORCE
    assert rollout.next_stage(rollout.ENFORCE) is None


# ── off: the store is never read ──────────────────────────────────────────────

def test_off_does_not_touch_the_store_at_all(client, monkeypatch):
    """The default path must stay free. The gate resolves a role per request from `observe` up,
    which is a settings read plus a role read — acceptable when something reads the answer, and
    pure waste on a deployment that has not opted in at all."""
    tc, _core, st = client
    calls = []
    original = st.get_people
    monkeypatch.setattr(st, "get_people", lambda: calls.append(1) or original())
    assert get(tc, FORBIDDEN, ANALYST).status_code != 403
    assert calls == [], "the gate read the person record with the rollout off"


# ── observe: computed, recorded, and NOT applied ──────────────────────────────

def test_observe_allows_the_request_that_enforce_would_refuse(client, monkeypatch):
    """§15 step 1: "Calculate roles but preserve current access." The same request, two rungs."""
    tc, _core, _st = client
    monkeypatch.setenv(rollout.MODE_VAR, rollout.OBSERVE)
    assert get(tc, FORBIDDEN, ANALYST).status_code != 403

    denials.reset()
    monkeypatch.setenv(rollout.MODE_VAR, rollout.ENFORCE)
    assert get(tc, FORBIDDEN, ANALYST).status_code == 403


def test_observe_actually_records_the_difference_it_was_run_to_find(client, monkeypatch):
    """THE POINT OF THE WHOLE RUNG, and the assertion that stops it being decorative.

    The first version of this gate read `access["capabilities"]`, which below `navigation` is
    TODAY's access — everything, under OPEN_ACCESS. The capability check therefore always passed,
    no row was ever written, and an operator running observe mode for a week would have read a
    clean report produced by a monitor that never asked the question. This asserts the row exists;
    the control below asserts it is not written for someone who holds the capability, which is
    what stops the pair being satisfied by a gate that records everything.
    """
    tc, _core, st = client
    monkeypatch.setenv(rollout.MODE_VAR, rollout.OBSERVE)
    get(tc, FORBIDDEN, ANALYST)

    rows = role_rows(st, "role.access_would_deny")
    assert len(rows) == 1, f"observe mode recorded {len(rows)} differences, expected 1"
    detail = rows[0]["detail"]
    assert ANALYST in detail
    assert "would be refused" in detail, f"an allowed request must not read as refused: {detail}"
    assert FORBIDDEN in detail
    assert "operations.view" in detail
    assert role_rows(st, "role.access_denied") == [], "nothing was actually refused"


def test_observe_records_nothing_for_a_request_the_role_permits(client, monkeypatch):
    """The control. Without it the test above passes against a gate that logs every request,
    which would bury the audit log and tell an operator that every user is about to break."""
    tc, _core, st = client
    monkeypatch.setenv(rollout.MODE_VAR, rollout.OBSERVE)
    # An Analyst holds discover/assess at operate, so this is squarely inside the role.
    get(tc, "/scans", ANALYST)
    assert role_rows(st, "role.access_would_deny") == []


def test_observe_leaves_the_owner_alone(client, monkeypatch):
    """The carve-out returns before any lookup, so the owner cannot even be MEASURED into a
    denial. A report that lists the owner as about to lose access is a false alarm on the one
    person who cannot be locked out — and false alarms are how a report stops being read."""
    tc, _core, st = client
    monkeypatch.setenv(rollout.MODE_VAR, rollout.OBSERVE)
    get(tc, FORBIDDEN, OWNER)
    assert role_rows(st, "role.access_would_deny") == []


def test_observe_does_not_change_what_the_navigation_is_told(client, monkeypatch):
    """If observe mode narrowed the tabs, it would not be observation — it would be step 2 with a
    different name, and the rung that is supposed to change nothing would change the UI."""
    tc, _core, _st = client
    monkeypatch.setenv(rollout.MODE_VAR, rollout.OBSERVE)
    body = get(tc, "/me/access", ANALYST).json()
    assert body["enforced"] is False
    assert set(body["tabs"].values()) == {"operate"}, "observe must not hide a tab"
    assert body["calculated"]["tabs"]["liveops"] == "hidden", "but it must say what would happen"
    assert body["mode"] == rollout.OBSERVE


# ── navigation: tabs govern, the server still allows ──────────────────────────

def test_navigation_hides_tabs_but_does_not_refuse(client, monkeypatch):
    """The distinction PRD §11 turns on: hiding a tab is not a security control. At this rung the
    tab is gone from the SPA and the API still answers — which is precisely why the rung after it
    exists, and why nobody should stop here."""
    tc, _core, _st = client
    monkeypatch.setenv(rollout.MODE_VAR, rollout.NAVIGATION)
    body = get(tc, "/me/access", ANALYST).json()
    assert body["enforced"] is True, "the SPA must apply the tabs at this rung"
    assert body["tabs"]["liveops"] == "hidden"
    assert "calculated" not in body, "the decision IS the access here; there is nothing to preview"
    assert get(tc, FORBIDDEN, ANALYST).status_code != 403


def test_navigation_still_records_what_gets_through(client, monkeypatch):
    """What reaches the gate once the tab is hidden is exactly what the hiding did NOT cover — a
    direct URL, a stale open tab, a poll from a page loaded before the role changed. That list is
    the last thing an operator wants before making the server refuse, so this rung keeps
    recording."""
    tc, _core, st = client
    monkeypatch.setenv(rollout.MODE_VAR, rollout.NAVIGATION)
    get(tc, FORBIDDEN, ANALYST)
    assert len(role_rows(st, "role.access_would_deny")) == 1


# ── enforce: unchanged from slice 4 ───────────────────────────────────────────

def test_enforce_refuses_and_records_it_as_a_real_refusal(client, monkeypatch):
    """The two actions must stay distinguishable. An operator counting refusals has to know which
    rows were real without reading prose, because the count of each is what the decision to
    advance or roll back turns on."""
    tc, _core, st = client
    monkeypatch.setenv(rollout.MODE_VAR, rollout.ENFORCE)
    assert get(tc, FORBIDDEN, ANALYST).status_code == 403

    denied = role_rows(st, "role.access_denied")
    assert len(denied) == 1
    assert "was refused" in denied[0]["detail"]
    assert role_rows(st, "role.access_would_deny") == []


def test_advancing_the_rung_does_not_swallow_the_first_real_refusal(client, monkeypatch):
    """THE COALESCING BUG THIS SEPARATION EXISTS TO PREVENT.

    The window suppresses repeats of one (person, requirement) for two minutes. Sharing it across
    both actions would mean an observation warmed the counter, and the FIRST genuine 403 after an
    operator advances to enforcement — the single most important row in the entire rollout, the
    one that says the thing they were afraid of is now happening — is silently dropped as a
    repeat. The kinds are keyed separately so it cannot be.
    """
    tc, _core, st = client
    monkeypatch.setenv(rollout.MODE_VAR, rollout.OBSERVE)
    get(tc, FORBIDDEN, ANALYST)
    assert len(role_rows(st, "role.access_would_deny")) == 1

    monkeypatch.setenv(rollout.MODE_VAR, rollout.ENFORCE)
    assert get(tc, FORBIDDEN, ANALYST).status_code == 403
    assert len(role_rows(st, "role.access_denied")) == 1, (
        "the first real refusal after advancing was suppressed by the observation before it")


def test_the_rollout_state_is_reported_where_an_operator_will_see_it(client, monkeypatch):
    """`describe()` on the roles list, not just in an environment variable nobody can read from
    the product. An administrator designing roles has to be able to tell whether what they are
    building is live."""
    tc, _core, _st = client
    monkeypatch.setenv(rollout.MODE_VAR, rollout.NAVIGATION)
    body = get(tc, "/admin/roles", OWNER).json()
    assert body["rollout"]["mode"] == rollout.NAVIGATION
    assert body["rollout"]["next"] == rollout.ENFORCE
    assert body["rollout"]["enforcing"] is False
    assert body["enforced"] is False
    assert body["rollout"]["means"], "the rung must explain itself, not just name itself"


# ── the preflight report, through the app ─────────────────────────────────────

def test_the_preflight_report_is_owner_only(client, monkeypatch):
    """It lists every managed person's email next to the capabilities they are about to lose, and
    it is read at the moment somebody is deciding whether to narrow other people's access. That is
    a personnel-shaped answer; `roles.manage` is the wrong gate because a role holding it could
    use this to enumerate the whole workspace's standing."""
    tc, _core, _st = client
    monkeypatch.setenv(rollout.MODE_VAR, rollout.OBSERVE)
    assert get(tc, "/admin/workspace-roles/preflight", ANALYST).status_code == 403
    assert get(tc, "/admin/workspace-roles/preflight", OWNER).status_code == 200


def test_the_preflight_report_reads_the_real_route_table(client, monkeypatch):
    """Served with the routes the RUNNING app registered, not a fixture. The completeness test in
    CI checks the code; this checks the image, which is where a route added without a capability
    decision would actually be live."""
    tc, _core, _st = client
    monkeypatch.setenv(rollout.MODE_VAR, rollout.OBSERVE)
    out = get(tc, "/admin/workspace-roles/preflight", OWNER).json()
    assert out["target"] == rollout.NAVIGATION
    assert "routes_unmapped" not in [f["code"] for f in out["findings"]], (
        "the shipped app has a route with no capability decision")
    assert out["people"]["total"] >= 3


def test_the_preflight_report_surfaces_what_observe_recorded(client, monkeypatch):
    """End to end: a real refused-in-observe request, then the report an operator reads before
    advancing. The two halves are written by different modules and this is the only place they
    are required to line up."""
    tc, _core, _st = client
    monkeypatch.setenv(rollout.MODE_VAR, rollout.NAVIGATION)
    get(tc, FORBIDDEN, ANALYST)

    out = get(tc, "/admin/workspace-roles/preflight", OWNER).json()
    assert out["target"] == rollout.ENFORCE
    assert out["observed"]["counts"]["role.access_would_deny"] == 1
    assert "observed_would_deny" in [f["code"] for f in out["findings"]]
    assert any(ANALYST in (s["detail"] or "") for s in out["observed"]["samples"])
