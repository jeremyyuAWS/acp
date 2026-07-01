# ADR 0011 — Incremental scans: skip unchanged files across scan runs

Status: **Accepted** · Date: 2026-06-30 · Accepted: 2026-07-01 · Builds on [ADR 0007](0007-fan-out-scan-pipeline.md),
extends the checksum dedup shipped alongside this ADR (`file_records.checksum`,
`store.find_by_checksum`)

## Context
Every scan — even a re-scan of an estate where almost nothing changed — re-downloads,
re-analyses (engine + PII extraction), and re-persists **every** file. For a 10K–100K file
estate (ADR 0007/0008's stated scale target) run on a recurring schedule, that's full-cost
work for documents that are byte-identical to what was already scored last time.

We just shipped the smaller, narrower version of this: **within one scan**, two files sharing
a Drive `md5Checksum` skip redundant analysis (`find_by_checksum`, scoped to one `scan_id`).
This ADR is the larger feature it deliberately deferred: reuse analysis **across scan runs**,
not just within one.

## Decision
Add a cross-scan fingerprint lookup, gated on the **same owner** and the **same rubric version**
(the correctness-critical constraint — see below), keyed by Drive's stable `id` + `md5Checksum`:

1. **`store.find_prior_analysis(owner, drive_file_id, checksum, rubric_hash)`** — same return
   shape as `find_by_checksum`, but queries the owner's most recent `file_records` row (any
   `scan_id`, joined through `scan_runs.owner_email`) matching `drive_file_id` AND `checksum`
   AND `scan_runs.rubric_hash = rubric_hash`. The rubric-hash match is mandatory, not optional:
   byte-identical bytes can score differently once the rubric's rule set changes, so a stale
   analysis under an old rubric is not valid evidence under a new one. `acp_stamped` lets a
   user manually re-trigger a single file's analysis without invalidating everything else.
2. **Wired into the same chokepoint as checksum dedup** — `_analyse_and_persist_one` tries
   `find_by_checksum` (this scan) first, then `find_prior_analysis` (history) before falling
   back to a real download + engine run. Both copy forward the same way (new file name/
   `drive_file_id`, prior `engine`/`status`/`score`/`issues`/`pii`).
3. **Drive id is the match key, not filename** — survives a rename (the `_dedupe_names`
   suffix problem checksum dedup already had to solve doesn't recur here, since `drive_file_id`
   is stable Drive-side identity, immune to the same-name-different-folder collision).
4. **Opt-in toggle, default ON**: "Incremental scan" alongside the existing Skip Remediated/ /
   PII scan / Durable scan switches (`Integrations.jsx`). An explicit "Fresh scan" override
   (toggle off) forces full re-analysis of every file — for after a manual rubric edit outside
   the normal version bump, or when a user just doesn't trust the cache.
5. **`modifiedTime` is NOT part of the match key.** `md5Checksum` already proves byte-identity
   more strongly than a timestamp (Drive doesn't always bump `modifiedTime` on a no-op
   save-as), so checksum alone is the correctness boundary; `modifiedTime` would only add a
   false-negative risk (skipping work that should re-run) for no real gain.

## Why this is bigger than checksum dedup (and earns its own ADR)
- **Cross-scan reuse touches correctness in a way within-scan dedup didn't.** Within one scan,
  the rubric is necessarily the same scan's rubric — no version-drift risk. Across scans, the
  rubric *can* have changed between them, so this ADR's core decision (gate on `rubric_hash`)
  is the load-bearing piece that didn't exist in the smaller feature.
- **Changes the default scan-cost model**, not just a dedup optimization within one run — a
  scheduled nightly re-scan of a stable estate goes from "full estate cost every time" to
  "cost proportional to what actually changed." That's a behavior change worth a recorded
  decision, not a quiet implementation detail.
- **Interacts with PII findings retention** — a file whose analysis is copied forward also
  copies forward its PII findings (masked samples). Worth being explicit that this is
  intentional (the bytes didn't change, so neither did what's inside them), not an oversight.

## Consequences
- **No new schema** — reuses `file_records.checksum` (already added) and the existing
  `scan_runs.rubric_hash`/`owner_email` columns. Pure query-layer addition.
- **Scan cost drops roughly proportional to estate stability** — the common case (a recurring
  scan of a mostly-static document library) goes from O(all files) to O(changed files) for the
  expensive part (download + engine + PII), while still producing a complete `file_records`
  row set (every file gets persisted, copied-forward or freshly analysed) so all the existing
  read paths (Dashboard, diff, reports) are unaffected.
- **Trace volume**: a copied-forward file should still get its own Discover/Assess Langfuse
  spans (for inventory/audit completeness), marked with `duplicate_of` / a parallel
  `reused_from_scan` marker — mirrors the `duplicate_of` field checksum dedup already emits.

## Non-goals
- Detecting changes server-side without a scan trigger (push notifications / Drive webhooks)
  — still explicitly deferred, same as ADR 0009's non-goal.
- Incremental remediation (skipping re-remediation of unchanged-but-already-remediated files)
  — a related but separate decision; `acp_stamped` already gives the UI a signal for this
  today without needing the fingerprint cache.
- Retroactively backfilling fingerprints for scans that predate this ADR — `checksum` is NULL
  on old rows, so they simply never match and always re-analyse on the next scan (safe default).

## Decisions on review (2026-07-01)
- **Fresh scan is schedulable, as a trust-but-verify backstop.** Cheap insurance against an
  undetected cache-correctness bug: a recurring scan can force a full re-analysis on a cadence
  (e.g. monthly) independent of rubric changes, not just on manual override.
- **Copying forward PII findings gets its own `decision_log` entry.** PII detection results
  carry more sensitivity than a WCAG score, so silently copying them forward without an audit
  trail entry isn't acceptable — an explicit `pii.copied_forward` decision is logged alongside
  the existing `duplicate_of`/`reused_from_scan` markers.
