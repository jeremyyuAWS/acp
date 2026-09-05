"""Workspace roles: the capability catalog, the built-in roles, and the rules that join them.

WHY THIS IS NOT core.is_admin(), AND NOT acr_authz EITHER
---------------------------------------------------------
Three authorization boundaries now exist in this codebase and they answer different questions.
Confusing them is the failure this module is shaped to prevent.

    core.is_admin()   "may this identity touch platform settings?"  Under the default
                      OPEN_ACCESS model (api/core.py, ACP_OPEN_ACCESS defaults ON) this is TRUE
                      FOR EVERY AUTHENTICATED USER. It is a deliberate product decision for the
                      rest of the platform and it is useless as a workspace-role gate: every role
                      below would collapse to Platform Admin.

    acr_authz         "may this identity approve or publish THIS ACR?"  Per-report, granted in the
                      `acr_role` table. Governs an external compliance artifact. Workspace roles
                      do NOT confer ACR roles and must never be read as if they did — PRD §3 and
                      §14 both say so, and tests/test_acr_authorization.py pins the ACR side.

    workspace_rbac    "which tabs may this identity see, and what may they do inside them?"

The one thing all three share is the owner carve-out: `core.is_owner` (the protected
ACP_OWNER_EMAIL) is the platform's anti-lockout root of trust. A fresh deploy whose only
administrator could be locked out of role administration has no recovery path, so Owner is
immutable here by construction (see OWNER and `is_protected_role`).

FAIL CLOSED, AND THE `None` / EMPTY DISTINCTION
-----------------------------------------------
`capabilities_for` returns a frozenset. An EMPTY frozenset means "this role was resolved and it
grants nothing" — a Viewer with every tab hidden. It never means "the role could not be loaded".
A caller that cannot load a role must not call this function with a default; it must refuse. The
two are different facts and this file never lets one stand in for the other (PRD §14: "Failure to
load permissions must fail closed for sensitive operations").

WHAT THIS MODULE DELIBERATELY DOES NOT DO
------------------------------------------
No database, no request, no HTTPException. It is a pure decision table so it can be tested
exhaustively — every tab at Hidden, View and Operate (PRD §16) — without a server. The store
holds the rows (api/store.py: workspace_roles, workspace_role_permissions) and the route gate
raises (slice 4). Keeping the decision here means the SPA's navigation and the API's refusal are
computed from ONE table and cannot drift into disagreeing about what a role means.
"""
from __future__ import annotations

# ── access levels (PRD §5) ────────────────────────────────────────────────────
# Ordered, because "at least View" is a question the gate asks constantly. The order is written
# out rather than implied by list position so a reordering cannot silently change what a role
# grants.
HIDDEN = "hidden"
VIEW = "view"
OPERATE = "operate"

ACCESS_LEVELS: tuple[str, ...] = (HIDDEN, VIEW, OPERATE)
_RANK: dict[str, int] = {HIDDEN: 0, VIEW: 1, OPERATE: 2}


def access_at_least(level: str, minimum: str) -> bool:
    """Does `level` reach `minimum`? Unknown levels are HIDDEN — an unrecognised access string is
    a corrupt row or a newer build's value, and both must deny rather than guess upward."""
    return _RANK.get(level, 0) >= _RANK.get(minimum, 0)


# ── the governed tabs (PRD §6) ────────────────────────────────────────────────
# KEYED BY THE FRONTEND'S OWN TAB KEYS, not by the PRD's display labels. frontend/src/App.jsx's
# TABS table is the existing vocabulary the navigation already filters on (`me.allow`), and a
# second spelling of the same tab is how a role that hides "Release" leaves "publish" reachable.
# The label is carried alongside so the admin UI (slice 3) names tabs the way the PRD does
# without re-deriving the mapping.
#
# `settings` is in this list and NOT in App.jsx's TABS: it is a view the SPA reaches from the
# header rather than the workflow strip. It is governed here because PRD §6 requires it.
TABS: tuple[tuple[str, str], ...] = (
    ("overview", "Overview"),
    ("integrations", "Sources"),
    ("discover", "Discover"),
    ("assess", "Assess"),
    ("remediate", "Remediate"),
    ("publish", "Release"),
    ("monitor", "Monitor"),
    ("liveops", "Live Operations"),
    ("analytics", "Scan Analytics"),
    ("settings", "Settings"),
)

