"""Workspace roles, bound to the store: seeding, assignment, and the §15 migration.

api/workspace_rbac.py is the decision table and knows nothing about the database. This module is
the other half — it reads and writes rows, and it owns the two operations that turn an existing
deployment into one with roles:

    seed_builtin_roles()   put the six built-in roles into a tenant, idempotently
    migrate_people()       give every existing person the role PRD §15 maps them to

THE FLAG IS OFF BY DEFAULT AND THAT IS A SECURITY DECISION, not caution about polish. Seeding and
migrating are safe (they only write rows nothing reads yet); ENFORCEMENT is what changes who can
do what, and it arrives in later slices behind the same flag. api/core.py already carries the
lesson in TEST_BYPASS_ENABLED's comment: a control must not depend on a variable being absent.
Here the same rule points the other way round — the feature is the new thing, so its ABSENCE must
leave today's behaviour exactly as it is.

MIGRATION MUST NOT REMOVE ACCESS (PRD §15). An existing standard user becomes a Compliance
Manager, not a Viewer, because today every admitted user sees every workflow tab (core.py's
OPEN_ACCESS model). Mapping them to anything narrower would take away access on the morning the
flag is switched on, which is the one outcome §15 forbids. Administrators tighten afterwards,
having seen the generated assignments.
"""
from __future__ import annotations

import os

import workspace_rbac as rbac

# Explicit opt-in, matching api/core.py's idiom. Read at call time rather than captured at import
# so a test can set it without reloading the module — and so a deployment that flips the variable
# does not need a different process to notice.
FLAG = "ACP_WORKSPACE_RBAC_ENABLED"


def rbac_enabled() -> bool:
    return os.environ.get(FLAG, "").strip().lower() in ("1", "true", "yes", "on")


def tenant_id_for(owner_email: str | None) -> str:
    """The tenant a role set belongs to.

    ACP has no first-class tenant column (api/store.py says so above scan_runs.owner_email); the
    owner email is the identifier every other table uses, and roles use the same one so a tenant's
    roles and its scans cannot end up keyed differently. An unconfigured owner — local dev, demo,
    no auth — is the single tenant `"default"` rather than an empty string, because an empty
    tenant key is indistinguishable from a bug that dropped it.
    """
    return (owner_email or "").strip().lower() or "default"


# ── seeding ───────────────────────────────────────────────────────────────────

def _permission_rows(role: dict) -> dict[str, str]:
    """A built-in role's definition as workspace_role_permissions rows.

    Tab rows carry the access level; grant rows carry the literal 'granted'. One table holds both
    (see the DDL) and this is the single place that decides how each is spelled, so a reader and a
    writer cannot disagree about what a row means.
    """
    rows = dict(role["tabs"])
    rows.update({grant: "granted" for grant in role["grants"]})
    return rows


def seed_builtin_roles(store, *, tenant_id: str, actor: str | None = None) -> list[str]:
    """Ensure the six built-in roles exist. Returns the ids actually created.

    IDEMPOTENT, AND IT DOES NOT OVERWRITE. A built-in role that is already present is left alone,
    because an administrator may have duplicated and edited it — and because re-running the seed
    on every boot would silently revert their edits, which is a data-loss bug that looks like a
    no-op. New built-ins added by a later build DO get created, which is the behaviour that makes
    this callable on every boot rather than once.

    Owner is seeded like the rest but marked protected, so the anti-lockout role exists from the
    first boot rather than being created by whoever happens to open the admin screen first.
    """
    created: list[str] = []
    for role_id, role in rbac.BUILTIN_ROLES.items():
        if store.get_workspace_role(tenant_id=tenant_id, role_id=role_id) is not None:
            continue
        store.upsert_workspace_role(
            tenant_id=tenant_id, role_id=role_id, name=role["name"],
            description=role["description"], permissions=_permission_rows(role),
            is_system=True, is_protected=role["is_protected"], actor=actor)
        created.append(role_id)
    return created


# ── assignment ────────────────────────────────────────────────────────────────
# The assignment lives on the managed-person record (PRD §12: "extend the existing managed-person
# record"), which api/store.py keeps as a JSON list in app_settings under `people_records`. Adding
# three keys to that record is genuinely all this needs — there is no people TABLE to alter.

ROLE_FIELD = "workspace_role_id"
ASSIGNED_BY_FIELD = "role_assigned_by"
ASSIGNED_AT_FIELD = "role_assigned_at"


