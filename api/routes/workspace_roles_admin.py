"""Role administration (PRD §8, §9, §13) — the endpoints behind the Roles tab.

WHAT IS ACTUALLY HARD HERE is not the CRUD. It is PRD §14, whose rules exist because each one
names a way an administrator can destroy their own ability to administer:

    Owner is immutable                    editing it is how the anti-lockout role stops being one
    a role with users cannot be deleted   deleting it strands them on an id resolving to nothing,
                                          which the gate reads as a refusal — a mass lockout that
                                          looks like the feature working
    names are unique per tenant           two "Reviewer" roles means an assignment nobody can
                                          audit, because the name in the log names two things
    version checking on update            two administrators, two tabs, one silent overwrite
    no granting what you do not hold      otherwise any role-manager escalates to Owner in two
                                          clicks: make a role with everything, assign it to self
    someone keeps roles.manage            the rule that makes the others recoverable

Every one is enforced HERE, at the route, and not in the drawer. The drawer should also warn — a
control that lets you build something the server will reject is a bad control — but a check that
lives only in the UI is not a check, and this feature's whole premise is that the client is not
the boundary.

THE GATE IS `roles.manage`, NOT `is_admin`. Under ACP's default OPEN_ACCESS model core.is_admin()
is true for every authenticated user (api/core.py), so gating role administration on it would let
anyone who can sign in grant themselves anything. The protected owner is the one carve-out, for
the same anti-lockout reason as everywhere else in this feature: a fresh deploy whose roles nobody
can administer has no recovery path.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request

import core
import workspace_rbac as rbac
import workspace_rollout as rollout
import workspace_roles as wr

router = APIRouter()

# A role id is derived from the name, not supplied: an administrator naming a role should not have
# to think about identifiers, and letting them choose one invites a collision with a built-in.
_SLUG_STRIP = re.compile(r"[^a-z0-9]+")
_MAX_NAME = 60


def _tenant() -> str:
    return wr.tenant_id_for(core.OWNER_EMAIL)


def _actor(request: Request) -> str:
    return (getattr(request.state, "user_email", None) or "").strip().lower()


def _my_capabilities(request: Request) -> frozenset[str]:
    """What the CALLER holds — the ceiling on what they may grant (PRD §14)."""
    access = wr.access_for_email(core.store, _actor(request), owner_email=core.OWNER_EMAIL,
                                 is_suspended=_suspended)
    return frozenset(access.get("capabilities") or ())


def _suspended(email: str) -> bool:
    target = (email or "").strip().lower()
    person = next((p for p in core.store.get_people() if p.get("email") == target), None)
    return (person or {}).get("status") == "suspended"


def _require_roles_manage(request: Request) -> None:
    """The gate. `roles.manage`, or the protected owner.

    Deliberately NOT core.is_admin — see this module's docstring. Also deliberately not a no-op
    when no owner is configured: local dev has no owner, so `is_owner` already returns True for
    everyone there, and that is the one place a blanket bypass belongs.
    """
    if core.is_owner(_actor(request)):
        return
    if "roles.manage" not in _my_capabilities(request):
        raise HTTPException(403, "managing roles requires the roles.manage permission")


def _role_out(row: dict, counts: dict[str, int]) -> dict:
    """One role as the Roles list and drawer read it.

    `users` is on the ROLE rather than fetched per row by the client, because the list shows it
    for every role and §14 makes it consequential: it is what decides whether Delete is offered at
    all. A count the UI derives separately is a count that can disagree with the one the DELETE
    endpoint checks.
    """
    perms = row.get("permissions") or []
    tabs = rbac.tab_access_from_rows(perms)
    grants = sorted({p["capability"] for p in perms if (p.get("access_level") or "") == "granted"}
                    & set(rbac.GRANT_CAPABILITIES))
    return {
        "id": row["id"], "name": row["name"], "description": row.get("description") or "",
        "is_system": bool(row.get("is_system")), "is_protected": bool(row.get("is_protected")),
        "version": int(row.get("version") or 1),
        "tabs": rbac.tabs_payload(tabs), "grants": grants,
        "capabilities": sorted(rbac.builtin_capabilities(row["id"]) if row["id"] == rbac.OWNER
                               else rbac.capabilities_for(tabs, grants)),
        "users": counts.get(row["id"], 0),
        "created_by": row.get("created_by"), "updated_at": row.get("updated_at"),
    }


def _user_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for person in core.store.get_people():
        role_id = person.get(wr.ROLE_FIELD)
        if role_id:
            counts[role_id] = counts.get(role_id, 0) + 1
    return counts


def _validate_permissions(body: dict, caller: frozenset[str]) -> dict[str, str]:
    """Turn the drawer's payload into permission rows, refusing anything the caller cannot grant.

    UNKNOWN TABS AND LEVELS ARE REJECTED, not dropped. Silently discarding them would let a
    drawer built against a newer build save a role that means something different from what it
    displayed — the administrator reads one thing, the database stores another, and nothing says
    so.
    """
    tabs = body.get("tabs") or {}
    grants = body.get("grants") or []
    if not isinstance(tabs, dict) or not isinstance(grants, list):
        raise HTTPException(400, "tabs must be an object and grants a list")

    rows: dict[str, str] = {}
    for tab, level in tabs.items():
        if tab not in rbac.TAB_LABELS:
            raise HTTPException(400, f"unknown tab: {tab}")
        if level not in rbac.ACCESS_LEVELS:
            raise HTTPException(400, f"unknown access level for {tab}: {level}")
        rows[tab] = level
    for grant in grants:
        if grant not in rbac.GRANT_CAPABILITIES:
            raise HTTPException(400, f"unknown permission: {grant}")
        rows[grant] = "granted"

    # PRD §14: "Administrators cannot grant permissions they do not possess." Without this, a
    # role-manager escalates to Owner in two clicks — create a role holding everything, assign it
    # to themselves — and every check below becomes decorative.
    would_grant = rbac.capabilities_for({k: v for k, v in rows.items() if k in rbac.TAB_LABELS},
                                        {k for k, v in rows.items() if v == "granted"})
    excess = sorted(would_grant - caller)
    if excess:
        raise HTTPException(403, "you cannot grant permissions you do not hold yourself: "
                                 + ", ".join(excess))
    return rows


def _slug(name: str, taken: set[str]) -> str:
    base = _SLUG_STRIP.sub("-", (name or "").strip().lower()).strip("-") or "role"
    candidate, n = base, 2
    while candidate in taken:
        candidate, n = f"{base}-{n}", n + 1
    return candidate


# ── the catalog the drawer renders itself from ────────────────────────────────

@router.get("/admin/capabilities")
def list_capabilities(request: Request):
    """Every tab and permission a role can carry (PRD §13).

    Served rather than hardcoded in the SPA so the drawer cannot offer a control the server does
    not honour, or miss one it does. The two lists diverging is how a checkbox comes to do
    nothing — visibly ticked, silently ignored — which is worse than the permission not existing.
    """
    _require_roles_manage(request)
    return {
        "tabs": [{"key": k, "label": rbac.TAB_LABELS[k]} for k in rbac.TAB_KEYS],
        "levels": list(rbac.ACCESS_LEVELS),
        "grants": [{"key": k, "label": v} for k, v in rbac.GRANT_CAPABILITIES.items()],
        # What the CALLER holds. The drawer disables what they cannot grant rather than letting
        # them tick it and be refused on save — the refusal is correct but arrives after they have
        # designed the role around it.
        "mine": sorted(_my_capabilities(request)),
        "ungoverned_tabs": sorted(rbac.UNGOVERNED_TABS),
    }


# ── roles ─────────────────────────────────────────────────────────────────────

@router.get("/admin/roles")
def list_roles(request: Request):
    _require_roles_manage(request)
    counts = _user_counts()
    tenant = _tenant()
    # Seed on read so the Roles tab is never empty on a deployment that has not run the §15
    # bootstrap. Idempotent and non-overwriting (see workspace_roles.seed_builtin_roles), so this
    # cannot revert an administrator's edits — it only fills in what is missing.
    wr.seed_builtin_roles(core.store, tenant_id=tenant, actor=_actor(request) or "system")
    return {"roles": [_role_out(r, counts) for r in core.store.list_workspace_roles(tenant_id=tenant)],
            "enforced": wr.rbac_enabled(), "rollout": rollout.describe()}


@router.get("/admin/roles/{role_id}")
def get_role(role_id: str, request: Request):
    _require_roles_manage(request)
    row = core.store.get_workspace_role(tenant_id=_tenant(), role_id=role_id)
    if row is None:
        raise HTTPException(404, "role not found")
    return _role_out(row, _user_counts())


@router.post("/admin/roles")
def create_role(body: dict, request: Request):
    """Create a custom role, or duplicate a built-in one (PRD §4: "duplicate a built-in role and
    customize the copy")."""
    _require_roles_manage(request)
    tenant, actor = _tenant(), _actor(request)
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "a role name is required")
    if len(name) > _MAX_NAME:
        raise HTTPException(400, f"a role name must be {_MAX_NAME} characters or fewer")

    existing = core.store.list_workspace_roles(tenant_id=tenant)
    # PRD §14: names are unique within a tenant. Checked here for a clear message AND enforced by
    # a unique index (api/store.py), because two administrators creating "Reviewer" in the same
    # second both pass this read-then-check and one of them is wrong.
    if any((r.get("name") or "").strip().lower() == name.lower() for r in existing):
        raise HTTPException(409, f"a role named {name} already exists")

    # Duplicating: copy the source's permissions as the starting point. The COPY is an ordinary
    # custom role even when the source is protected — that is what makes Owner duplicable without
    # making it editable.
    rows = None
    if body.get("duplicate_of"):
        source = core.store.get_workspace_role(tenant_id=tenant, role_id=body["duplicate_of"])
        if source is None:
            raise HTTPException(404, "the role being duplicated does not exist")
        perms = source.get("permissions") or []
        rows = {p["capability"]: p["access_level"] for p in perms}
        if source["id"] == rbac.OWNER:
            # Owner's stored rows are not the whole truth — its capabilities are resolved from the
            # catalog so the anti-lockout guarantee survives new capabilities. A copy has no such
            # carve-out, so materialise what Owner actually holds or the duplicate silently grants
            # less than the role it claims to copy.
            rows = {**{k: rbac.OPERATE for k in rbac.TAB_KEYS},
                    **{g: "granted" for g in rbac.GRANT_CAPABILITIES}}
        caller = _my_capabilities(request)
        tabs = rbac.tab_access_from_rows([{"capability": k, "access_level": v}
                                          for k, v in rows.items()])
        grants = {k for k, v in rows.items() if v == "granted"}
        excess = sorted(rbac.capabilities_for(tabs, grants) - caller)
        if excess:
            raise HTTPException(403, "you cannot duplicate a role holding permissions you do not "
                                     "hold yourself: " + ", ".join(excess))
    else:
        rows = _validate_permissions(body, _my_capabilities(request))

    role_id = _slug(name, {r["id"] for r in existing})
    core.store.upsert_workspace_role(
        tenant_id=tenant, role_id=role_id, name=name,
        description=(body.get("description") or "").strip() or None,
        permissions=rows, is_system=False, is_protected=False, actor=actor,
        expected_version=None)
    core.store.log_decision(actor or "admin", "role.created",
                            detail=f"{role_id} · {name}"
                                   + (f" · copy of {body['duplicate_of']}" if body.get("duplicate_of") else ""))
    return _role_out(core.store.get_workspace_role(tenant_id=tenant, role_id=role_id), _user_counts())