TAB_KEYS: tuple[str, ...] = tuple(k for k, _ in TABS)
TAB_LABELS: dict[str, str] = dict(TABS)

# TWO TABS THE SPA RENDERS ARE NOT GOVERNED HERE, and that is a decision rather than an oversight:
#
#   `acr`   (Conformance / VPAT) — authorized by acr_authz per report, a different boundary that
#           PRD §3 explicitly says this feature must not replace or silently change.
#   `graph` (Knowledge Graph) — simply not in PRD §6's list. Left ungoverned rather than given an
#           invented default, because guessing an access level for a tab nobody specified is how a
#           surface ends up hidden from the people who need it, or shown to people who should not
#           see it, with no decision anywhere to point at.
#
# Both stay reachable exactly as they are today. Recorded here so the gap is visible at the point
# of use; UNGOVERNED_TABS is asserted in tests so this comment cannot quietly become false.
UNGOVERNED_TABS: frozenset[str] = frozenset({"acr", "graph"})


# ── the capability catalog (PRD §11) ──────────────────────────────────────────
# A capability is what a ROUTE asks for. Two kinds, and the split is the whole point of PRD §5:
#
#   TAB-DERIVED   implied by the role's access level on one tab. `discover.run` follows from
#                 Operate on Discover, because running discovery IS what that tab is for.
#
#   GRANT-ONLY    never implied by any tab. Publishing corrected files, managing people, reading
#                 every user's operations — these are granted by their own checkbox in the role
#                 drawer, so a role does not acquire a sensitive action merely because a tab it
#                 needs happens to contain the button. "This avoids granting sensitive actions
#                 merely because a tab is visible" (PRD §5).
#
# A grant-only capability is INDEPENDENT of tab access, which has a consequence worth naming: a
# role may hold `release.publish` with Release hidden. That is the literal reading of §5 and it is
# what the drawer's checkboxes imply — the tab radio and the permission checkbox are separate
# controls. It is also a footgun (an admin can grant publishing to a role that cannot see what it
# publishes), so the admin UI in slice 3 should warn on that combination rather than this module
# silently repairing it: repairing it here would mean a checkbox that sometimes does nothing.

TAB_CAPABILITIES: dict[str, tuple[str, str]] = {
    # capability          (tab key,        minimum access level)
    "overview.view":      ("overview",     VIEW),
    "sources.view":       ("integrations", VIEW),
    "discover.view":      ("discover",     VIEW),
    "discover.run":       ("discover",     OPERATE),
    "assess.view":        ("assess",       VIEW),
    "assess.run":         ("assess",       OPERATE),
    "assess.cancel":      ("assess",       OPERATE),
    "remediate.view":     ("remediate",    VIEW),
    "remediate.run":      ("remediate",    OPERATE),
    "remediate.review":   ("remediate",    OPERATE),
    "release.view":       ("publish",      VIEW),
    "monitor.view":       ("monitor",      VIEW),
    "operations.view":    ("liveops",      VIEW),
    "analytics.view":     ("analytics",    VIEW),
    "settings.view":      ("settings",     VIEW),
}

# The seven administrative permissions of PRD §5, as capabilities. `label` is what the role
# drawer shows; keeping it here means the UI cannot invent an eighth permission or rename one of
# these into something the server does not enforce.
GRANT_CAPABILITIES: dict[str, str] = {
    "people.manage":       "Manage people",
    "roles.manage":        "Manage roles",
    "sources.manage":      "Manage sources",
    "workers.manage":      "Manage worker configuration",
    "operations.view_all": "View all users’ operations",
    "reports.export":      "Export reports or inventory",
    "release.publish":     "Publish corrected files",
}

CAPABILITIES: frozenset[str] = frozenset(TAB_CAPABILITIES) | frozenset(GRANT_CAPABILITIES)


