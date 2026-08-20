# ADR 0038 — Pausable / resumable scans

Status: **Proposed** (design only — no code in this PR)
Date: 2026-08-19
Related: ADR 0013 (finalize by count, not a running counter), ADR 0037 (staged bounded pipeline),
the existing cancel path (`store.cancel_scan`, `POST /scans/{sid}/cancel`) and the cooperative
download-halt marker (`handlers._stop_scan_downloads` / `drive_download_halted` / `clear_drive_stop`).

## Context

The Track A scan-experience redesign (#452–#463) added an outcome-oriented progress panel, and its
spec called for a **Pause / Resume** control on a running scan. That control was **deliberately not
shipped**: there is no backend pause/resume, and a button that does not actually pause is worse than
no button — it tells an operator the estate stopped being read when it did not. This ADR designs the
backend so the control can be built honestly.

A pause is worth having for a hospital estate: a reviewer may need to stop a large run mid-flight to
let an interactive job through, to spare a rate-limited Drive credential, or simply to come back to
it after a meeting — **without losing the files already assessed** and **without re-reading the whole
estate** on resume.

### What already exists (and what pause must reuse, not reinvent)

- **Cancel** — `POST /scans/{sid}/cancel` → `store.cancel_scan(sid, owner)` sets
  `scan_runs.status='cancelled'`, stamps `completed_at`, and keeps every `file_record` already
  written. Owner-scoped. It is terminal: a cancelled run is not meant to continue.
- **Cooperative halt marker** — `_stop_scan_downloads(scan_id, reason)` writes a per-scan setting
  (`_DRIVE_STOP_KEY % scan_id`); the per-file path checks `drive_download_halted(scan_id)` and, when
  set, **still persists a row for every remaining file** (skip-with-a-row) so the run finalizes
  instead of hanging at N/M. `clear_drive_stop` is called from `_enqueue_analysis`, the single choke
  point both the immediate-scan and the deferred-Assess paths pass through.
- **Finalize by count (ADR 0013)** — a run is done when `count_files_done(scan_id)` (rows in
  `file_records`) reaches `scan_runs.files`. There is no running "are we finished" flag to corrupt;
  finished is a *count over persisted rows*.
- **Per-file idempotent persistence** — each file's `_analyse_and_persist_one` upserts one row, and
  incremental scanning already knows how to skip a file whose result is current.

Pause is therefore **not** "cancel", and **not** "halt-and-finalize". It is a third thing: *stop
dispatching new work, keep the run open, and be able to dispatch the remainder later.*

## Decision

Add a **`paused`** run state and a **cooperative pause marker**, mirroring the download-halt seam but
with the opposite finalize semantics: a paused file gets **no row yet**, so the run stays legitimately
unfinalized until it is resumed or cancelled.

### 1. State + marker

- New `scan_runs.status` value **`paused`** (alongside `running` / `completed` / `cancelled` /
  `interrupted`). Additive; every place that switches on status must learn it (see §5).
- New per-scan marker `_PAUSE_KEY % scan_id` (a setting, same mechanism as `_DRIVE_STOP_KEY`), so the
  signal is readable by any worker in either the in-process pool or the standalone worker tier
  without shared memory. `scan_paused(scan_id) -> bool` reads it.

### 2. Pause (`POST /scans/{sid}/pause`)

Owner-scoped exactly like cancel. On pause:
1. `store.pause_scan(sid, owner)` — CAS `status: running → paused`; refuse (return false) if the run
   is not the caller's, not found, or not currently `running` (you cannot pause a finished or
   cancelled run). Do **not** stamp `completed_at`.
2. Set `_PAUSE_KEY % scan_id`.

The bounded pool's **per-file checkpoint** — the same point that already consults
`drive_download_halted` — also consults `scan_paused`:
- a file **already in flight** runs to completion and persists its row (a pause is cooperative, never
  a mid-file kill — a half-analysed file must not leave a partial row);
- **no new file is dispatched** while the marker is set.

Because remaining files get **no row**, `count_files_done` stays below `scan_runs.files` and the
finalize machinery correctly does **not** close the run. This is the one deliberate difference from
`_stop_scan_downloads`, which *wants* finalization and therefore writes skip rows.

### 3. Resume (`POST /scans/{sid}/resume`)

1. `store.resume_scan(sid, owner)` — CAS `status: paused → running`.
2. Clear `_PAUSE_KEY % scan_id`.
3. Re-dispatch **only the undone files** through `_enqueue_analysis` (the existing choke point, which
   already calls `clear_drive_stop`). "Undone" = the run's in-scope files with no current
   `file_record`. Idempotent upsert makes a redundant dispatch harmless, so the query may be
   conservative.

No file is re-read or re-analysed that already has a current row — resume is "scan the remainder",
which is why per-file persistence is a precondition, not an afterthought.

### 4. Interaction with the lost-worker sweeper

The sweeper marks a `running` scan **`interrupted`** when its worker tier stops beating. A `paused`
scan has, by design, no active workers — so the sweeper **must exclude `paused`** from its candidate
query, or every pause would be misread as a crash within one sweep interval. This is the subtlest
correctness point in the change and needs an explicit test (see §6).

### 5. Surfaces that must learn `paused`

- `/scans` listing and `/scans/{sid}` — report `paused` so the UI can show Resume instead of a
  spinner (the whole point of the feature).
- Progress/aggregate readers (`_fill_run_aggregate`) — a paused run's live tallies are valid and
  should render; nothing changes except that `done < total` is now an expected steady state.
- The scan-start guard — a `paused` run is not `running`; ensure "you already have a scan running"
  logic does not either block a new scan on a paused one or treat pause as free capacity incorrectly
  (product call: recommend a paused run still counts against the one-active-scan limit, since Resume
  expects its slot back).

### 6. Tests (ship with the implementation, not after)

- pause on a `running` scan flips to `paused`, sets the marker, and does **not** stamp `completed_at`;
- pause on a `completed`/`cancelled`/other-owner scan is refused;
- a paused run does **not** finalize even when the pool drains (count < files, status stays `paused`);
- the lost-worker sweeper leaves a `paused` run alone (the §4 regression guard);
- resume re-dispatches exactly the undone files and skips those with a current row (idempotency);
- resume on a non-paused run is refused;
- full cycle: run → pause → resume → completes, with the analysed-so-far rows intact across the pause.

## Consequences

- **Honest UI.** The Pause control becomes real: the estate genuinely stops being read on pause and
  no completed work is lost. The deferred Track A polish item can ship on top of this with no fakery.
- **Small, seam-aligned change.** It reuses the marker mechanism, the `_enqueue_analysis` choke
  point, and the count-based finalize — no new pipeline, no new persistence model.
- **One real hazard, called out:** the sweeper/finalize interaction (§4) is where a naive
  implementation silently turns pauses into `interrupted`. The test in §6 exists to catch exactly
  that.
- **Scope note:** this touches the scan pipeline (`handlers.py` / `store.py` / `routes/scans.py`),
  which is an active thread (#384). This ADR is **design only** so it can land without colliding;
  implementation should be sequenced against that thread, not raced with it.

## Alternatives considered

- **Cancel + new scan.** Loses the "resume the remainder" property — a 30k-file estate would be
  re-read from zero. Rejected: the whole value is not re-reading.
- **Hard-kill in-flight files on pause.** Would leave partial/again-needed rows and complicate the
  idempotency story. Rejected: cooperative checkpoint is simpler and already the pattern here.
- **A dedicated `paused_files` table.** Unnecessary — "undone" is derivable from `file_records` vs.
  the run's in-scope set, the same truth finalize already uses.
