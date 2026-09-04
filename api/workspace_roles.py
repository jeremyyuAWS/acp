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
    # PRD §12 asks for `role.assigned` AND `role.unassigned`, and they are not the same event to
    # somebody reading the log: assigning is a grant, removing the last role is a REVOCATION, and
    # an auditor scanning for revocations should not have to notice that the arrow on an
    # `role.assigned` row happens to point at "none". Recorded under the action that names what
    # happened, with both values either way.
    action = "role.unassigned" if not role_id else "role.assigned"
    store.log_decision(actor or "system", action,
                       detail=f"{target} · {previous or 'none'} → {role_id or 'none'}")
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
      * everyone else                                    → Platform User

    PLATFORM USER, NOT COMPLIANCE MANAGER, since the owner's 2026-09-04 decision: "All signed-in
    users receive a default Platform User RBAC role... Existing users should be backfilled
    automatically."

    It is also the stronger reading of §15's "must not unexpectedly remove access". Compliance
    Manager has Live Operations at View and Settings HIDDEN (PRD §7), so migrating a standard user
    onto it would have taken away two surfaces they can reach today under the OPEN_ACCESS model —
    a narrowing nobody asked for, applied on the morning the flag went on. Platform User takes
    away nothing, which is what a backfill should do; narrowing is then an administrator's
    deliberate act in the Roles screen rather than a side effect of the migration.
    """
    email = (person.get("email") or "").strip().lower()
    if owner_email and email == owner_email:
        return rbac.OWNER
    if (person.get("role") or "").strip().lower() == "admin" or email in store_admins:
        return rbac.PLATFORM_ADMIN
    return rbac.PLATFORM_USER


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


# ── resolving one identity's access (PRD §13) ─────────────────────────────────

def _legacy_access() -> tuple[dict[str, str], frozenset[str]]:
    """What every admitted user has TODAY, before this feature enforces anything.

    Every governed tab at Operate and every capability, because that is the truth about ACP as it
    ships: `core.OPEN_ACCESS` is on by default and there is no separate admin view. Written out as
    a function rather than assumed at each call site so "what does the flag being off mean" has
    exactly one answer, and so the observe-mode diff below compares against something real.
    """
    return ({k: rbac.OPERATE for k in rbac.TAB_KEYS}, rbac.CAPABILITIES)


def _stored_access(store, *, tenant_id: str, role_id: str) -> tuple[dict, frozenset] | None:
    """One role's tab access and capabilities, or None when the role does not resolve.

    None is the fail-closed signal and the reason this returns an Optional rather than an empty
    pair: a role id that names nothing is a DIFFERENT fact from a role that grants nothing, and
    only the first should make a caller refuse. PRD §14: "Failure to load permissions must fail
    closed for sensitive operations."
    """
    row = store.get_workspace_role(tenant_id=tenant_id, role_id=role_id)
    if row is None:
        return None
    perms = row.get("permissions") or []
    tab_access = rbac.tab_access_from_rows(perms)
    grants = {p["capability"] for p in perms if (p.get("access_level") or "") == "granted"}
    if role_id == rbac.OWNER:
        # Owner always holds every capability (PRD §14), including ones added after the row was
        # written. Reading Owner off its stored rows would make the anti-lockout guarantee depend
        # on a migration having been re-run, which is exactly the dependency it exists to remove.
        return ({k: rbac.OPERATE for k in rbac.TAB_KEYS}, rbac.CAPABILITIES)
    return (tab_access, rbac.capabilities_for(tab_access, grants))


def access_for_email(store, email: str | None, *, owner_email: str | None,
                     is_suspended=None) -> dict:
    """The whole answer GET /me/access returns for one identity.

    THE SHAPE CARRIES ITS OWN AUTHORITY. `enforced` says whether `tabs`/`capabilities` are the
    rules or merely today's status quo, and `calculated` (present only when NOT enforced) is what
    the assigned role WOULD give. That pair is the §15 "Observe" step made readable: an operator
    can diff what a person has against what the migration decided, before flipping the flag, from
    one response rather than by reasoning about two code paths.

    Four ways this resolves, and the order matters:

      1. the protected owner            → everything, always. The anti-lockout carve-out.
      2. the flag is off                → today's access, unchanged, plus `calculated`.
      3. a role that resolves           → what that role grants.
      4. anything else                  → NOTHING. Unassigned, suspended, or a role id naming a
                                          row that is not there. All three mean "we could not
                                          establish what this person may do", and the safe
                                          reading of that is not "the usual".
    """
    tenant = tenant_id_for(owner_email)
    who = (email or "").strip().lower()
    role_id = role_id_for_email(store, who)
    row = store.get_workspace_role(tenant_id=tenant, role_id=role_id) if role_id else None
    role = {"id": role_id, "name": (row or {}).get("name") or role_id} if role_id else None
    version = int((row or {}).get("version") or 0)

    # 1. The owner carve-out comes FIRST, before the flag and before any lookup can fail. An owner
    #    locked out by a bad row is the one failure mode with no recovery path — nobody else can
    #    grant the role back.
    owner = (owner_email or "").strip().lower()
    if owner and who == owner:
        tabs, caps = _legacy_access()
        return {"role": role or {"id": rbac.OWNER, "name": "Owner"},
                "tabs": rbac.tabs_payload(tabs), "capabilities": sorted(caps),
                "version": version, "enforced": rbac_enabled(), "owner": True}

    # 2. Off means off. Nothing about anyone's access changes until an operator says so.
    if not rbac_enabled():
        tabs, caps = _legacy_access()
        would = _stored_access(store, tenant_id=tenant, role_id=role_id) if role_id else None
        calculated = ({"tabs": rbac.tabs_payload(would[0]), "capabilities": sorted(would[1])}
                      if would else {"tabs": rbac.tabs_payload({}), "capabilities": []})
        return {"role": role, "tabs": rbac.tabs_payload(tabs), "capabilities": sorted(caps),
                "version": version, "enforced": False, "owner": False,
                "calculated": calculated}

    # 3/4. Enforcing. A suspended user has no effective permissions (PRD §14) and is checked
    #      before the role, because a suspended person may still carry a perfectly valid one.
    if is_suspended and is_suspended(who):
        return {"role": role, "tabs": rbac.tabs_payload({}), "capabilities": [],
                "version": version, "enforced": True, "owner": False}

    # AN UNASSIGNED SIGNED-IN USER GETS THE DEFAULT ROLE, NOT NOTHING. Owner decision,
    # 2026-09-04: "All signed-in users receive a default Platform User RBAC role... Existing users
    # should be backfilled automatically."
    #
    # This deliberately REVERSES what slices 1–3 did for the unassigned case, and the reversal is
    # narrow enough to be worth stating precisely, because "fail closed" is why the rest of this
    # file is shaped the way it is:
    #
    #   unassigned            -> Platform User. Being signed in is itself an authorization
    #                            decision — core.email_allowed already admitted them — so a user
    #                            with no role is not an unknown, they are a known user nobody has
    #                            narrowed yet. Refusing them would mean turning the flag on locks
    #                            the entire company out until an administrator assigns every
    #                            person by hand, which is the outcome PRD §15 forbids in the
    #                            migration and would be no better here.
    #   suspended             -> nothing, checked above. Access was deliberately withdrawn.
    #   assigned a role that
    #   does not resolve      -> nothing, below. Somebody DID narrow them, and the row that says
    #                            how is missing; falling back to full access would silently undo
    #                            an administrator's decision, which is the fail-open this file
    #                            exists to prevent.
    #
    # The distinction that makes both halves right is the one this codebase keeps having to
    # relearn: "nobody has decided yet" and "a decision was recorded and cannot be read" are
    # different facts, and only the second is a failure.
    # "All SIGNED-IN users" — an empty identity is not one, and this guard is the difference
    # between a default and a hole. Found by test_an_anonymous_caller_gets_nothing_when_enforcing,
    # which was written for slice 2's contract and kept failing after the default was added: with
    # `who` empty, role_id_for_email returns None, which fell straight into the default branch
    # below and handed Platform User to a caller with no identity at all. In production the access
    # gate 401s first, so the reachable surface was the exempt endpoints (/me/access,
    # /workspace/bootstrap) — but "the other gate happens to stop it" is not a reason for this one
    # to be wrong, and those two are precisely what a signed-out browser calls.
    if not who:
        return {"role": None, "tabs": rbac.tabs_payload({}), "capabilities": [],
                "version": 0, "enforced": True, "owner": False}

    if not role_id:
        default = _stored_access(store, tenant_id=tenant, role_id=rbac.PLATFORM_USER)
        if default is None:
            # The default role has not been seeded in this tenant. Fail CLOSED rather than
            # inventing it from the catalog: a tenant whose roles were never seeded is one where
            # nothing else can be trusted either, and the recovery (run the bootstrap) is one
            # owner-only call away — the owner having been let through above.
            return {"role": None, "tabs": rbac.tabs_payload({}), "capabilities": [],
                    "version": 0, "enforced": True, "owner": False, "default_missing": True}
        tabs, caps = default
        row = store.get_workspace_role(tenant_id=tenant, role_id=rbac.PLATFORM_USER)
        return {"role": {"id": rbac.PLATFORM_USER, "name": row.get("name") or "Platform User"},
                "tabs": rbac.tabs_payload(tabs), "capabilities": sorted(caps),
                "version": int(row.get("version") or 1), "enforced": True, "owner": False,
                "defaulted": True}

    resolved = _stored_access(store, tenant_id=tenant, role_id=role_id)
    if resolved is None:
        return {"role": role, "tabs": rbac.tabs_payload({}), "capabilities": [],
                "version": version, "enforced": True, "owner": False}
    tabs, caps = resolved
    return {"role": role, "tabs": rbac.tabs_payload(tabs), "capabilities": sorted(caps),
            "version": version, "enforced": True, "owner": False}


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
