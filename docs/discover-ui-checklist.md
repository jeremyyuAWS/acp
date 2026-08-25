# Discovery UI Checklist

Tracks the 15-item improvement list against `DiscoverRunProgress.jsx`.
Status updated 2026-08-25. Frontend component: `frontend/src/DiscoverRunProgress.jsx`.

## Progress payload schema

All phase events share a common versioned envelope. `schema_version` lets the frontend
detect old scanners and degrade gracefully. Counters are cumulative (not per-event deltas) so
reconnects get the full picture from the latest payload.

```json
{
  "schema_version": 2,
  "phase": "reading",
  "files_found": 24,
  "folders_found": 6,
  "metadata_complete": 22,
  "metadata_incomplete": 2,
  "exc_inaccessible_folder": 1,
  "exc_inaccessible_file": 0,
  "exc_metadata_failure": 0,
  "exc_missing_optional": 1,
  "exc_missing_required": 0,
  "exc_deleted_during_scan": 0,
  "rules_enabled": 5,
  "files_evaluated": 18,
  "lifecycle_matches": 4,
  "save_new": null,
  "save_updated": null,
  "save_unchanged": null,
  "save_failed": null
}
```

Fields present in earlier schema versions are backwards-compatible; absent fields default to
`null` and the frontend omits the KPI rather than showing 0.

## Classification reconciliation constraint

The five doc-class buckets must sum to files_found:

```
assessable + metadata-only + unsupported + eligibility-unknown + excluded-by-policy = files_found
```

Lifecycle status is a separate dimension — a file can be assessable by type while also being
excluded from Assessment by a lifecycle rule. Do NOT conflate the two.

## Done

- [x] **#1 KPIs for completed steps** — Connected shows `1 source` / `N sources`; Listing shows
  `N files · M folders` (or `N files found` when folder count is unavailable); Metadata shows
  `N complete · M incomplete`; Classification shows `N assessable · M unsupported`; Lifecycle
  shows `N matched · M unchanged`. (Saving step KPI added in #3.)

- [x] **#4 Clear units** — Listing KPI now shows `N files · M folders` when the scanner emits
  `folders_found` (folder-scoped Drive scans). Falls back to `N files found` for whole-Drive
  scans (where folder count is not tracked). Backend emits `folders_found: scope.get("folders_walked")`
  in the `discovering` phase progress event.

- [x] **#8 Skipped-step treatment** — When no lifecycle rules are enabled, the Lifecycle KPI reads
  `— No enabled rules` instead of `0 matched · N unchanged`. PR #782.

- [x] **#9 Completion summary** — `done` phase renders a summary card with total files discovered,
  lifecycle matches, assessable/unsupported breakdown, and elapsed time.

- [x] **#10 Explicit assessment boundary** — Summary footer includes
  `No documents were assessed or changed.` and a `Continue to Assessment →` button (via
  `onContinue` prop).

- [x] **#11 Review-inventory action** — `Review inventory` button in the completion summary (via
  `onReview` prop).

- [x] **#12 Reconciliation** — Classification totals (assessable + unsupported) are shown in the
  completion summary so they can be reconciled against total files discovered.

- [x] **#13 Stop-state feedback** — Stop button goes `disabled` and shows `Stopping…` after click.
  A contextual hint below the checklist explains what the active step will do when stopped
  (e.g. "Stops at the next folder — files listed so far will be kept."). PR #784.

- [x] **#14 Slow/stalled state** — After 90 s with no files found during listing:
  `This source contains many folders — discovery is still active.`
  After 30 s in the `analysing` phase: `Lifecycle evaluation is taking longer than usual.`
  PR #782 + PR #784.

- [x] **#15 Accessible status** — Active step has `aria-current="step"`. Status icons carry
  `aria-label` ("Completed", "In progress", "Not started"). A `role="status" aria-live="polite"`
  region announces phase transitions without repeating per-tick KPI counts (which are
  `aria-hidden`).

- [x] **#3 Saving-inventory result** — After the `saving` step completes, the Saved inventory
  step shows `N new · M updated` (and `P failed` if any). Only non-zero counts are shown.
  `save_unchanged` is emitted as 0 — the upsert pattern cannot distinguish an update that changed
  values from one that did not without a per-column comparison; updated + unchanged collapse into
  `save_updated` at the store layer.
  Implementation: `store.add_inventory` returns `{new, updated, unchanged, failed}` using a
  before/after count query; `persist_discovery_inventory` in handlers.py captures and returns it;
  `routes/scans.py work()` emits `save_new/updated/unchanged/failed` plus `schema_version: 2`
  in the `phase: "done"` update. Frontend degrades gracefully when fields are absent (old backends).

- [x] **#5 Metadata exceptions** — Surface inaccessible files/folders and metadata-read failures
  encountered during the `reading` phase. Six distinct categories:
  - `exc_inaccessible_folder` — permission denied on a folder during listing
  - `exc_inaccessible_file` — permission denied on a file during metadata read
  - `exc_metadata_failure` — API / network error reading file metadata
  - `exc_missing_optional` — optional metadata absent (owner, modified date)
  - `exc_missing_required` — metadata required for classification is absent
  - `exc_deleted_during_scan` — item existed at listing time but gone by reading time
  Live note shown during `reading` phase when any counters are non-zero. Exception summary
  included in completion card. Metadata step KPI shows exception breakdown when step is done.
  Backend: scanner.py wraps `_download()` in try/except classifying failures; emits
  `schema_version: 2` on discovering and reading events.

- [x] **#2 + #7 Lifecycle activity detail** — Lifecycle step KPI (when done) now shows
  `N rules · M matched` (or `— No enabled rules` when `rules_enabled === 0`) sourced from
  the `done` progress payload rather than derived from `inv` rows. Falls back to the
  `inv`-derived `N matched · M unchanged` display for old backends that don't emit the new fields.
  Completion summary footer uses `lifecycle_matches` from the payload when available.
  Backend: `_evaluate_discover_lifecycle_rules` returns
  `{"rules_enabled": N, "files_evaluated": M, "lifecycle_matches": K}`;
  `persist_discovery_inventory` merges these into its return dict alongside save-outcome keys;
  `routes/scans.py work()` emits `rules_enabled`, `files_evaluated`, `lifecycle_matches` in the
  `phase: "done"` update (schema_version 2).

- [x] **#6 Classification breakdown** — Classifying step KPI now shows 5 non-zero buckets from
  the `done` progress payload (`assessable`, `metadata-only`, `unsupported`, `eligibility-unknown`,
  `excluded`). Completion summary shows the same 5-bucket row. Falls back to inv-derived
  `N assessable · M unsupported` for old backends that don't emit the new fields.
  Backend: `_count_inventory_classes(scan_id)` iterates `scan_inventory` and counts using the
  `_ASSESSABLE_DOC_CLASSES` / `_METADATA_ONLY_DOC_CLASSES` frozensets; `persist_discovery_inventory`
  merges these into its return dict; `routes/scans.py work()` emits all 5 fields in the
  `phase: "done"` update (schema_version 2). Field names align with PRD §7: `assessable`,
  `metadata_only`, `unsupported`, `eligibility_unknown`, `excluded`.

## Remaining

_All 15 items complete._