@router.put("/admin/roles/{role_id}")
def update_role(role_id: str, body: dict, request: Request):
    _require_roles_manage(request)
    tenant, actor = _tenant(), _actor(request)

    # PRD §4: Owner "cannot be edited, deleted, or assigned by anyone except the current Owner",
    # and §14: "Owner always has every capability". Editing it is therefore refused outright
    # rather than restricted to the owner — there is no edit that leaves the guarantee intact, so
    # allowing the owner to make one would only let them remove their own last resort.
    if rbac.is_protected_role(role_id):
        raise HTTPException(409, "the Owner role cannot be edited — it exists so administrative "
                                 "lockout is impossible, and an edited Owner is not that role")

    current = core.store.get_workspace_role(tenant_id=tenant, role_id=role_id)
    if current is None:
        raise HTTPException(404, "role not found")

    name = (body.get("name") or current["name"]).strip()
    if not name:
        raise HTTPException(400, "a role name is required")
    if len(name) > _MAX_NAME:
        raise HTTPException(400, f"a role name must be {_MAX_NAME} characters or fewer")
    clash = [r for r in core.store.list_workspace_roles(tenant_id=tenant)
             if r["id"] != role_id and (r.get("name") or "").strip().lower() == name.lower()]
    if clash:
        raise HTTPException(409, f"a role named {name} already exists")

    rows = _validate_permissions(body, _my_capabilities(request))

    # PRD §14's concurrency check. A caller that omits `version` is refused rather than defaulted
    # to "no check": a client that does not send it has not read the role, and a blind overwrite
    # is exactly what this rule exists to prevent.
    if "version" not in body:
        raise HTTPException(400, "version is required — re-open the role and save again")
    try:
        saved = core.store.upsert_workspace_role(
            tenant_id=tenant, role_id=role_id, name=name,
            description=(body.get("description") or "").strip() or None,
            permissions=rows, is_system=bool(current.get("is_system")), is_protected=False,
            actor=actor, expected_version=int(body["version"]))
    except (TypeError, ValueError) as exc:
        raise HTTPException(409, str(exc))
    core.store.log_decision(actor or "admin", "role.updated", detail=f"{role_id} · {name}")
    return _role_out(saved, _user_counts())


