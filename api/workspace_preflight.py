"""Is it safe to advance the rollout one rung? (PRD §15, §18.)

An operator about to change `ACP_WORKSPACE_RBAC_MODE` has exactly one question — "who breaks?" —
and before this module the only way to answer it was to read every person's role by hand and
reason about the capability map. That is a question people answer optimistically when it is
tedious, and the cost of being wrong lands on users mid-workday.

WHAT MAKES THIS DIFFERENT FROM A HEALTH CHECK: it does not return a boolean. `safe: true` invites
exactly one behaviour — advancing without reading — and the interesting output here is never the
verdict, it is the NAMES. Who loses what. Which routes nobody mapped. Which people the migration
never reached. So the report is a list of blockers and warnings, each carrying the specific fact
that produced it, and `ready` is a derived convenience that an operator can disagree with.

BLOCKER vs WARNING, and the line is deliberate:

  * A BLOCKER is a fact that makes the next rung UNSAFE regardless of intent — roles never seeded,
    a mode string nobody can parse, a route the capability map does not know about, or a person
    losing access that NO ADMINISTRATOR CHOSE to take away.
  * A WARNING is a consequence somebody may well have intended. An administrator who moved Jane to
    Viewer meant for Jane to lose things; saying so is useful, blocking on it is the report crying
    wolf until it gets ignored.

That distinction is the whole reason losses are split by whether the person carries an explicit
assignment. §15's rule is that migration must not UNEXPECTEDLY remove access — not that access
never narrows.
"""
from __future__ import annotations

import workspace_capability_map as capmap
import workspace_rbac as rbac
import workspace_rollout as rollout
import workspace_roles as wr

# How far back the observed-denial counts look. The decision log is read newest-first with a cap
# because it is the busiest table in the product — role rows are a rounding error in it, and
# scanning the whole thing to count a handful would make the report expensive enough that nobody
# runs it before advancing, which is the only moment it matters.
DECISION_SCAN_LIMIT = 2000

WOULD_DENY = "role.access_would_deny"
DENIED = "role.access_denied"


def _blocker(code: str, detail: str, **extra) -> dict:
    return {"code": code, "severity": "blocker", "detail": detail, **extra}


def _warning(code: str, detail: str, **extra) -> dict:
    return {"code": code, "severity": "warning", "detail": detail, **extra}


def _people_report(store, *, owner_email: str | None, is_suspended=None) -> dict:
    """Every managed person, today's access against the access their role would give.

    Compared as CAPABILITIES rather than tabs because capabilities are what the server enforces —
    a tab dropping from Operate to View is only meaningful through the capabilities it costs, and
    reporting the tab would describe the symptom while the 403 comes from the capability.
    """
    today = set(wr.legacy_access()[1])
    owner = (owner_email or "").strip().lower()
    rows, unassigned, suspended = [], 0, 0

    for person in store.get_people():
        email = (person.get("email") or "").strip().lower()
        if not email:
            continue
        assigned = wr.role_id_for_email(store, email)
        planned = wr.planned_access(store, email, owner_email=owner_email,
                                    is_suspended=is_suspended)
        caps = set(planned.get("capabilities") or ())
        if person.get("status") == "suspended":
            suspended += 1
        if not assigned:
            unassigned += 1
        rows.append({
            "email": email,
            "assigned_role": assigned,
            "effective_role": (planned.get("role") or {}).get("id"),
            "owner": email == owner and bool(owner),
            "defaulted": bool(planned.get("defaulted")),
            "loses": sorted(today - caps),
            "keeps": len(caps),
        })

    return {"people": rows, "unassigned": unassigned, "suspended": suspended,
            "total": len(rows)}


def _observed(store) -> dict:
    """What observe mode actually saw. Counted from the audit log, which is the only durable
    record — workspace_denials' window is in-process memory and dies with the replica."""
    counts = {WOULD_DENY: 0, DENIED: 0}
    samples = []
    try:
        decisions = store.list_decisions(limit=DECISION_SCAN_LIMIT)
    except Exception:
        # A report that cannot read history is still worth serving — the access diff above is the
        # part that decides the rollout, and it does not depend on this. Reporting the counts as
        # unknown is honest; failing the whole call would make a busy database look like a
        # blocked rollout.
        return {"counts": counts, "samples": [], "readable": False}
    for row in decisions:
        action = row.get("action") or ""
        if action in counts:
            counts[action] += 1
            if len(samples) < 20:
                samples.append({"action": action, "actor": row.get("actor"),
                                "detail": row.get("detail"), "at": str(row.get("ts") or "")})
    return {"counts": counts, "samples": samples, "readable": True}


