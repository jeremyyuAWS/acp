# ADR 0049 — Workspace RBAC: three authorization boundaries, and a rollout that can be reversed

Status: Accepted
Date: 2026-09-04
Phase: 6 of 6 (final slice of the Configurable ACP Roles and Tab Access PRD)

## Context

ACP shipped with one idea of authorization: `core.is_admin()`. Under `ACP_OPEN_ACCESS`, which is
**on by default**, that function returns `True` for every authenticated user. It is not a weak
boundary; it is not a boundary at all. Every "admin-only" route in the product was reachable by
anybody the allowlist admitted.

Slices 1–6 added a workspace role model on top of that, which raises two questions this ADR
exists to answer: what the new boundary is *for* (and, more importantly, what it is not for), and
how a workspace turns it on without locking anybody out on a Tuesday morning.

## Decision 1 — three authorization boundaries, kept separate on purpose

The tempting simplification is one permission system. It is wrong here, because the three answer
different questions and are trusted by different people:

| Boundary | Question | Where | Changed by |
|---|---|---|---|
| `core.is_admin` / `email_allowed` | May this person use ACP at all? | `api/core.py` | the allowlist, the owner |
| `acr_authz` | May this person approve or publish a **conformance report**? | `api/acr_authz.py` | ACR reviewer roles |
| `workspace_rbac` | May this person see this **tab** and perform this **action**? | `api/workspace_rbac.py` | workspace administrators |

The ACR boundary is the one worth naming explicitly. An Accessibility Conformance Report is a
compliance claim sent to customers who rely on it, and who may approve one is a decision with
legal weight (ADR 0047). A workspace administrator gaining the ability to grant ACR approval by
editing a workspace role would move that decision to a different authority without anybody
deciding to. So no workspace capability grants any ACR right, and
`tests/test_capability_map_is_complete.py::test_no_acr_route_is_governed_by_a_workspace_capability`
holds the line as a test rather than as a convention.

## Decision 2 — one enforcement point, and a table that must be complete

The gate is a single middleware in `api/app.py`, not a decorator on 236 routes. Route → capability
lives in `api/workspace_capability_map.py` as one table.

The reason is the failure mode of the alternative: a decorator per route means the 237th route
added next week has no decorator, is open to everybody, and nothing reports it. With a table,
"every route has a capability decision" becomes a property that can be *checked* — and it is,
against the app's real registered route table, in CI and again at runtime through the preflight
report. An unmapped route is allowed through by design (a 403 on every new endpoint would take the
product down on the day somebody adds one), which is safe **only** because the completeness check
makes an unmapped route impossible to merge. The check is load-bearing, not hygiene.

This also satisfies the owner's decision of 2026-09-04 that *"new tabs should require an explicit
capability decision rather than silently inheriting access"*: the decision is a line in a table,
and omitting it fails a test with the route's name in it.

## Decision 3 — the default role reverses fail-closed, for exactly one case

PRD §14 says failure to load permissions must fail closed. Every path in `access_for_email` obeys
that except one: a signed-in person with **no assigned role** resolves to `Platform User`, which
grants every current tab.

That is the owner's decision (2026-09-04) and it is narrower than it looks:

- **unassigned** → the default. Being signed in is already an authorization decision;
  `core.email_allowed` admitted them. They are not an unknown, they are a known user nobody has
  narrowed. Refusing them would mean enabling the feature locks the whole company out until an
  administrator assigns every person by hand.
- **suspended** → nothing. Access was deliberately withdrawn.
- **assigned a role that does not resolve** → nothing. Somebody *did* narrow them and the row
  saying how is missing; granting full access would silently undo an administrator's decision.

The distinction underneath all three: *"nobody has decided yet"* and *"a decision was recorded and
cannot be read"* are different facts, and only the second is a failure.

## Decision 4 — the rollout is a ladder, not a switch

`ACP_WORKSPACE_RBAC_MODE` selects one of four rungs (`api/workspace_rollout.py`):