@router.delete("/admin/roles/{role_id}")
def delete_role(role_id: str, request: Request):
    """Delete a role. Refused while anyone holds it (PRD §14: "Role deletion requires reassignment
    of affected users")."""
    _require_roles_manage(request)
    tenant, actor = _tenant(), _actor(request)
    if rbac.is_protected_role(role_id):
        raise HTTPException(409, "the Owner role cannot be deleted")
    row = core.store.get_workspace_role(tenant_id=tenant, role_id=role_id)
    if row is None:
        raise HTTPException(404, "role not found")

    # The count, not a flag, so the message can say how many — an administrator who has to
    # discover the number by trial is one who will delete the wrong thing eventually.
    holders = [p["email"] for p in core.store.get_people() if p.get(wr.ROLE_FIELD) == role_id]
    if holders:
        raise HTTPException(409, f"{len(holders)} user(s) still hold this role — reassign them "
                                 f"first: " + ", ".join(sorted(holders)[:5])
                                 + (" …" if len(holders) > 5 else ""))
    core.store.delete_workspace_role(tenant_id=tenant, role_id=role_id)
    core.store.log_decision(actor or "admin", "role.deleted", detail=f"{role_id} · {row['name']}")
    return {"deleted": role_id}


# ── assignment (PRD §9) ───────────────────────────────────────────────────────

