"""Workspace roles in the database: seeding, assignment, concurrency, and the §15 migration.

THE CLAIM THIS FILE DEFENDS is that turning workspace RBAC on cannot take away access somebody
has today, and cannot silently overwrite an administrator's decisions. Both are migration
properties rather than permission-table properties, so neither is visible in
test_workspace_rbac_catalog.py: that file proves the grid means what the PRD says, this one
proves an existing deployment survives acquiring one.

The store is a real SQLite Store (the `isolated_store` fixture), not a fake. A fake would let the
schema and the accessors drift apart — and the two tables added for this feature are exactly the
kind of thing a fake makes look fine while the DDL is wrong.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import workspace_rbac as rbac        # noqa: E402
import workspace_roles as wr         # noqa: E402

TENANT = "owner@acp.test"
OTHER_TENANT = "other@acp.test"


# ── the tables exist and round-trip ───────────────────────────────────────────

def test_a_role_survives_a_round_trip_with_its_permissions(isolated_store):
    st = isolated_store
    st.upsert_workspace_role(tenant_id=TENANT, role_id="r1", name="Reviewer",
                             description="Reviews fixes.",
                             permissions={"remediate": "operate", "assess": "view",
                                          "reports.export": "granted"},
                             actor="owner@acp.test")
    role = st.get_workspace_role(tenant_id=TENANT, role_id="r1")
    assert role["name"] == "Reviewer"
    assert role["version"] == 1
    got = {p["capability"]: p["access_level"] for p in role["permissions"]}
    assert got == {"remediate": "operate", "assess": "view", "reports.export": "granted"}


def test_a_missing_role_is_None_and_a_role_with_no_permissions_is_not(isolated_store):
    """The distinction the whole design rests on. `None` = no such role, so the gate must refuse.
    A role with an empty permission list = a real role that grants nothing, which is a legitimate
    Viewer. Collapsing them turns a lookup failure into a silent, plausible-looking deny."""
    st = isolated_store
    assert st.get_workspace_role(tenant_id=TENANT, role_id="ghost") is None
    st.upsert_workspace_role(tenant_id=TENANT, role_id="empty", name="Nothing", permissions={})
    role = st.get_workspace_role(tenant_id=TENANT, role_id="empty")
    assert role is not None and role["permissions"] == []


def test_editing_a_role_replaces_its_permissions_rather_than_merging(isolated_store):
    """Revoking access is the operation a merge cannot express. If the old rows survived, an
    administrator could add a tab and never remove one."""
    st = isolated_store
    st.upsert_workspace_role(tenant_id=TENANT, role_id="r1", name="R",
                             permissions={"remediate": "operate", "liveops": "operate"})
    st.upsert_workspace_role(tenant_id=TENANT, role_id="r1", name="R",
                             permissions={"remediate": "view"}, expected_version=1)
    role = st.get_workspace_role(tenant_id=TENANT, role_id="r1")
    assert {p["capability"]: p["access_level"] for p in role["permissions"]} == {"remediate": "view"}
    assert role["version"] == 2


def test_roles_are_isolated_between_tenants(isolated_store):
    """Asserted by holding two tenants at once rather than by reading the WHERE clause."""
    st = isolated_store
    st.upsert_workspace_role(tenant_id=TENANT, role_id="r1", name="Mine",
                             permissions={"remediate": "operate"})
    assert st.get_workspace_role(tenant_id=OTHER_TENANT, role_id="r1") is None
    assert st.list_workspace_roles(tenant_id=OTHER_TENANT) == []
    assert [r["id"] for r in st.list_workspace_roles(tenant_id=TENANT)] == ["r1"]


def test_listing_includes_a_role_that_has_no_permissions(isolated_store):
    """A join would drop it, and the role it drops is the Viewer. Pinned because 'list the roles'
    is the query most likely to be rewritten as a join by someone tidying up."""
    st = isolated_store
    st.upsert_workspace_role(tenant_id=TENANT, role_id="empty", name="Nothing", permissions={})
    st.upsert_workspace_role(tenant_id=TENANT, role_id="full", name="Everything",
                             permissions={"remediate": "operate"})
    listed = {r["id"]: r for r in st.list_workspace_roles(tenant_id=TENANT)}
    assert set(listed) == {"empty", "full"}
    assert listed["empty"]["permissions"] == []


# ── optimistic concurrency (PRD §14) ──────────────────────────────────────────

def test_a_stale_version_is_refused_and_nothing_is_written(isolated_store):
    """Two administrators, two browser tabs. The second save must not silently win — and the
    refusal must leave the role exactly as the first save left it, or 'refused' would still have
    cost the first administrator their change."""
    st = isolated_store
    st.upsert_workspace_role(tenant_id=TENANT, role_id="r1", name="R",
                             permissions={"remediate": "operate"})
    st.upsert_workspace_role(tenant_id=TENANT, role_id="r1", name="R",
                             permissions={"remediate": "view"}, expected_version=1)

    with pytest.raises(ValueError) as exc:
        st.upsert_workspace_role(tenant_id=TENANT, role_id="r1", name="Clobbered",
                                 permissions={"liveops": "operate"}, expected_version=1)
    assert "changed by someone else" in str(exc.value)

    role = st.get_workspace_role(tenant_id=TENANT, role_id="r1")
    assert role["name"] == "R", "the refused write still changed the role"
    assert role["version"] == 2
    assert {p["capability"] for p in role["permissions"]} == {"remediate"}


def test_creating_does_not_require_a_version(isolated_store):
    """There is nothing to be stale about. Requiring one would mean inventing a version for a
    role that does not exist, and the obvious invention (0) is indistinguishable from a bug."""
    st = isolated_store
    role = st.upsert_workspace_role(tenant_id=TENANT, role_id="new", name="New",
                                    permissions={}, expected_version=None)
    assert role["version"] == 1


# ── seeding the built-in roles ────────────────────────────────────────────────

def test_seeding_creates_every_builtin_role_with_the_capabilities_the_catalog_says(isolated_store):
    st = isolated_store
    created = wr.seed_builtin_roles(st, tenant_id=TENANT, actor="owner@acp.test")
    assert set(created) == set(rbac.BUILTIN_ROLES)

    for role_id in rbac.BUILTIN_ROLES:
        stored = st.get_workspace_role(tenant_id=TENANT, role_id=role_id)
        tab_access = rbac.tab_access_from_rows(stored["permissions"])
        grants = {p["capability"] for p in stored["permissions"]
                  if p["access_level"] == "granted"}
        assert rbac.capabilities_for(tab_access, grants) == rbac.builtin_capabilities(role_id), \
            f"{role_id} does not mean in the database what it means in the catalog"


def test_seeding_twice_creates_nothing_the_second_time(isolated_store):
    st = isolated_store
    wr.seed_builtin_roles(st, tenant_id=TENANT)
    assert wr.seed_builtin_roles(st, tenant_id=TENANT) == []


def test_seeding_never_overwrites_an_edited_builtin(isolated_store):
    """Re-seeding on every boot is the point of idempotence, and this is what makes it safe:
    an administrator who narrowed Compliance Manager must not find it widened again by a restart.
    A seed that overwrote would look like a no-op in the diff and be data loss in production."""
    st = isolated_store
    wr.seed_builtin_roles(st, tenant_id=TENANT)
    st.upsert_workspace_role(tenant_id=TENANT, role_id=rbac.COMPLIANCE_MANAGER,
                             name="Compliance Manager", permissions={"overview": "view"},
                             is_system=True, expected_version=1)
    wr.seed_builtin_roles(st, tenant_id=TENANT)
    role = st.get_workspace_role(tenant_id=TENANT, role_id=rbac.COMPLIANCE_MANAGER)
    assert {p["capability"]: p["access_level"] for p in role["permissions"]} == {"overview": "view"}


def test_owner_is_seeded_protected(isolated_store):
    """The anti-lockout role must exist from the first boot, already marked — not created by
    whoever opens the admin screen first, and not editable when they do."""
    st = isolated_store
    wr.seed_builtin_roles(st, tenant_id=TENANT)
    owner = st.get_workspace_role(tenant_id=TENANT, role_id=rbac.OWNER)
    assert owner["is_protected"] in (1, True)
    assert owner["is_system"] in (1, True)


# ── assignment ────────────────────────────────────────────────────────────────

def test_assigning_a_role_records_who_did_it_and_when(isolated_store):
    st = isolated_store
    st.upsert_person({"email": "jane@acp.test", "provider": "microsoft", "role": "user"})
    wr.assign_role(st, email="jane@acp.test", role_id=rbac.REMEDIATION_REVIEWER,
                   actor="owner@acp.test")
    person = next(p for p in st.get_people() if p["email"] == "jane@acp.test")
    assert person[wr.ROLE_FIELD] == rbac.REMEDIATION_REVIEWER
    assert person[wr.ASSIGNED_BY_FIELD] == "owner@acp.test"
    assert person[wr.ASSIGNED_AT_FIELD]
    assert person["provider"] == "microsoft", "assignment discarded the rest of the record"


def test_the_assignment_appears_in_the_audit_trail_with_both_values(isolated_store):
    """PRD §12 wants previous value and new value. 'jane's role changed' is not an audit trail —
    the question an auditor asks is what it changed FROM."""
    st = isolated_store
    st.upsert_person({"email": "jane@acp.test", "role": "user"})
    wr.assign_role(st, email="jane@acp.test", role_id=rbac.ANALYST, actor="owner@acp.test")
    wr.assign_role(st, email="jane@acp.test", role_id=rbac.VIEWER, actor="owner@acp.test")
    rows = [d for d in st.list_decisions() if d["action"] == "role.assigned"]
    assert len(rows) == 2
    assert rows[0]["actor"] == "owner@acp.test"
    details = " ".join(r["detail"] for r in rows)
    assert "none → analyst" in details, details
    assert "analyst → viewer" in details, details


def test_an_unassigned_person_reads_as_None_not_as_a_default_role(isolated_store):
    """`None` is what makes the gate able to fail closed. If this returned 'viewer', a person the
    migration had not reached would silently acquire a role nobody granted them."""
    st = isolated_store
    st.upsert_person({"email": "nobody@acp.test", "role": "user"})
    assert wr.role_id_for_email(st, "nobody@acp.test") is None
    assert wr.role_id_for_email(st, "stranger@acp.test") is None
    assert wr.role_id_for_email(st, "") is None


# ── the §15 migration ─────────────────────────────────────────────────────────

def _seed_people(st):
    st.upsert_person({"email": TENANT, "role": "admin"})
    st.upsert_person({"email": "admin2@acp.test", "role": "admin"})
    st.upsert_person({"email": "user1@acp.test", "role": "user"})
    st.upsert_person({"email": "user2@acp.test", "role": "user"})


def test_the_migration_maps_people_the_way_section_15_says(isolated_store):
    st = isolated_store
    _seed_people(st)
    wr.seed_builtin_roles(st, tenant_id=TENANT)
    plan = {row["email"]: row["to"] for row in
            wr.migrate_people(st, tenant_id=TENANT, owner_email=TENANT)}
    # PLATFORM USER, not Compliance Manager, since the owner's 2026-09-04 decision: "All
    # signed-in users receive a default Platform User RBAC role... Existing users should be
    # backfilled automatically." Compliance Manager would have been a NARROWING — it has Live
    # Operations at View and Settings hidden — which §15 forbids a migration from doing.
    assert plan == {
        TENANT: rbac.OWNER,
        "admin2@acp.test": rbac.PLATFORM_ADMIN,
        "user1@acp.test": rbac.PLATFORM_USER,
        "user2@acp.test": rbac.PLATFORM_USER,
    }


def test_a_standard_user_keeps_the_workflow_rather_than_being_narrowed(isolated_store):
    """§15's hard requirement, asserted as capability rather than as a role name — the role name
    could be right while the role itself had been edited into something narrower.

    Today every admitted user sees every workflow tab (core.OPEN_ACCESS). Mapping them to Viewer
    or Analyst would remove access on the morning the flag is turned on, which is exactly what
    §15 forbids; Compliance Manager is the narrowest built-in that keeps the whole workflow."""
    caps = rbac.builtin_capabilities(rbac.PLATFORM_USER)
    for workflow in ("discover.run", "assess.run", "remediate.run", "release.view", "monitor.view"):
        assert workflow in caps, f"a migrated standard user lost {workflow}"
    # And the two Compliance Manager would have taken away, which is why the target changed.
    assert "operations.view" in caps and "settings.view" in caps


def test_a_dry_run_writes_nothing_and_reports_the_same_shape(isolated_store):
    """The 'Observe' step of the §15 rollout. A preview whose shape differs from the real run is
    a preview of something else, so both return the same rows — only `applied` differs."""
    st = isolated_store
    _seed_people(st)
    preview = wr.migrate_people(st, tenant_id=TENANT, owner_email=TENANT, dry_run=True)
    assert {r["email"] for r in preview} == {TENANT, "admin2@acp.test",
                                            "user1@acp.test", "user2@acp.test"}
    assert all(r["applied"] is False for r in preview)
    assert all(wr.role_id_for_email(st, r["email"]) is None for r in preview)

    real = wr.migrate_people(st, tenant_id=TENANT, owner_email=TENANT)
    assert [(r["email"], r["to"]) for r in real] == [(r["email"], r["to"]) for r in preview]
    assert all(r["applied"] is True for r in real)


def test_re_running_the_migration_does_not_overwrite_a_later_decision(isolated_store):
    """An administrator tightens a migrated user to Viewer. The migration runs again — on a
    redeploy, or because someone re-ran the bootstrap — and must not put them back."""
    st = isolated_store
    _seed_people(st)
    wr.migrate_people(st, tenant_id=TENANT, owner_email=TENANT)
    wr.assign_role(st, email="user1@acp.test", role_id=rbac.VIEWER, actor="owner@acp.test")

    second = {r["email"]: r for r in wr.migrate_people(st, tenant_id=TENANT, owner_email=TENANT)}
    assert second["user1@acp.test"]["applied"] is False
    assert wr.role_id_for_email(st, "user1@acp.test") == rbac.VIEWER


def test_the_store_admin_list_promotes_even_when_the_record_says_user(isolated_store):
    """`role` on the person record and store.get_admins() are two places ACP records the same
    fact, and they can disagree — an owner-promoted admin is in the second and not the first.
    Reading only the record would demote them on migration day."""
    st = isolated_store
    st.upsert_person({"email": "promoted@acp.test", "role": "user"})
    st.set_admins(["promoted@acp.test"])
    plan = {r["email"]: r["to"] for r in
            wr.migrate_people(st, tenant_id=TENANT, owner_email=TENANT)}
    assert plan["promoted@acp.test"] == rbac.PLATFORM_ADMIN


def test_bootstrap_seeds_before_it_assigns(isolated_store):
    """Order, asserted by outcome: every assigned role id must resolve to a role that exists.
    A dangling id reads to the gate as 'role not found', which fails closed — so the migration
    would lock people out of a feature that had not gone wrong."""
    st = isolated_store
    _seed_people(st)
    out = wr.bootstrap(st, owner_email=TENANT, actor="owner@acp.test")
    assert out["tenant_id"] == TENANT
    for row in out["assignments"]:
        assert st.get_workspace_role(tenant_id=TENANT, role_id=row["to"]) is not None, \
            f"{row['email']} was assigned {row['to']}, which does not exist"


def test_bootstrap_with_no_owner_configured_uses_one_named_tenant(isolated_store):
    """Local dev, demo, no auth. An empty tenant key would be indistinguishable from a bug that
    dropped it, and two such deployments would share a row space by accident."""
    assert wr.tenant_id_for(None) == "default"
    assert wr.tenant_id_for("  ") == "default"
    st = isolated_store
    out = wr.bootstrap(st, owner_email=None)
    assert out["tenant_id"] == "default"
    assert st.get_workspace_role(tenant_id="default", role_id=rbac.OWNER) is not None


# ── the flag ──────────────────────────────────────────────────────────────────

def test_the_feature_is_off_unless_explicitly_turned_on(monkeypatch):
    """A control must not depend on a variable being absent — api/core.py's TEST_BYPASS_ENABLED
    comment records what that cost here before. This is the same rule pointed the other way: the
    NEW behaviour is what must be opted into, so no missing or misspelled variable can change how
    an existing deployment authorizes anybody."""
    monkeypatch.delenv(wr.FLAG, raising=False)
    assert wr.rbac_enabled() is False
    for off in ("", "0", "false", "no", "off", "maybe", "TRUE-ish"):
        monkeypatch.setenv(wr.FLAG, off)
        assert wr.rbac_enabled() is False, f"{off!r} enabled RBAC"
    for on in ("1", "true", "TRUE", "yes", "on"):
        monkeypatch.setenv(wr.FLAG, on)
        assert wr.rbac_enabled() is True, f"{on!r} did not enable RBAC"


def test_seeding_and_migrating_are_safe_with_the_flag_off(isolated_store, monkeypatch):
    """Rows may be written before enforcement exists — that is the whole point of the staged
    rollout in §15. What must NOT happen is the flag's state changing what gets written, or the
    bootstrap refusing to run and leaving step 1 undone when step 3 arrives."""
    monkeypatch.delenv(wr.FLAG, raising=False)
    st = isolated_store
    _seed_people(st)
    out = wr.bootstrap(st, owner_email=TENANT)
    assert out["enabled"] is False
    assert set(out["roles_created"]) == set(rbac.BUILTIN_ROLES)
    assert wr.role_id_for_email(st, "user1@acp.test") == rbac.PLATFORM_USER