def capabilities_for(tab_access: dict[str, str],
                     grants: set[str] | frozenset[str] | list[str] | None = None) -> frozenset[str]:
    """Everything a role permits, from its per-tab access levels and its administrative grants.

    `tab_access` maps tab key → access level; a tab absent from it is HIDDEN. That default is the
    safe direction and it is also what makes adding a new governed tab non-breaking: existing
    stored roles do not mention it, so nobody gains access to it by upgrade.

    An empty result is a real answer ("this role grants nothing"), never a failure — see the
    module docstring. Callers that could not LOAD a role must refuse rather than pass {} here.
    """
    out = {cap for cap, (tab, minimum) in TAB_CAPABILITIES.items()
           if access_at_least(tab_access.get(tab, HIDDEN), minimum)}
    out |= {g for g in (grants or ()) if g in GRANT_CAPABILITIES}
    return frozenset(out)


def tab_access_from_rows(rows) -> dict[str, str]:
    """Normalize stored `workspace_role_permissions` rows into a tab→level map.

    Rows carrying an unknown tab or an unrecognised level are DROPPED rather than defaulted:
    a row this build does not understand was written by a different build, and inventing a level
    for it is precisely the guess `access_at_least` refuses to make one layer down.
    """
    out: dict[str, str] = {}
    for row in rows or ():
        tab = (row.get("capability") or "").strip()
        level = (row.get("access_level") or "").strip().lower()
        if tab in TAB_LABELS and level in _RANK:
            out[tab] = level
    return out


# ── built-in roles (PRD §4 and §7) ────────────────────────────────────────────
OWNER = "owner"
PLATFORM_ADMIN = "platform-admin"
PLATFORM_USER = "platform-user"
COMPLIANCE_MANAGER = "compliance-manager"
REMEDIATION_REVIEWER = "remediation-reviewer"
ANALYST = "analyst"
VIEWER = "viewer"

# Owner is immutable: it cannot be edited, deleted, or assigned by anyone except the current
# Owner (PRD §4), and it always holds every capability (PRD §14). Both facts are enforced at the
# route, but the flag lives with the role definition so the two cannot disagree about WHICH role
# is protected.
PROTECTED_ROLES: frozenset[str] = frozenset({OWNER})


def _all_tabs(level: str) -> dict[str, str]:
    return {k: level for k in TAB_KEYS}


