# ADR 0052 — Durable structured remediation progress, and what it lets the stream stop lying about

**Status:** Accepted
**Date:** 2026-09-05
**Related:** ADR 0042 (durable scan lifecycle event log), ADR 0051 (`Last-Event-ID` resume for the
remediation stream) — this closes both of 0051's "Open" items. Code: `api/store.py`
(`append_scan_event`, `list_scan_events`, `prune_scan_events`, `latest_material_event_at`,
`remediation_run_facts`, `remediation_filename_privacy`), `api/remediation_run.py`
(`document_ref`, `_applicable_states`, `build_snapshot`), `api/routes/scans.py`
(`_project_event`, `_stream_is_finished`), `api/sweeper.py`,
`frontend/src/remediationEventFeed.js`.
PRD: `docs/prd-remediation-realtime-ops-panel.md` §8, §6D, §21, §22.

---

## Context

ADR 0051 made the remediation stream resumable and left three things undone, two of them written
into its own **Open** section:

> - **Pruning**, per §22's 24h/10,000 decision. The gap check lands here; the deletion does not.
> - **Whether the stream should stay open past `in_flight == 0`.**

The third was not open, because nobody had noticed it. `remediation_run_facts` computed the run's
`latest_progress_at` as `max(jobs.updated_at)`, and `store.touch_job` — the lease heartbeat —
writes `updated_at` on every beat. So the run's progress clock was refreshed every few seconds by
a worker doing nothing but staying alive.

That is not a cosmetic mislabel. The stall predicate in `remediation_run._applicable_states` is
`progress_age_s > stall_after_s`, so while a heartbeat kept the age near zero the predicate was
not merely wrong, it was **unreachable**: a worker wedged inside one document could never produce
a stalled run, and the panel went on reporting progress on the strength of a thread breathing.
`STALL_AFTER_S` has been in the code, tested, since Phase 1, describing a state the code could
not enter.

Two further gaps were structural rather than behavioural. Remediation events carried the filename
inside their JSON `detail` and carried no correlation at all, which made two reads impossible:

* **one document's own history**, which PRD §6D's live workstream is entirely about — several
  documents remediate at once and each needs an ordered account separable from the others;
* **withholding a name**, which PRD §22 requires under some privacy policies. A value that can
  appear anywhere inside a JSON blob has to be hunted for, and the hunt is what eventually misses
  one.

## Decision

### 1. `document` and `correlation_id` become columns

`scan_events` gains both, plus `idx_scan_events_document (scan_id, document, seq)`. The filename
moves out of `detail` entirely — it is not written to both. Two copies of one fact is two places
for a suppression rule to be applied to only one of them.

`correlation_id` is the batch (stage execution). `scan_id` cannot separate two remediation runs
over one scan, and the panel is deliberately scoped to the latest batch.

Readers keep a `detail.file` fallback, because the log is durable: rows written the old way are
still replayed on every resume, and dropping the fallback would blank the names in exactly the
history a reconnecting client came back for.

### 2. Material progress and lease heartbeat are different facts, named apart

`Store.MATERIAL_SCAN_EVENT_KINDS` / `LEASE_SCAN_EVENT_KINDS`, and `is_material_event`. An unknown
kind is **not** material — treating one as progress would let any telemetry line added later
silently reset a stall clock.

`remediation_run_facts` now derives `latest_progress_at` from:

* the `updated_at` of jobs that are **not running** (a row that is not running cannot be
  heartbeating, so its stamp is a real transition), and
* the newest material event in the durable log.

and reports `latest_heartbeat_at` separately, from the `locked_at` of running jobs — which is
precisely what `touch_job` rewrites on each beat. The snapshot exposes both under `progress`.

**Unknown stays unknown.** No material evidence means `latest_progress_at` is `None`, and
`_applicable_states` cannot build the stall predicate on a `None` age — it is neither stalled nor
fresh. Falling back to the heartbeat would reintroduce the bug with an extra step; falling back
to `started_at` would report a run as freshly progressing at the moment it has produced nothing.

### 3. Stalled now also requires an unhealthy lease

PRD §22, stated exactly: "declare stalled after two further missed heartbeats **and** an expired
or unhealthy attempt lease." This clause was unreachable while a heartbeat held the age down.
With an honest progress clock it becomes load-bearing in the other direction: a genuinely slow
document — one honest attempt, a live lease, a large PDF mid-render — would otherwise be announced
as "Progress has stopped", which is the same class of false statement the panel exists to remove.