def report(store, *, owner_email: str | None, routes=None, is_suspended=None) -> dict:
    """The whole preflight answer for the rung above the current one."""
    state = rollout.describe()
    target = state["next"]
    tenant = wr.tenant_id_for(owner_email)
    seeded = {r["id"] for r in store.list_workspace_roles(tenant_id=tenant)}
    people = _people_report(store, owner_email=owner_email, is_suspended=is_suspended)
    observed = _observed(store)
    findings: list[dict] = []

    if state["invalid_mode"]:
        findings.append(_blocker(
            "mode_unreadable",
            f"{rollout.MODE_VAR}={state['invalid_mode']!r} is not one of "
            f"{', '.join(rollout.LADDER)}. The rollout is running as {state['mode']!r} — which is "
            "NOT what that variable was set to, and is the state an operator is least likely to "
            "notice, because an unenforced workspace looks exactly like one nobody has got to."))

    if state["mode"] != rollout.ENFORCE and state["legacy_flag"] and state["mode"] != rollout.OFF:
        findings.append(_warning(
            "legacy_flag_shadowed",
            f"{rollout.LEGACY_VAR} is still set but {rollout.MODE_VAR} takes precedence. Remove "
            "the old variable so the next person to read this configuration is not told two "
            "different things."))

    missing = [r for r in (rbac.OWNER, rbac.PLATFORM_USER) if r not in seeded]
    if missing:
        findings.append(_blocker(
            "roles_not_seeded",
            "The built-in roles are missing from this workspace: " + ", ".join(missing) +
            ". Run the bootstrap with {\"apply\": true} first — every unassigned person resolves "
            "through the default role, so advancing without it refuses everybody at once.",
            missing=missing))

    if routes is not None:
        unmapped = capmap.unmapped_routes(routes)
        if unmapped:
            findings.append(_blocker(
                "routes_unmapped",
                f"{len(unmapped)} registered route(s) have no capability decision. The gate lets "
                "an unmapped route through, so these are open to every role — a new tab would "
                "inherit access silently, which is the outcome this design refuses.",
                routes=[f"{m} {p}" for m, p in unmapped[:25]]))

    unknown = capmap.unknown_capabilities()
    if unknown:
        findings.append(_blocker(
            "capabilities_unknown",
            "The capability map names capabilities the catalog does not define: " +
            ", ".join(unknown) + ". No role can hold one, so those routes refuse everybody.",
            capabilities=unknown))

    # The §15 rule, checked as two different facts rather than one.
    unchosen = [p for p in people["people"]
                if p["loses"] and not p["assigned_role"] and not p["owner"]]
    chosen = [p for p in people["people"]
              if p["loses"] and p["assigned_role"] and not p["owner"]]
    if unchosen:
        findings.append(_blocker(
            "unassigned_people_lose_access",
            f"{len(unchosen)} person/people with no assigned role would LOSE access — nobody "
            "chose that. They resolve through the default role, so either it has been narrowed "
            "or it is missing. PRD §15: migration must not unexpectedly remove access.",
            people=[{"email": p["email"], "loses": p["loses"]} for p in unchosen[:25]]))
    if chosen:
        findings.append(_warning(
            "assigned_people_lose_access",
            f"{len(chosen)} person/people would lose capabilities their assigned role does not "
            "include. This is what assigning a narrower role MEANS — listed so it is a decision "
            "somebody confirms rather than one they discover.",
            people=[{"email": p["email"], "role": p["assigned_role"], "loses": p["loses"]}
                    for p in chosen[:25]]))

    # Advancing to enforcement on no evidence is the specific mistake the observe rung exists to
    # prevent, so it is called out at exactly the moment it would be made.
    if target == rollout.ENFORCE:
        if observed["readable"] and observed["counts"][WOULD_DENY] == 0:
            findings.append(_warning(
                "no_observations",
                "No `role.access_would_deny` rows were found. Either the observe rung has not run "
                "under real traffic yet, or it ran and found nothing. Those are very different "
                "situations and this report cannot tell them apart — check that the workspace has "
                "actually been used since the rung was raised."))
        elif observed["counts"][WOULD_DENY]:
            findings.append(_warning(
                "observed_would_deny",
                f"{observed['counts'][WOULD_DENY]} recorded refusal(s) that enforcement WOULD "
                "have made. Each is a real request by a real user that will start returning 403. "
                "Read them before advancing — they are the whole reason to run observe mode.",
                count=observed["counts"][WOULD_DENY]))

    blockers = [f for f in findings if f["severity"] == "blocker"]
    return {
        "rollout": state,
        "target": target,
        "ready": target is not None and not blockers,
        "at_top": target is None,
        "findings": findings,
        "blockers": len(blockers),
        "warnings": len(findings) - len(blockers),
        "people": people,
        "observed": observed,
        "roles_seeded": sorted(seeded),
        "tenant_id": tenant,
    }