def assign_role(store, *, email: str, role_id: str, actor: str | None = None) -> dict:
    """Give one person one workspace role, and record who did it and when.

    Writes an audit row (PRD §12 `role.assigned`) through the same decision log every other
    consequential action in this codebase uses, rather than a second log nobody reads.
    """
    from datetime import datetime, timezone
    target = (email or "").strip().lower()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    current = next((p for p in store.get_people() if p.get("email") == target), None)
    previous = (current or {}).get(ROLE_FIELD)
    record = store.upsert_person({"email": target, ROLE_FIELD: role_id,
                                  ASSIGNED_BY_FIELD: actor, ASSIGNED_AT_FIELD: now})
    store.log_decision(actor or "system", "role.assigned",
                       detail=f"{target} · {previous or 'none'} → {role_id}")
    return record


def role_id_for_email(store, email: str) -> str | None:
    """The role assigned to this person, or None if they have none.

    None means UNASSIGNED and callers must treat it as such — it is not "Viewer" and it is not
    "everything". Resolving it to a default here would put the fail-open decision in the one place
    no caller can see it; the gate decides, and PRD §14 says it fails closed.
    """
    target = (email or "").strip().lower()
    if not target:
        return None
    person = next((p for p in store.get_people() if p.get("email") == target), None)
    return (person or {}).get(ROLE_FIELD) or None


# ── the §15 migration ─────────────────────────────────────────────────────────

def planned_role_for(person: dict, *, owner_email: str, store_admins: set[str]) -> str:
    """Which built-in role PRD §15 maps this existing person to.

    Three inputs decide it, and all three are how ACP already describes the person today:
      * the protected ACP_OWNER_EMAIL                    → Owner
      * role=='admin' on the record, or a store admin    → Platform Admin
      * everyone else                                    → Compliance Manager

    Compliance Manager rather than a narrower role is the §15 "must not unexpectedly remove
    access" rule; see this module's docstring.
    """
    email = (person.get("email") or "").strip().lower()
    if owner_email and email == owner_email:
        return rbac.OWNER
    if (person.get("role") or "").strip().lower() == "admin" or email in store_admins:
        return rbac.PLATFORM_ADMIN
    return rbac.COMPLIANCE_MANAGER


def migrate_people(store, *, tenant_id: str, owner_email: str | None,
                   actor: str | None = None, dry_run: bool = False) -> list[dict]:
    """Assign every existing person their §15 role. Returns the plan, applied or not.

    `dry_run` is the "Observe" step of the §15 rollout — calculate the mapping and report it
    without writing anything, so an administrator can read the generated assignments before they
    mean something. It returns the SAME shape as a real run, because a preview that differs in
    shape from the thing it previews is a preview of something else.

    Already-assigned people are left alone: re-running must not overwrite an administrator's
    later, deliberate tightening with the migration's opening guess.
    """
    owner = (owner_email or "").strip().lower()
    admins = {e.strip().lower() for e in (store.get_admins() or [])}
    plan: list[dict] = []
    for person in store.get_people():
        email = (person.get("email") or "").strip().lower()
        if not email:
            continue
        existing = person.get(ROLE_FIELD) or None
        target = planned_role_for(person, owner_email=owner, store_admins=admins)
        plan.append({"email": email, "from": existing, "to": target,
                     "applied": bool(not dry_run and existing is None)})
        if existing is None and not dry_run:
            assign_role(store, email=email, role_id=target, actor=actor or "migration")
    return plan


def bootstrap(store, *, owner_email: str | None, actor: str | None = None,
              dry_run: bool = False) -> dict:
    """Seed the built-in roles and migrate existing people, in that order.

    The order matters and is not incidental: assigning a person a role that does not exist yet
    would leave a dangling id that resolves to nothing, and "resolves to nothing" is exactly the
    state the gate must treat as a refusal — so the migration would lock people out of a feature
    that had not gone wrong.
    """
    tenant = tenant_id_for(owner_email)
    created = [] if dry_run else seed_builtin_roles(store, tenant_id=tenant, actor=actor)
    plan = migrate_people(store, tenant_id=tenant, owner_email=owner_email, actor=actor,
                          dry_run=dry_run)
    return {"tenant_id": tenant, "roles_created": created, "assignments": plan,
            "dry_run": dry_run, "enabled": rbac_enabled()}