### 4. Retention: 24 hours **or** 10,000 events per run, whichever is greater

`store.prune_scan_events` deletes a row only when it is outside **both** windows, and the sweeper
runs it hourly, bounded per pass. Read the other way round — delete when outside *either* — a busy
run would lose its last hour on passing ten thousand events, and a quiet run would lose a
200-event history to nothing but the passage of a day.

This is what makes ADR 0051's `events_pruned` reconcile branch reachable. That branch was written
for a condition nothing could produce, explicitly so resume would not begin losing events silently
on the day pruning landed. The regression fixture now prunes for real rather than issuing a DELETE
that imitates it.

### 5. Filename suppression happens in one projection, on both read paths

`routes/scans.py::_project_event` is the only place an event becomes a wire payload — the SSE
stream and `GET /scans/{sid}/history` both go through it. Under a `suppressed` policy it removes
the name and keeps `document_ref`: a per-run, salted, non-reversible handle, so grouping and
ordering (what §6D actually needs the name for) keep working on a run whose names are withheld.
Salted with the scan id so one document's ref does not correlate across runs.

`remediation_filename_privacy` is the one place in this change where an unknown does **not** stay
unknown: an unreadable policy suppresses. The two answers are not symmetric — guessing `visible`
discloses a name that cannot be un-sent, while guessing `suppressed` costs a label on a card whose
document the owner can still identify by its ref.

### 6. The stream closes when the run is finished, not when the queue is empty

`_stream_is_finished` keeps the shipped `in_flight` gate as its first clause — so it can only ever
extend the stream, never shorten it — and then declines to close while the snapshot's `state` or
`also` contains `completing`, whose reason code is literally
`delivery_reconciliation_outstanding`.

It stays open for reconciliation the run performs itself, **not** for a human. `needs_attention`
waits on a review decision that may be hours away; holding a connection for that is a leak dressed
as liveness, and the client already polls there.

## Consequences

**A wedged worker is now visible.** The state it produces is `stalled` with reason
`no_progress_within_threshold`, and it can be reached — which it could not before.

**`onDone` means more than it did.** The client's `onDone` drives `finishRemediation`; it now
fires after delivery rather than during it. The fallback poll still runs after `done`, because
review decisions and evidence can outlive delivery and the reconciled snapshot, not one frame, is
the authority on terminality.

**A rolling deploy is safe on both sides.** An old replica writes NULL into both new columns; new
readers treat both as optional, and `latest_material_event_at` matches `correlation_id IS NULL`
explicitly so a run begun on an old replica is not read as having made no progress. An old replica
never selects either column. `seq` — the resume cursor — is untouched, so neither generation can
produce a cursor the other cannot honour.

**Retention makes the log lossy on purpose.** A client resuming from a cursor older than the
window gets `reconciliation-required` and a fresh snapshot, which is the contract ADR 0051 built
for exactly this.

## Alternatives considered

**Stop `touch_job` writing `updated_at`.** The narrowest possible fix, and it was rejected for
being cross-cutting: `jobs` is shared by discovery, assess and remediation, and changing what
`updated_at` means for every job type to fix a remediation snapshot is a large blast radius for a
small target. Deriving remediation's progress from remediation's own material evidence is scoped
to the surface that needs it.

**A `remediation_events` table.** Rejected for the reason `SCAN_EVENT_KINDS` already gives: two
logs anchored on one scan, with no defined interleaving, is worse than either alone — and `seq`,
the resume cursor, is a per-scan counter that a second table could not share.

**Suppress filenames at each read site.** Rejected. A rule applied at several places is a rule
that eventually gets applied at all but one of them, and the one it misses is the fallback path
nobody watches.

**Keep the filename in `detail` and add only `correlation_id`.** Rejected: it leaves per-document
replay unindexable and leaves suppression as an allow-list somebody extends without noticing what
it protects.

## Open

- **Per-phase and per-format stall thresholds** (PRD §18/§22). Still one `STALL_AFTER_S`; the
  lease clause added here is the half of §22's rule that does not need per-format evidence.
- **A per-run or per-workspace privacy override.** `remediation_filename_privacy` takes a
  `scan_id` it does not yet use, which is where one plugs in without touching a call site.
- **`paused`, `policy_version`, `execution_mode`** — unchanged, and still declared-and-never-
  derived for the reasons PRD §20 records.