@router.put("/admin/people/{email:path}/role")
def assign_person_role(email: str, body: dict, request: Request):
    """Give one person a workspace role.

    Gated on `people.manage` rather than `roles.manage`: designing roles and deciding who holds
    one are different jobs, and PRD §5 lists them as separate permissions. A caller holding only
    one of them can do only that half.
    """
    actor = _actor(request)
    if not core.is_owner(actor) and "people.manage" not in _my_capabilities(request):
        raise HTTPException(403, "assigning roles requires the people.manage permission")

    tenant = _tenant()
    target = (email or "").strip().lower()
    role_id = (body.get("role_id") or "").strip()
    if not target or "@" not in target:
        raise HTTPException(400, "a valid email is required")

    # THE ROSTER THE SCREEN RENDERED, not the `people` table underneath it. Reading the table
    # alone rejected everyone who has access by way of the ALLOWLIST without a stored record —
    # the "Provider not recorded" rows — with `404 person not found`, on a row whose dropdown the
    # administrator had just used. `wr.assign_role` upserts, so the write was always able to
    # create the record; only this lookup stood in the way.
    if core.person_with_access(target) is None:
        raise HTTPException(404, "person not found")

    # PRD §4: Owner is "assignable by the current Owner alone".
    if rbac.is_protected_role(role_id) and not core.is_owner(actor):
        raise HTTPException(403, "only the current Owner may assign the Owner role")

    if role_id:
        if core.store.get_workspace_role(tenant_id=tenant, role_id=role_id) is None:
            raise HTTPException(404, "role not found")
        # A role you do not hold is a role you cannot hand out, for the same reason you cannot
        # build one: otherwise assignment is the escalation path that role creation is not.
        if not core.is_owner(actor):
            granting = rbac.builtin_capabilities(role_id) if role_id == rbac.OWNER else (
                _capabilities_of(tenant, role_id))
            excess = sorted(granting - _my_capabilities(request))
            if excess:
                raise HTTPException(403, "you cannot assign a role holding permissions you do not "
                                         "hold yourself: " + ", ".join(excess))

    _guard_last_role_manager(tenant, target, role_id)
    wr.assign_role(core.store, email=target, role_id=role_id or None, actor=actor or "admin")
    # After `wr.assign_role` the record exists whether or not it did before, so this reads the
    # table directly — it is the row that was just written, not a membership question.
    return {"person": next(p for p in core.store.get_people() if p["email"] == target),
            "access": wr.access_for_email(core.store, target, owner_email=core.OWNER_EMAIL,
                                          is_suspended=_suspended)}


