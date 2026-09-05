# Runbook — turning on workspace roles

**What this changes:** who can see which tabs, and who can perform which actions. Today every
signed-in user can do everything (`ACP_OPEN_ACCESS` is on and `core.is_admin()` returns true for
all of them). After this rollout, a user's workspace role decides.

**What it does not change:** who can sign in (the allowlist), and who can approve or publish an
Accessibility Conformance Report (ACR reviewer roles, ADR 0047). Those are separate boundaries and
nothing here touches them.

**Time:** each stage is a deployment plus a soak. Plan days, not minutes — the soak is the part
that has value.

---

## Before you start

Set the owner. `ACP_OWNER_EMAIL` is the anti-lockout carve-out: that identity is resolved before
any role lookup, so no deletion, bad row or mistaken assignment can lock them out.

**Without it there is no carve-out.** The owner-only routes still refuse a non-owner, but a direct
write to the store bypasses that and there is nothing to fall back on. `ACP_OWNER_EMAIL` unset is
the default in development, which is where most of this gets exercised — so check it in the
environment you are actually rolling out.

```
GET /admin/workspace-roles/preflight        # owner-only; read it, don't poll it
```

---

## Stage 0 → 1: seed the roles

```
POST /admin/workspace-roles/bootstrap        {}                 # preview — the default
POST /admin/workspace-roles/bootstrap        {"apply": true}    # write
```

Dry by default. Read the generated assignments — who becomes Platform Admin, who becomes
Compliance Manager — before they mean anything. Safe to re-run: existing roles are not overwritten
and already-assigned people are not reassigned, so a second run will not undo an administrator's
tightening.

`{"apply": "false"}` does **not** write. Only a JSON `true` does.

Nothing is enforced yet at any point in this stage.

---

## Stage 1: `observe`

```
ACP_WORKSPACE_RBAC_MODE=observe
```

Roles are resolved on every mapped request and the difference is recorded. **Nobody's access
changes.** Every request that enforcement would have refused succeeds, and writes one
`role.access_would_deny` row (coalesced: first of a kind immediately, repeats suppressed for two
minutes, then one row carrying the count).

**Soak until the workspace has actually been used.** A week of ordinary work beats a day of
clicking around, because the point is to catch the routes real people use that the capability map
gets wrong.

Then read the report:

```
GET /admin/workspace-roles/preflight
→ observed.counts["role.access_would_deny"]
→ observed.samples[]
```

**Every would-deny is a request that will start returning 403.** Decide for each: is the role
wrong (fix the assignment), or is the capability map wrong (fix the map and ship it)? Zero
would-denies after real traffic is a good result. Zero would-denies after *no* traffic tells you
nothing, and the report says so rather than implying the reassuring reading.

---

## Stage 2: `navigation`

```
ACP_WORKSPACE_RBAC_MODE=navigation
```

The SPA now hides tabs a role does not grant. **The server still allows the calls** — a direct
URL, a bookmarked page or a stale open tab still works. This is not a security control; it is the
step that stops users being invited to click things that are about to start failing.

Recording continues, and what it catches now is exactly what the hiding did *not* cover: direct
URLs, stale tabs, background polls from pages loaded before a role changed. That list is the last
thing worth reading before the server starts refusing.

Users see the change on their next page load — no sign-out required.

---

## Stage 3: `enforce`

```
ACP_WORKSPACE_RBAC_MODE=enforce
```

The server refuses. Refusals are `403` with `{"capability_denied": true, "required": [...]}` and a
message naming the role, so a user can tell an administrator what they need.

Run the preflight one last time and clear every blocker first.

---

## Rolling back

**Set the mode down a rung and redeploy.** It takes effect immediately; there is no state to
unwind, no migration to reverse, and role assignments are untouched.

```
ACP_WORKSPACE_RBAC_MODE=observe        # from enforce, mid-incident
```

`ACP_WORKSPACE_RBAC_MODE` beats `ACP_WORKSPACE_RBAC_ENABLED`, so a rollback works even if the old
variable is still set — you do not have to find and unset two things under pressure. Tidy up the
stale one afterwards; the preflight report warns while both are present.

---

## Preflight findings

**Blockers** make the next rung unsafe regardless of intent. **Warnings** are consequences somebody
may well have intended — narrowing a role is the entire point of the feature, so it does not block.

| Code | Severity | What to do |
|---|---|---|
| `mode_unreadable` | blocker | `ACP_WORKSPACE_RBAC_MODE` is misspelled. ACP is running at the rung the report names, **not** the one you set. Fix the variable. |
| `roles_not_seeded` | blocker | Run the bootstrap with `{"apply": true}`. Every unassigned person resolves through the default role; without it, advancing refuses everybody at once. |
| `default_role_narrowed` | blocker | Somebody edited Platform User below its definition. Every unassigned person depends on it. Restore it or re-run the bootstrap. |
| `routes_unmapped` | blocker | A running route has no capability decision, so it is open to every role. Map it in `api/workspace_capability_map.py` and ship. |
| `capabilities_unknown` | blocker | The map names a capability the catalog does not define. No role can hold it, so those routes refuse everybody. |
| `assigned_people_lose_access` | warning | An administrator narrowed these people. Confirm it was meant. |
| `unassigned_people_lose_access` | warning | They resolve through Platform User and lose the seven administrative grants `OPEN_ACCESS` hands everybody today. Expected — read it once. |
| `legacy_flag_shadowed` | warning | Both variables set. Remove `ACP_WORKSPACE_RBAC_ENABLED`. |
| `no_observations` | warning | Nothing was recorded. Either observe found nothing or it never ran under real traffic — the report cannot tell which, and neither can anyone else without checking. |
| `observed_would_deny` | warning | **Read these.** Each is a real user's real request that is about to start failing. |

---

## If somebody is locked out

1. **The owner never can be**, provided `ACP_OWNER_EMAIL` is set — the carve-out returns before
   any lookup. If the owner appears locked out, that variable is the first thing to check.
2. **Anyone else:** the owner assigns them a role
   (`PUT /admin/people/{email}/role`), effective on that user's next request — no cache, no TTL,
   no sign-out.
3. **Everyone at once** means the default role is missing or narrowed. Drop to `observe`, then
   re-run the bootstrap.

## Audit trail

Everything lands in the same `decision_log` the rest of the product uses:

| Action | Meaning |
|---|---|
| `role.migration` | the bootstrap ran |
| `role.assigned` | somebody was given a role |
| `role.unassigned` | somebody's role was **removed** — a revocation, kept separate so it is not missed among grants |
| `role.access_would_deny` | observe/navigation: enforcement would have refused this, and it was allowed |
| `role.access_denied` | enforce: actually refused |

## References

- ADR 0049 — the design and why each choice was made
- `api/workspace_rollout.py` — the ladder
- `api/workspace_preflight.py` — the report