| Rung | The SPA | The server | What it buys |
|---|---|---|---|
| `off` | unchanged | unchanged | the store is never read; the default path costs nothing |
| `observe` | unchanged | allows, **records** | who would have been refused, from real traffic, at zero user impact |
| `navigation` | hides tabs | allows, records | removes the "click a tab, get a wall of 403s" failure on its own |
| `enforce` | hides tabs | **refuses** | the actual control |

Going straight from `off` to `enforce` is one deployment in which every wrong permission becomes a
403 for somebody doing their job, and the first you hear of it is a support ticket. The middle
rungs each remove one class of that risk *before* it can bite. `observe` is the important one: a
capability map that is subtly wrong is invisible in tests, because tests assert the mapping we
intended — only real traffic exercises the mapping we actually wrote.

`ACP_WORKSPACE_RBAC_ENABLED=1` still means `enforce`. Slices 1–5 shipped that variable and a
deployment may carry it; a release that quietly stopped honouring it would turn enforcement **off**
in a workspace that believed it was enforcing. Removing a security control by renaming its switch
is the failure mode the alias prevents.

### An unreadable mode does not mean "enforce"

A typo (`enfoce`) falls back to whatever readable configuration remains, and `off` if none does —
never to enforcement. Enforcing on a misspelling would lock a workspace out on a deploy nobody
thought was risky, and §15's own rule is that migration must not unexpectedly remove access.

The cost of that choice is the state an operator is *least* likely to notice: running unenforced
while believing otherwise, which looks exactly like a workspace nobody has got to yet. So the bad
value is kept rather than discarded, and surfaced as a **blocker** in the preflight report and as
an alert on the Roles screen. The fallback is quiet; the fact of it is not.

## Decision 5 — denials are coalesced, and observations are a separate event

`decision_log` is append-only by design — it is what an auditor reads. A row per refusal would
bury the role changes and publish approvals it exists for, and would make a 403 cost a database
write, which is a denial-of-service available to anyone with a valid session.

So the first refusal of a `(person, capability requirement)` is recorded immediately, repeats are
suppressed for two minutes, and the next recorded row carries the count it stood for. "Jane was
refused once" and "Jane was refused four hundred times" are different situations, and the first
reads as a misclick.

`role.access_would_deny` (observe/navigation) and `role.access_denied` (enforce) are **separate
actions with separate coalescing windows**. Sharing one window would let a suppressed observation
swallow the first genuine 403 after an operator advances a rung — the single most important row in
the rollout, lost to a counter that was already warm.

## Consequences

- **Per-request cost from `observe` upward.** The gate resolves the caller's role on every mapped
  request: one settings read plus one role read, with deliberately **no cache** — PRD §9 requires a
  changed role to take effect on the next request, and any TTL is a window in which a revoked
  permission still works. `off` returns before touching the store. Whether that cost is acceptable
  under real load is now measurable rather than theoretical: `observe` pays it without changing
  anybody's access, which is the point of running it first.
- **The preflight report is linear in headcount.** Read it before advancing a rung; do not put it
  on a dashboard.
- **Denial telemetry is per-replica.** The window is in-process, so N replicas record up to N
  first-denials for one event. A shared counter would be another write on the path we are keeping
  cheap. N rows is legible; ten thousand is not.
- **Steps 4 and 5 of PRD §15 are deliberately not done.** "Default on for new tenants" and
  "retire broad admin/user authorization" both depend on observation data that does not exist yet,
  and step 5 in particular means changing what `ACP_OPEN_ACCESS` does — a much larger change that
  should follow evidence rather than precede it.

## References

- `docs/runbooks/workspace-rbac-rollout.md` — the operator procedure
- `api/workspace_rollout.py`, `api/workspace_preflight.py`, `api/workspace_capability_map.py`
- `tests/test_staged_rollout.py`, `tests/test_rollout_preflight.py`,
  `tests/test_no_owner_lockout_paths.py`
- ADR 0047 (ACR workspace data model) — the boundary this one must not absorb
