"""The workspace-role decision table: every tab, at every level, against the PRD's own grid.

WHY THIS FILE IS EXHAUSTIVE RATHER THAN REPRESENTATIVE. PRD §16 asks for tests covering "every
tab at Hidden, View, and Operate levels", and the reason is specific to this shape of code: a
permission table is a lookup, so a bug in it is not a crash or a wrong answer in general — it is
ONE cell being wrong while every other cell is right. Testing three representative tabs proves
nothing about the fourth, and the fourth is where the wrong cell is.

So the parametrised tests below walk 10 tabs × 3 levels and assert the exact capability set at
each. A new governed tab with no capabilities, or a capability pointing at a tab that does not
exist, fails here rather than shipping as a surface nobody can reach or a check nobody can pass.

WHAT THIS FILE DOES NOT TEST. Nothing here touches a database, a request, or a route. That is the
whole reason api/workspace_rbac.py has no imports from either — enforcement (does the route
actually ask?) is a different claim, tested where the routes are, and a green decision table says
nothing about it. Recorded so this file is not mistaken for evidence that the tabs are enforced.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import workspace_rbac as rbac  # noqa: E402


# ── the premise ───────────────────────────────────────────────────────────────

def test_the_catalog_is_not_empty_and_the_two_kinds_do_not_overlap():
    """The premise every other test rests on. If TAB_CAPABILITIES were empty this file would pass
    by asserting nothing, and a capability that is BOTH tab-derived and grant-only would make
    'granted separately from tab access' (PRD §5) meaningless — it would come back either way."""
    assert rbac.TAB_CAPABILITIES, "the tab capability catalog is empty"
    assert rbac.GRANT_CAPABILITIES, "the administrative permission catalog is empty"
    overlap = set(rbac.TAB_CAPABILITIES) & set(rbac.GRANT_CAPABILITIES)
    assert overlap == set(), f"these are granted two different ways: {sorted(overlap)}"
    assert rbac.CAPABILITIES == set(rbac.TAB_CAPABILITIES) | set(rbac.GRANT_CAPABILITIES)


def test_every_tab_capability_names_a_governed_tab():
    """A capability pointing at a tab nobody can be granted is a check that can never pass —
    the route 403s for every role including Owner, and the role drawer has no control to fix it."""
    for cap, (tab, _level) in rbac.TAB_CAPABILITIES.items():
        assert tab in rbac.TAB_LABELS, f"{cap} is governed by unknown tab {tab!r}"


def test_every_governed_tab_has_at_least_a_view_capability():
    """The other direction. A tab with no capability is a surface the server cannot protect: the
    navigation would hide it and every route behind it would stay open, which is precisely the
    'hiding a tab is not a security control' failure the PRD opens with."""
    covered = {tab for tab, level in rbac.TAB_CAPABILITIES.values() if level == rbac.VIEW}
    missing = set(rbac.TAB_KEYS) - covered
    assert missing == set(), f"governed tabs with no view capability: {sorted(missing)}"


def test_the_governed_and_ungoverned_tabs_do_not_overlap():
    """`acr` and `graph` are deliberately outside this feature (see the module comment). If one
    were added to TABS as well, it would be governed AND documented as ungoverned, and the comment
    explaining the exemption would quietly be a lie."""
    assert set(rbac.TAB_KEYS) & rbac.UNGOVERNED_TABS == set()


# ── every tab, every level (PRD §16) ──────────────────────────────────────────

@pytest.mark.parametrize("tab", rbac.TAB_KEYS)
def test_a_hidden_tab_grants_nothing_at_all(tab):
    caps = rbac.capabilities_for({tab: rbac.HIDDEN})
    assert caps == frozenset(), f"{tab} hidden still granted {sorted(caps)}"


@pytest.mark.parametrize("tab", rbac.TAB_KEYS)
def test_view_grants_exactly_the_view_capabilities_of_that_tab(tab):
    """View means see, not do. Any Operate-level capability appearing here is a read-only user
    who can start work — the single most consequential cell to get wrong in the whole table."""
    caps = rbac.capabilities_for({tab: rbac.VIEW})
    expected = {c for c, (t, level) in rbac.TAB_CAPABILITIES.items()
                if t == tab and level == rbac.VIEW}
    assert caps == expected
    operate_only = {c for c, (t, level) in rbac.TAB_CAPABILITIES.items()
                    if t == tab and level == rbac.OPERATE}
    assert caps & operate_only == set(), f"View on {tab} granted an action: {sorted(caps & operate_only)}"


@pytest.mark.parametrize("tab", rbac.TAB_KEYS)
def test_operate_grants_every_capability_of_that_tab_and_no_others(tab):
    caps = rbac.capabilities_for({tab: rbac.OPERATE})
    expected = {c for c, (t, _l) in rbac.TAB_CAPABILITIES.items() if t == tab}
    assert caps == expected


@pytest.mark.parametrize("tab", rbac.TAB_KEYS)
def test_a_tab_never_grants_a_capability_belonging_to_another_tab(tab):
    """Operate on Remediate must not confer release.publish, discover.run, or anything else next
    to it in the dict. Cheap to assert, and the exact failure a copy-pasted catalog row causes."""
    caps = rbac.capabilities_for({tab: rbac.OPERATE})
    foreign = {c for c in caps if rbac.TAB_CAPABILITIES[c][0] != tab}
    assert foreign == set(), f"Operate on {tab} leaked {sorted(foreign)}"


def test_an_unmentioned_tab_is_hidden_not_granted():
    """The default direction, and what makes adding a governed tab non-breaking: every role stored
    before it existed says nothing about it, and must therefore not have it."""
    caps = rbac.capabilities_for({"remediate": rbac.OPERATE})
    assert "discover.view" not in caps
    assert rbac.tabs_payload({"remediate": rbac.OPERATE})["discover"] == rbac.HIDDEN


@pytest.mark.parametrize("bogus", ["", "admin", "Operate ", "read-write", None, "OPERATE"])
def test_an_unrecognised_access_level_denies_rather_than_guessing(bogus):
    """A level this build does not know was written by a different build. Reading it as 'probably
    fine' is how a downgrade grants more than the role that wrote it intended; the safe reading of
    an unknown value is the one that grants nothing.

    'OPERATE' is in this list on purpose: the stored value is lower-case, and a case-insensitive
    read here would mean the SAME string means different things in the store and the gate."""
    assert rbac.capabilities_for({"remediate": bogus}) == frozenset()
    assert rbac.access_at_least(bogus, rbac.VIEW) is False


# ── administrative permissions are never implied by a tab (PRD §5) ────────────

def test_no_amount_of_tab_access_confers_an_administrative_permission():
    """The point of §5. Every tab at Operate — the most access the grid can express — and still
    not one of the seven checkboxes."""
    caps = rbac.capabilities_for({k: rbac.OPERATE for k in rbac.TAB_KEYS})
    leaked = caps & set(rbac.GRANT_CAPABILITIES)
    assert leaked == set(), f"tab access alone conferred {sorted(leaked)}"


def test_publishing_is_a_grant_and_not_a_consequence_of_the_release_tab():
    """Named separately from the test above because it is the one an implementer is most likely to
    'fix': Release at Operate looks like it should let you publish. PRD §5 says it must not — the
    drawer has its own checkbox for it, and a checkbox that is already implied does nothing."""
    assert "release.publish" not in rbac.capabilities_for({"publish": rbac.OPERATE})
    assert "release.publish" in rbac.capabilities_for({}, {"release.publish"})


def test_an_unknown_grant_is_ignored_rather_than_honoured():
    """A stored grant this build does not recognise is not a capability; honouring it would let a
    row written by a newer build (or a corrupted one) name anything it liked."""
    assert rbac.capabilities_for({}, {"nonsense.manage", "reports.export"}) == {"reports.export"}


# ── the built-in roles, against PRD §4 and §7 ─────────────────────────────────

# PRD §7's table, transcribed. Written out rather than derived from BUILTIN_ROLES: a test that
# computes its expectation from the thing under test asserts only that the code equals itself.
PRD_SECTION_7 = {
    #                    Admin      Compliance  Reviewer   Analyst    Viewer
    "overview":         ("operate", "operate", "view",    "view",    "view"),
    "integrations":     ("operate", "operate", "view",    "view",    "hidden"),
    "discover":         ("operate", "operate", "view",    "operate", "hidden"),
    "assess":           ("operate", "operate", "view",    "operate", "view"),
    "remediate":        ("operate", "operate", "operate", "view",    "view"),
    "publish":          ("operate", "operate", "view",    "hidden",  "view"),
    "monitor":          ("operate", "operate", "view",    "view",    "view"),
    "liveops":          ("operate", "view",    "hidden",  "hidden",  "hidden"),
    "analytics":        ("operate", "operate", "view",    "view",    "view"),
    "settings":         ("operate", "hidden",  "hidden",  "hidden",  "hidden"),
}
_COLUMNS = (rbac.PLATFORM_ADMIN, rbac.COMPLIANCE_MANAGER, rbac.REMEDIATION_REVIEWER,
            rbac.ANALYST, rbac.VIEWER)


@pytest.mark.parametrize("tab", sorted(PRD_SECTION_7))
def test_the_builtin_roles_match_the_prds_default_grid(tab):
    for role_id, expected in zip(_COLUMNS, PRD_SECTION_7[tab]):
        actual = rbac.BUILTIN_ROLES[role_id]["tabs"][tab]
        assert actual == expected, f"{role_id} on {tab}: {actual!r}, PRD §7 says {expected!r}"


def test_the_grid_covers_every_governed_tab():
    """If a tab were added to TABS and not to §7's grid, the test above would silently stop
    checking it — it parametrises over the grid, not over the tabs."""
    assert set(PRD_SECTION_7) == set(rbac.TAB_KEYS)


def test_owner_holds_every_capability_including_ones_added_later():
    """PRD §14. Asserted against the whole catalog rather than Owner's own grid, because the
    failure this prevents is a NEW capability being added and Owner not being updated — at which
    point the anti-lockout role cannot perform the action it was invented to guarantee."""
    assert rbac.builtin_capabilities(rbac.OWNER) == rbac.CAPABILITIES


def test_owner_is_the_only_protected_role():
    assert rbac.PROTECTED_ROLES == {rbac.OWNER}
    assert rbac.is_protected_role("owner") and rbac.is_protected_role("OWNER ")
    for other in (rbac.PLATFORM_ADMIN, rbac.VIEWER, "some-custom-role", ""):
        assert not rbac.is_protected_role(other)


def test_a_viewer_cannot_do_anything_and_that_is_a_real_answer():
    """The empty-vs-None distinction, at the level that matters. A Viewer legitimately holds no
    action capability; that must be expressible without being mistaken for a failed lookup."""
    caps = rbac.builtin_capabilities(rbac.VIEWER)
    assert caps, "a Viewer should still be able to VIEW things"
    assert not any(c.endswith((".run", ".cancel", ".review", ".publish", ".manage")) for c in caps)


def test_an_unknown_role_grants_nothing():
    assert rbac.builtin_capabilities("not-a-role") == frozenset()
    assert rbac.builtin_capabilities("") == frozenset()
    assert rbac.builtin_capabilities(None) == frozenset()


# ── the shapes the store and the SPA exchange ─────────────────────────────────

def test_tabs_payload_names_every_tab_including_the_hidden_ones():
    """GET /me/access must let the SPA tell 'hidden by role' from 'this build has no such tab'.
    An omitted key answers neither."""
    payload = rbac.tabs_payload({"remediate": rbac.OPERATE, "assess": rbac.VIEW})
    assert set(payload) == set(rbac.TAB_KEYS)
    assert payload["remediate"] == rbac.OPERATE
    assert payload["assess"] == rbac.VIEW
    assert payload["settings"] == rbac.HIDDEN


def test_stored_rows_that_this_build_does_not_understand_are_dropped():
    """Not defaulted — dropped. A row naming a tab this build has never heard of cannot be given
    an access level without inventing one, and the invented one is either a lockout or a leak."""
    rows = [{"capability": "remediate", "access_level": "operate"},
            {"capability": "teleport", "access_level": "operate"},     # unknown tab
            {"capability": "assess", "access_level": "supervise"},     # unknown level
            {"capability": "reports.export", "access_level": "granted"}]  # a grant, not a tab
    assert rbac.tab_access_from_rows(rows) == {"remediate": "operate"}


def test_tab_access_from_rows_survives_the_empty_and_the_absurd():
    assert rbac.tab_access_from_rows([]) == {}
    assert rbac.tab_access_from_rows(None) == {}
    assert rbac.tab_access_from_rows([{}, {"capability": None, "access_level": None}]) == {}