# PRD §7 gives the tab grid. It does NOT give the administrative permissions per role, so those
# are derived from each role's stated purpose (§4) and marked here rather than presented as if the
# PRD specified them:
#
#   Compliance Manager "runs the complete accessibility workflow" and has Release at Operate, so
#     publishing and exporting are part of that job; Sources at Operate makes sources.manage
#     coherent. Settings is HIDDEN for this role in §7, so people/roles/workers management is not.
#   Remediation Reviewer takes exactly the drawer mock-up in §8: export ticked, publish and the
#     two manage boxes clear.
#   Analyst and Viewer get none. An Analyst "discovers and assesses content without changing
#     files"; export is a data-egress decision an administrator can add deliberately.
BUILTIN_ROLES: dict[str, dict] = {
    OWNER: {
        "name": "Owner",
        "description": "Full access, role administration, and anti-lockout authority.",
        "tabs": _all_tabs(OPERATE),
        "grants": frozenset(GRANT_CAPABILITIES),
        "is_protected": True,
    },
    PLATFORM_ADMIN: {
        "name": "Platform Admin",
        "description": "Full operational and administrative access.",
        "tabs": _all_tabs(OPERATE),
        "grants": frozenset(GRANT_CAPABILITIES),
        "is_protected": False,
    },
    # THE DEFAULT EVERY SIGNED-IN USER GETS. Owner decision, 2026-09-04: "All signed-in users
    # receive a default Platform User RBAC role... That role grants visibility and access to every
    # current tab... Administrators can later create restricted roles and reassign users."
    #
    # ITS TABS ARE WRITTEN OUT, NOT `_all_tabs(OPERATE)`, and that is the whole point of the same
    # decision's last clause: "New tabs should require an explicit capability decision rather than
    # silently inheriting access." Spelled as a comprehension, a governed tab added next year
    # would join this role the moment it was defined — nobody would decide anything, and the first
    # person to notice would be whoever it should have been hidden from.
    # test_a_new_tab_does_not_silently_join_the_default_role pins the list against TAB_KEYS: add a
    # tab and that test fails until somebody says, here, whether Platform User gets it.
    #
    # NOT the same role as Platform Admin, which also holds the seven administrative grants.
    # Platform User is "everything the workflow does", not "everything ACP does": Settings stays
    # visible (it is a current tab) but managing people, roles, workers and publishing remain
    # separate permissions, exactly as PRD §5 requires.
    PLATFORM_USER: {
        "name": "Platform User",
        "description": "The default for everyone who signs in — every workflow tab, no "
                       "administrative permissions.",
        "tabs": {"overview": OPERATE, "integrations": OPERATE, "discover": OPERATE,
                 "assess": OPERATE, "remediate": OPERATE, "publish": OPERATE,
                 "monitor": OPERATE, "liveops": OPERATE, "analytics": OPERATE,
                 "settings": OPERATE},
        "grants": frozenset(),
        "is_protected": False,
    },
    COMPLIANCE_MANAGER: {
        "name": "Compliance Manager",
        "description": "Runs the complete accessibility workflow.",
        "tabs": {"overview": OPERATE, "integrations": OPERATE, "discover": OPERATE,
                 "assess": OPERATE, "remediate": OPERATE, "publish": OPERATE,
                 "monitor": OPERATE, "liveops": VIEW, "analytics": OPERATE,
                 "settings": HIDDEN},
        "grants": frozenset({"reports.export", "release.publish", "sources.manage"}),
        "is_protected": False,
    },
    REMEDIATION_REVIEWER: {
        "name": "Remediation Reviewer",
        "description": "Reviews automated fixes and prepares approved files for release.",
        "tabs": {"overview": VIEW, "integrations": VIEW, "discover": VIEW, "assess": VIEW,
                 "remediate": OPERATE, "publish": VIEW, "monitor": VIEW,
                 "liveops": HIDDEN, "analytics": VIEW, "settings": HIDDEN},
        "grants": frozenset({"reports.export"}),
        "is_protected": False,
    },
    ANALYST: {
        "name": "Analyst",
        "description": "Discovers and assesses content without changing files.",
        "tabs": {"overview": VIEW, "integrations": VIEW, "discover": OPERATE, "assess": OPERATE,
                 "remediate": VIEW, "publish": HIDDEN, "monitor": VIEW,
                 "liveops": HIDDEN, "analytics": VIEW, "settings": HIDDEN},
        "grants": frozenset(),
        "is_protected": False,
    },
    VIEWER: {
        "name": "Viewer",
        "description": "Read-only dashboards, results, and monitoring.",
        "tabs": {"overview": VIEW, "integrations": HIDDEN, "discover": HIDDEN, "assess": VIEW,
                 "remediate": VIEW, "publish": VIEW, "monitor": VIEW,
                 "liveops": HIDDEN, "analytics": VIEW, "settings": HIDDEN},
        "grants": frozenset(),
        "is_protected": False,
    },
}


def is_protected_role(role_id: str) -> bool:
    """Owner only. Protected means: not editable, not deletable, and assignable by the current
    Owner alone (PRD §4, §14)."""
    return (role_id or "").strip().lower() in PROTECTED_ROLES


def builtin_capabilities(role_id: str) -> frozenset[str]:
    """What a built-in role grants. Owner short-circuits to EVERY capability rather than being
    computed from its grid — "Owner always has every capability" (PRD §14) must not depend on
    somebody remembering to add a new capability to Owner's row."""
    key = (role_id or "").strip().lower()
    if key == OWNER:
        return CAPABILITIES
    role = BUILTIN_ROLES.get(key)
    if role is None:
        return frozenset()
    return capabilities_for(role["tabs"], role["grants"])


def tabs_payload(tab_access: dict[str, str]) -> dict[str, str]:
    """The `tabs` object of GET /me/access (PRD §13) — every governed tab named explicitly,
    including the hidden ones.

    Naming the hidden tabs rather than omitting them is deliberate: the SPA has to distinguish
    "hidden by role" from "this build has no such tab", and an absent key answers neither. It is
    not a disclosure — the tab NAMES are in the shipped JavaScript already; what is protected is
    the data behind them, which the server refuses separately.
    """
    return {k: tab_access.get(k, HIDDEN) for k in TAB_KEYS}


class WorkspaceForbidden(PermissionError):
    """The caller lacks the workspace capability this action needs.

    Raised by the route gate (slice 4), never by this module — the decision table has no opinion
    about HTTP. Mirrors acr_authz.AcrForbidden so both boundaries refuse in the same shape.
    """