def _capabilities_of(tenant: str, role_id: str) -> frozenset[str]:
    row = core.store.get_workspace_role(tenant_id=tenant, role_id=role_id)
    if row is None:
        return frozenset()
    perms = row.get("permissions") or []
    tabs = rbac.tab_access_from_rows(perms)
    grants = {p["capability"] for p in perms if (p.get("access_level") or "") == "granted"}
    return rbac.capabilities_for(tabs, grants)


def _guard_last_role_manager(tenant: str, target: str, new_role_id: str) -> None:
    """PRD §14: "At least one non-suspended user must retain roles.manage."

    THE RULE THAT MAKES THE OTHERS RECOVERABLE. Every refusal above can be undone by somebody with
    roles.manage; if the last such person demotes themselves, none of them can. The protected
    owner is a standing holder — `core.is_owner` grants everything — so this only bites where no
    owner is configured, which is precisely the deployment with no other way back.
    """
    if core.OWNER_EMAIL:
        return                       # the owner always holds it; lockout is impossible
    # Over the roster, so the person being GRANTED roles.manage is counted even when they have no
    # stored record yet. Reading `store.get_people()` here skipped the target entirely in that
    # case: promoting an allowlist-only user to role manager was refused as "this would leave
    # nobody able to manage roles" while doing exactly the thing that fixes it — and this guard
    # only runs where no owner is configured, which is the deployment with no other way back.
    keeps = 0
    for person in core.people_with_access():
        email = person.get("email")
        if not email or person.get("status") == "suspended":
            continue
        role_id = new_role_id if email == target else person.get(wr.ROLE_FIELD)
        if role_id and "roles.manage" in _capabilities_of(tenant, role_id):
            keeps += 1
    if keeps == 0:
        raise HTTPException(409, "this would leave nobody able to manage roles — give another "
                                 "active user a role with the roles.manage permission first")


@router.get("/admin/people/{email:path}/role-impact")
def role_impact(email: str, request: Request, role_id: str = ""):
    """What changes if this person is given this role (PRD §9's confirmation).

    Computed SERVER-SIDE from the same resolver the gate uses, rather than diffed in the drawer
    from two capability lists. A confirmation that disagrees with what actually happens is worse
    than none: the administrator reads it, approves it, and something else occurs.
    """
    if not core.is_owner(_actor(request)) and "people.manage" not in _my_capabilities(request):
        raise HTTPException(403, "requires the people.manage permission")
    target = (email or "").strip().lower()
    before = wr.access_for_email(core.store, target, owner_email=core.OWNER_EMAIL,
                                 is_suspended=_suspended)
    tenant = _tenant()
    after_caps = (rbac.CAPABILITIES if role_id == rbac.OWNER
                  else _capabilities_of(tenant, role_id) if role_id else frozenset())
    # Compare against what the role WOULD give — `calculated` when unenforced, `capabilities`
    # when enforced — so the preview means the same thing before and after the flag is turned on.
    current = frozenset(before.get("calculated", {}).get("capabilities")
                        if not before.get("enforced") else before.get("capabilities") or ())
    return {"email": target, "role_id": role_id or None,
            "gains": sorted(after_caps - current), "loses": sorted(current - after_caps),
            "enforced": wr.rbac_enabled(), "mode": rollout.mode(),
            "now": datetime.now(timezone.utc).isoformat(timespec="seconds")}
