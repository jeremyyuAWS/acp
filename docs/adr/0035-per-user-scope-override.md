# ADR 0035 — Per-user scan-scope override (owner default + per-user override)

**Status:** Proposed. Stage 1 (the storage + resolution primitive) shipped with this ADR; stage 2
(wiring into the scope hot path) is a separate, reviewed change.
**Date:** 2026-08-18
**Related:** `api/store.py` (`set_user_setting` / `get_user_setting` / `clear_user_setting` /
`resolve_setting`), `api/assessment_policy.py` (`active_scope`), `api/routes/system.py`
(`/settings`), ADR 0026 (status contract), backlog R7 / Phase 3c.

## Context

Today the scan scope — which WCAG criteria, on which formats, a scan assesses — is a **single global
setting** (`app_settings["scan_scope"]`), edited by the owner through the admin-gated `PUT /settings`
and frozen per scan into `scan_runs.scope`. There is no way for one user to run their own scans under
a different scope without changing it for everyone.

R7 (Phase 3c) asks for a two-level model: the **owner sets a default**, and an individual **user may
override it for their own scans**. This ADR settles the governance — precedence, the freeze
interaction, and what an override is allowed to change — before the load-bearing scope code is touched.

## Decision

**Precedence — highest wins:** per-user override → owner (global) default → no restriction. This is
exactly what `store.resolve_setting(key, user)` implements (stage 1, shipped): the user's override if
present, else the global setting, else the caller's default. An override that is present but **empty**
is a real value (a user opting into "no restriction") and is distinct from having no override.

**Freeze, not live-read.** The effective per-user scope is resolved **once, at scan start**, and
frozen into `scan_runs.scope` — never re-read live. This is the same invariant the Phase 3a fix
established (`store.get_scan_scope` reads the scan's own frozen scope, not the live global), and the
reason it exists: with a live read, changing the scope — now, changing *a user's* override — after a
scan would silently rewrite what an already-issued report claims to cover. Stage 2 resolves the
override at the same chokepoint the global scope is resolved (`assessment_policy.active_scope`), then
freezes; everything downstream (`_scoped_for_scoring`, the traces gate) already reads the frozen scope.

**A per-user override may only WIDEN coverage, never narrow below the owner default.** For a hospital,
the owner is the compliance authority; the owner's scope is a **mandate**, not a suggestion. A user
override that *removed* criteria could skip a check the owner required and hide findings — the one
direction that must not be silent. So the effective scope is `owner_default ∪ user_override` per
format: a user may assess *more* than the owner mandated, never less. (If an owner ever wants to let
users narrow — e.g. a permissive default and per-team focus — that is a deliberate owner policy toggle,
not the default, and out of scope here.)

**Who may set what.** The owner default stays admin-gated (`PUT /settings`, `_require_admin`). A
per-user override is set by the user themselves for themselves — a **non-admin** surface keyed to the
signed-in `user_email`, never able to write another user's override. (That route is part of stage 2;
stage 1 ships only the store primitive, which the route and the resolver will consume.)

## Staged plan

- **Stage 1 (this PR): the primitive.** `store.set_user_setting` / `get_user_setting` /
  `clear_user_setting` / `resolve_setting`, stored as namespaced `app_settings` rows
  (`user:<email>:<key>`) — no schema change, inherits the settings table's persistence and RESET
  treatment. Tested for precedence, the empty-override edge, clear/idempotence, and per-user isolation.
- **Stage 2 (separate, reviewed): the wiring.** `active_scope(store, owner=None)` resolves the owner
  default and, when an owner override exists, computes the widen-only union and returns it; the scan
  freezes it as today. Touches `assessment_policy.py` (a `RULE_PATHS` file, needing a `Matrix-Note`)
  and the scanner call site, plus the non-admin `/settings/mine` route and the Settings UI. It changes
  the score-bearing hot path, so it lands on its own with the four backend guards run and, ideally, a
  fixture that proves a user override changes only that user's scored scope.

## Alternatives considered

- **A new `user_settings` table.** Rejected for stage 1 — a namespaced key in `app_settings` needs no
  migration and no new RESET wiring, and the value is always a small scalar. Revisit only if per-user
  config grows many keys with their own lifecycle.
- **Resolve the override live at scan time.** Rejected — it breaks the frozen-scope invariant above;
  a report must describe the scope it actually ran under, not whatever the user set since.
- **Let a user override narrow the owner's scope.** Rejected as the default — it lets a user silently
  skip a compliance-mandated criterion. Widen-only keeps the owner's mandate a floor.

## Consequences

- Stage 1 adds a tested, reusable owner-default/per-user-override primitive with no behaviour change:
  nothing resolves through it yet, so no scan is affected until stage 2 wires it in.
- Stage 2 is the point of risk (hot path, `RULE_PATHS`, frozen-scope invariant) and is deliberately
  separated so it can be reviewed and fixture-verified on its own rather than riding in on a primitive.
- The widen-only rule means a per-user override can never *reduce* a hospital's assessed criteria — the
  safe default for PHI compliance.

## Effort estimate (LOE)

Stage 1: done. Stage 2: ~1–2 days — the `active_scope` union + freeze, the non-admin route, a Settings
UI affordance, the `Matrix-Note`, and a fixture proving per-user scope isolation end to end.

## Status / next step

Stage 1 merged. Stage 2 is a committed follow-up; it should not land as an autonomous change — it edits
the score-bearing scope hot path and wants the full backend guard suite plus a dedicated fixture.
