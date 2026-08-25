# Discovery UI Checklist

Tracks the 15-item improvement list against `DiscoverRunProgress.jsx`.
Status updated 2026-08-25. Frontend component: `frontend/src/DiscoverRunProgress.jsx`.

## Done

- [x] **#1 KPIs for completed steps** — Connected shows `1 source` / `N sources`; Listing shows
  `N files · M folders` (or `N files found` when folder count is unavailable); Metadata shows
  `N complete · M incomplete`; Classification shows `N assessable · M unsupported`; Lifecycle
  shows `N matched · M unchanged`. (Saving step has no KPI yet — see #3.)

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

## Remaining (all blocked on backend data)

- [ ] **#2 Lifecycle-rule activity detail** — During the `analysing` phase, show the number of
  enabled rules, per-file evaluation progress, and match candidates (archive / delete / tag).
  Requires the scanner to emit rule counts and per-file progress in the `progress` payload.

- [ ] **#3 Saving-inventory result** — After `saving` step completes, show
  `N new · M updated · K unchanged` (and failed records if any).
  Requires the scanner to return save-step outcomes in the progress payload.

- [x] **#4 Clear units** — Listing KPI now shows `N files · M folders` when the scanner emits
  `folders_found` (folder-scoped Drive scans). Falls back to `N files found` for whole-Drive
  scans (where folder count is not tracked). Backend emits `folders_found: scope.get("folders_walked")`
  in the `discovering` phase progress event.

- [ ] **#5 Metadata exceptions** — Surface inaccessible files/folders and metadata-read failures
  encountered during the `reading` phase.
  Requires the scanner to collect and emit exception counts in the progress payload.

- [ ] **#6 Classification breakdown** — Expand beyond `assessable / unsupported` to show
  `metadata-only`, `eligibility-unknown`, and `excluded-by-policy` classes.
  Requires the scanner to emit per-class counts rather than a binary assessable flag.

- [ ] **#7 Current activity detail** — During the `analysing` phase, show a live counter such as
  `Applying 5 rules · 18 of 24 files evaluated`.
  Requires the scanner to emit current-rule and evaluated-count fields in the progress payload.
