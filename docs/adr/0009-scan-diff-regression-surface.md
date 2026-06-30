# ADR 0009 — Scan-diff (regression) read surface

Status: **Accepted** · Date: 2026-06-30 · Builds on [ADR 0007](0007-fan-out-scan-pipeline.md)

## Context
The Monitor tab promises "continuous compliance," but real drift/regression detection was
previously simulated (canned "score dropped 100→82" events). We now keep a full history of
scans (`scan_runs` + per-file `file_records` + per-rule `scan_rule_traces`). That history is
enough to compute **real** drift by *diffing two scans* — no Drive/SharePoint
change-notification infrastructure (the heavy Option-C webhook lifecycle) required.

We need a read surface that answers: *between scan A and scan B, which documents got worse,
which improved, what's new/gone, and — for each regression — exactly which WCAG criterion
flipped from pass to fail.*

## Decision
Add one **read-only, owner-scoped** endpoint:

```
GET /scans/{id}/diff?vs={prevId}
```

- `{id}` = the later scan, `vs` = the baseline. If `vs` is omitted, default to the caller's
  immediately-prior scan (second entry of their `list_scans`).
- **Owner-scoped**: both scans must belong to the caller (`get_scan(..., owner)` gate on each);
  404 otherwise — same isolation contract as every other scan endpoint.
- Backed by a pure store method `get_scan_diff(cur_id, prev_id, owner)`:
  1. Load `file_records` for both scans, key by `file`, compute per-file `{prev, cur, delta}`.
  2. Classify: **regressed** (delta < 0), **improved** (delta > 0), **new** (only in cur),
     **removed** (only in prev).
  3. For regressed files only, diff `scan_rule_traces` to list the criteria that flipped
     **PASS → FAIL** (`{sc, name}`) — the "what broke" detail.
- Returns a summary (`{regressed, improved, new, removed}` counts + the two scan timestamps)
  and the ranked lists. Files are matched by **filename** (a rename reads as new + removed,
  which the UI labels honestly).

## Why a diff endpoint (not client-side)
A client diff would fetch two full file lists (heavy at 10k–250k files) and can't see
`scan_rule_traces` without extra round-trips. The server already holds both; one scoped query
keeps payloads small and scales. It also becomes the shared input for the **AI Compliance
Digest** (ADR-to-follow) so the model grounds on the same real deltas.

## Consequences
- **Pure read, no schema change** — diffs existing tables; nothing new to migrate.
- Enables the **Regression Radar** UI and feeds the digest — real drift at ~Medium effort
  instead of the Large continuous-monitoring webhook build.
- Cost is bounded: two indexed reads by `scan_id` + an in-memory join; rule-flip detail is
  computed only for the (small) regressed set.

## Non-goals
- Push/instant change detection (that's the webhook infra — explicitly deferred).
- Cross-user or cross-estate comparison (owner-scoped, same-source only).
