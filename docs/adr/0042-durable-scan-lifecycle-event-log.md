# ADR 0042 — A durable scan-lifecycle event log (Postgres), with SSE kept as the live transport

**Status:** Accepted — open questions resolved by the owner 2026-08-29; implementation under way (PR 1 of 4: the table, unused)
**Date:** 2026-08-29
**Related:** ADR 0004 (Postgres job queue), ADR 0013 (worker durability hardening / finalize by
count), ADR 0020 (Discover/Assess phase separation), ADR 0038 (pausable-resumable scans),
ADR 0039 (regional resilience). Code: `api/core.py` (`set_job`/`update_job`/`get_job_state`/
`_maybe_checkpoint`), `api/routes/scans.py` (the three SSE endpoints), `api/live_snapshot.py`,
`api/live_queue.py`, `api/activity.py`, `frontend/src/api.js` (`openDiscoverStream`),
`frontend/src/App.jsx` (`pollScanJob`/`reconnectJob`), `frontend/src/liveAssessment.js`.

---

## Context

### What exists today, precisely

Scan lifecycle state today is a **mutable current-state record in Redis**, tailed by three
independent SSE endpoints. There is no event *log* anywhere — nothing appends, everything
overwrites.

**The store.** `core.set_job(job_id, state)` writes a Redis hash; `core.update_job(job_id, patch)`
patches fields with `HSET` + `HINCRBY seq` in one pipeline. `seq` is a change counter, not an
event id — it tells a reader *that* something changed, never *what* or *in what order*. Keys carry
`_JOB_TTL = 3600`. With no `REDIS_URL`, writes land in the process-local `JOBS` dict and are
invisible to every other replica (`set_job` logs a warning saying exactly that).

**The emitters.** `api/routes/scans.py` (thread path) and `api/handlers.py` (durable-queue path)
call `update_job` at phase transitions: `queued → discovering → lifecycle → saving → done`, plus
`error`. `worker.py` writes `phase: "retrying"` via `on_retry=update_job`. `api/activity.py`
publishes a *separate* synthetic key, `activity:{scan_id}`, at up to 5 writes/second (`_MIN_INTERVAL
= 0.2`) carrying the current file/criterion headline; its in-flight map is an in-process dict under
a lock, deliberately not in the store.

**The streams.** Three of them, with genuinely different contracts:

| Endpoint | Anchored on | Client | Terminal rule |
|---|---|---|---|
| `GET /scans/jobs/{job_id}/stream` | job_id | native `EventSource` (`App.jsx: pollScanJob`) | `state.done` → `event: done` |
| `GET /scans/{scan_id}/discover/stream` | scan_id (re-resolves job_id each poll) | `fetch` + `ReadableStream` (`api.js: openDiscoverStream`) | `done`, or 4 missed polls → checkpoint frame + `event: error` |
| `GET /scans/{sid}/events` | scan_id | native SSE auto-reconnect (`liveAssessment.js`) | snapshot not `available` or not `active` |

**The one durable thing that already exists.** `core._maybe_checkpoint` accumulates the same
patches `update_job` receives and flushes them to `scan_runs.live_checkpoint` (a single JSON
column, overwritten each time) on phase/done/error transitions and otherwise at most once per
`ACP_CHECKPOINT_INTERVAL_S` (20s). Its own comment states why the cadence is deliberate: it must
stay far below the write volume that caused the 2026-08-26 Postgres connection exhaustion. It is
**last-known-state, not history** — one row, overwritten, no ordering, no prior values.

### What this area has already cost, and must not cost again

This is the most race-prone code in the repo, and four fixes in the last two weeks are load-bearing
context for anything proposed here:

1. **`test_job_completion_race.py` (2026-08-28).** `reclaim_stuck_jobs()` requeues a job whose
   lease expired so a second worker can finish it — but the first (zombie) worker's handler keeps
   running and later calls `complete_job`/`fail_job`/`mark_job_cancelled` on the same `job_id`.
   Last writer silently won. Fixed by guarding every terminal UPDATE with
   `WHERE status NOT IN ('done','dead','cancelled')`. **Consequence for this ADR: two writers can
   legitimately produce events for the same job_id at the same time, and one of them is wrong.**

2. **`worker.py:307` re-read after `fail_job`.** `fail_job` returns `"queued"` even when the
   reclaim-race guard suppressed its write, so the worker re-reads the row before announcing
   `phase: "retrying"` — otherwise a zombie's late failure announces "retrying" over a job that
   already finished.

3. **`test_discover_completion_race.py` (2026-08-28).** `_scan_discover` used to flip the durable
   status to `discovered` *before* `add_inventory()` ran. The frontend clears `busy` the instant
   status ≠ running, so a scan rendered "Discovery complete, 0 files" against a still-empty
   inventory table. Fixed by ordering the flip after the durable write.

4. **The `event: error` reconnect-freshness bug (2026-08-26, documented in `api.js`).** Treating
   the server's `event: error` frame as a *transport* failure flipped `sseFailedRef` on **every
   cleanly-finished scan**, degrading the last ticks to polling `getJob(job_id)` with a job_id that
   had already aged out — reproducing the exact 404s the scan-anchored stream was built to
   eliminate. The rule that came out of it: **`event: done` and `event: error` both mean "the
   stream ended"; only a non-ok response or a reader exception is a transport failure.**

Read together these say something specific: **every one of these bugs was a *state* bug — two
writers disagreeing about one mutable cell, or a reader acting on a cell before its companion
write landed.** An append-only log is the shape that makes several of them structurally
impossible to repeat, which is an argument *for* this work; it is also new write volume on the hot
path, which is the argument for being narrow about what goes in it.

### What breaks today, that a user actually notices

- **A rollout eats the run's history.** ACP runs on Azure Container Apps, and `/control/workers/capacity`
  now reports `revision_health` / `draining_replicas` precisely because rollouts are mid-drain often
  enough to be worth surfacing (#957). Today a merge-triggered redeploy during a scan leaves the
  thread-path job with no trace at all — `core.py`'s own comment records the 2026-08-21 incident
  where a job sat at `phase="queued", scan_id=null` forever. `_job_is_stale` (90s) now converts that
  into an honest terminal error, which is a real improvement — but the *history* ("claimed by w3 at
  14:02, listed 4,100 files by 14:06, replica went away at 14:07") is gone. The operator gets
  "scan interrupted — the server likely restarted mid-run", with nothing to show how far it got.
- **Redis TTL beats the user.** `_JOB_TTL` is 3600s. Come back to a tab 70 minutes after a scan
  finished and there is nothing to reconnect to; `openDiscoverStream` correctly treats the
  resulting `event: error` as a clean end, which is right but leaves an empty panel.
- **Reconnect shows current state, never what was missed.** All three streams' first frame is the
  *current* state. A user whose laptop slept for ten minutes rejoins at "82% done" and cannot see
  that files 300–450 were retried twice against a rate-limited Drive credential — the `retrying`
  phases were written to a cell that has since been overwritten.
- **`document_timeline` has no run-level source.** `store.document_timeline` already assembles an
  auditor-grade per-file history from `scan_runs`, `file_records`, `ai_calls`, `hitl_queue`,
  `hitl_events`, `applied_fixes` and `decision_log` — "nothing is inferred or fabricated". It has
  **no lifecycle source**, because none is persisted. "What happened to this document" can be
  answered; "what happened to this *run*" cannot.
- **No-Redis deployments have no cross-replica progress at all.** Stated plainly in `set_job`'s
  warning. A durable log makes progress readable from any replica by construction, without making
  Redis a hard dependency.

### What depends on events being ephemeral (checked, not assumed)

Only two things, and both survive:

- **`_scan_freshness`** classifies `live` / `checkpoint` / `stale` by *how recently Redis was
  written*. It uses the store's recency as a liveness proxy. A durable log must therefore **not**
  be written on a cadence that makes a dead run look alive — one more reason lifecycle transitions,
  not heartbeats, are what gets persisted.
- **`live_queue.STALE_AFTER = 120`** and `activity`'s `_STALE = 300` prune the in-flight set so a
  crashed worker's document stops reading as "being assessed". These operate on the in-process map
  and the Redis activity key, neither of which this ADR touches.

Nothing else assumes events disappear. `purge_done_jobs(older_than_hours=24)` deletes finished
`jobs` rows hourly from the sweeper — which is *why* a lifecycle log is worth having separately:
the queue row that carried the history is deliberately garbage-collected.

---

## Decision

**Add an append-only `scan_events` table in Postgres that records scan-run lifecycle transitions,
and keep SSE exactly as it is as the live transport. Coexist; do not replace.**

Three rules define the split, and the first is the one that makes this affordable:

1. **The durable log records *transitions*, not *ticks*.** A row is written when the run changes
   state in a way a human would narrate: queued, claimed by a worker, listing started, listing
   complete, inventory saved, lifecycle rules applied, assessment started, retrying, paused,
   cancelled, completed, failed, interrupted. It is **not** written for `files_found` incrementing,
   for `activity.record_file`'s 5-per-second headline, or for per-file completion — `file_records`
   already persists the last of those with timestamps, and `document_timeline` already reads it.

2. **Redis stays the live current-state cell.** `set_job`/`update_job`/`get_job_state` are
   unchanged. Every SSE endpoint keeps tailing Redis at its current cadence. The log is written
   *beside* the Redis write, on the same code path, best-effort.

3. **The log is a read surface, not a stream source — at first.** It gets its own endpoint
   (`GET /scans/{sid}/history`). Only after that is shipped and proven does the existing
   checkpoint-fallback frame start reading from it (PR 4), and that change is one frame's contents,
   not a change to any stream's terminal rules.

### Why coexist rather than replace — the honest reasoning

The tempting architecture is "durable log as source of truth, SSE tails the log." It is the right
end-state for a system that starts there. It is the wrong *next step* here, for three reasons
specific to this codebase:

- **Cadence mismatch.** The streams poll at 250ms and 1s. `_maybe_checkpoint`'s own comment records
  that Postgres write volume in this exact path caused connection exhaustion on 2026-08-26, and
  the response was to throttle to one write per 20s. Making Postgres the *live* source means either
  reintroducing that write volume, or degrading live progress from 250ms to something far coarser.
  Neither is an acceptable trade for a durability win we can have without it.
- **The races are all in the write path, and replacement rewrites the write path.** Fixes (1)–(3)
  above landed in the last two weeks. Re-plumbing `update_job` into a log-first design touches
  every one of them. Writing *beside* the existing calls touches none.
- **We can get the user-facing win without it.** Everything named under "what breaks today" is
  answered by *having a durable history to read*, not by changing what delivers live frames.

The cost of coexistence is honest and should be stated: **two writes, and therefore the
possibility of divergence.** A Redis write can succeed while the Postgres append fails. This is
mitigated, not eliminated: the log is append-only and each row is self-describing, so a *missing*
row is a gap in narration, never a wrong statement — the same contract `activity.py` already runs
under ("a progress line must never be able to fail the work it describes"). Reconciliation is not
attempted and should not be: the log narrates, `scan_runs` + `file_records` remain authoritative
for counts and outcomes, exactly as `live_snapshot.py`'s honesty invariant requires.

**This is the call that most deserves a human's sign-off** — see "Open questions" below.

---

## Schema

```sql
CREATE TABLE IF NOT EXISTS scan_events (
  event_id    TEXT PRIMARY KEY,   -- uuid4 hex; stable identity for dedupe/idempotency
  scan_id     TEXT NOT NULL,      -- the anchor; stable across job retries (unlike job_id)
  seq         INT  NOT NULL,      -- per-scan monotonic, 1-based; the ordering + resume cursor
  occurred_at TEXT NOT NULL,      -- ISO-8601 UTC, microseconds; audit-readable, not the sort key
  kind        TEXT NOT NULL,      -- controlled vocabulary, below
  phase       TEXT,               -- the `phase` value written to Redis in the same breath, or NULL
  job_id      TEXT,               -- which job produced it (changes across retries — that's the point)
  worker_id   TEXT,               -- claiming worker, when known
  attempt     INT,                -- 1-based attempt number, for retry events
  detail      TEXT,               -- JSON object; per-kind payload, always small (< ~1KB)
  owner_email TEXT                -- denormalized from scan_runs so reads scope without a join
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_scan_events_seq ON scan_events(scan_id, seq);
CREATE INDEX IF NOT EXISTS idx_scan_events_read ON scan_events(scan_id, seq);
```

**Primary key and ordering.** `event_id` is the primary key (stable identity, safe to retry an
insert). **`(scan_id, seq)` is the ordering guarantee** and carries a UNIQUE index — that index is
what makes ordering a constraint rather than a convention, and it is what a resume cursor compares
against.

**Why `seq` and not a timestamp or a sequence type.** Two constraints force this:

- **No `BIGSERIAL`, no `AUTOINCREMENT`.** `store._SCHEMA`'s header states the schema is identical
  between SQLite and Postgres, and *no table in this repo uses an auto-increment column* — every
  key is explicitly supplied (`decision_log` uses "created_at + a uuid tiebreak"). A portable
  server-side sequence is not available.
- **Timestamps are not a safe total order here.** Events for one scan can be written from more than
  one replica (a reclaimed job's second worker), and `occurred_at` is a wall clock. Under the
  zombie-worker case from `test_job_completion_race.py` that is exactly when ordering matters most.
  A cursor over `(occurred_at, event_id)` would silently *skip* a late-arriving event stamped before
  the cursor — a resume that loses events is worse than no resume.

`seq` is assigned in the INSERT itself, as one statement, so it needs no transaction spanning a
read and a write (the SQLite adapter opens a fresh connection per `cursor()`, so it could not
provide one anyway):

```sql
INSERT INTO scan_events (event_id, scan_id, seq, occurred_at, kind, ...)
SELECT %s, %s, COALESCE(MAX(seq), 0) + 1, %s, %s, ...
  FROM scan_events WHERE scan_id = %s;
```

The UNIQUE index turns a lost race into an integrity error rather than a duplicate `seq`; the
writer retries up to 3 times and then drops the event (best-effort, per rule 2 of the write
contract below). **Contention is negligible by construction** because of rule 1: run-level
transitions are written by one job's thread at a time, ~10–30 rows per scan. This is the direct
reason per-file events are excluded — 8 assessment threads inserting per file would make MAX+1
contention real, and `file_records` already holds that data.

**`kind` vocabulary** (closed set, extended only by ADR amendment):

`scan.queued` · `scan.claimed` · `scan.listing_started` · `scan.listing_complete` ·
`scan.inventory_saved` · `scan.lifecycle_applied` · `scan.discovered` · `scan.assess_started` ·
`scan.retrying` · `scan.paused` · `scan.resumed` · `scan.cancelled` · `scan.completed` ·
`scan.failed` · `scan.interrupted`

**`detail` is a JSON object**, per-kind, and deliberately small: `{"files_found": 4100}`,
`{"error_class": "rate_limit", "message": "…"[:200]}`, `{"reason": "lease_expired"}`. It is
narration, never a second source of truth for a count that `scan_runs` already holds.

**`owner_email`** is denormalized so a read scopes without joining `scan_runs`, matching how
`live_snapshot` gates. `scan_events` joins `_ANALYTICS_TABLES` and `_RESET_USER_SCAN_TABLES` in
`store.py` — the reset-completeness test (`test_reset_leaves_no_customer_data`) fails closed if a
data table is left out, so this is not optional.

---

## Retention and growth

**Recommendation: never delete, and say so in the schema comment.** This repo already treats
`decision_log`, `finding_comments`, `disposition_audit` and `scan_file_manifests` as append-only
records that are never updated or deleted (ADR 0002, ADR 0003), and ADR 0003 states plainly that
"a scan remains an immutable event". A lifecycle log is the same kind of object.

That position is only defensible because rule 1 makes the volume trivial, and the arithmetic
belongs in the ADR rather than in a hand-wave:

| | rows/scan | 100 scans/day | 1 year | at ~250 B/row |
|---|---|---|---|---|
| **Transitions only (this design)** | ~15–30 | ~2.5k/day | ~900k rows | **~225 MB** |
| Transitions + per-file completion (7k-file estates) | ~7,000 | ~700k/day | ~250M rows | ~60 GB |
| If activity ticks were logged (5/s × 20 min) | ~6,000 | ~600k/day | ~220M rows | ~55 GB |

The first row is affordable to keep forever on the pilot's Postgres and stays index-friendly. The
second and third are not, and the table would need partitioning or a retention window — which is
the practical argument for the scope rule, not merely a tidiness one. **If a later ADR admits
per-file events into this table, it must ship a retention decision in the same PR.**

Deletion happens only where it already happens for scan data:

- `delete_scan(scan_id, owner)` and `reset_user_data(owner)` remove a scan's events with the rest
  of that scan's rows. That is "delete my scan and everything about it", the contract those methods
  already document.
- `reset_analytics()` clears it with the other data tables.
- **The sweeper does not touch it.** `purge_done_jobs(older_than_hours=24)` is scoped to the `jobs`
  table and stays that way — the whole point is that lifecycle history outlives the queue row.

No partitioning in this design. If volume ever justifies it, partition by month on `occurred_at`
(not by scan — thousands of tiny partitions is worse than one indexed table), and revisit then.

---

## Interaction with the reconnect path

This is where the risk sits, so it is spelled out as *changes* vs *invariants*.

### Unchanged — and these are the invariants that must be re-asserted in review

- **`pollScanJob`'s settle-once semantics.** The `settled` flag, `es.close()`, and the single
  resolve/reject stay exactly as they are.
- **`event: done` and `event: error` both mean "the stream ended".** `openDiscoverStream` continues
  to call `onDone` for both. **This is the 2026-08-26 fix and it is the single easiest thing to
  regress while adding a new frame type** — a durable history makes `event: error` *feel* like it
  should become recoverable, and it must not.
- **The 4-missed-poll rule, the 250ms/1s cadences, `_MAX_STREAM_ITERS`,** and every terminal
  condition in all three generators.
- **`_job_is_stale`'s 90s read-time staleness** and its `retrying` exemption. A durable log does
  **not** become a liveness signal — `_scan_freshness` keeps deriving `live` from Redis recency.
  Persisting a transition must never make a dead run look alive; this is why heartbeats are
  excluded from the log.
- **`liveAssessment.isNewerFrame` / the `sequence` dedupe.** `live_snapshot.sequence` is
  `completed` (a file count). `scan_events.seq` is a different number in a different namespace and
  is never fed into that comparison.
- **`live_snapshot`'s honesty invariant.** KPIs keep coming from the run summary. The log never
  becomes a tally source.

### Changed, and only here

- **PR 4 only:** the checkpoint-fallback frame in `stream_discover_state` — the one emitted after 4
  missed polls, already marked `live: false` — is enriched from `scan_events` instead of reading
  only the single overwritten `scan_runs.live_checkpoint` cell. It stays **one frame**, still
  `live: false`, still **followed by the same `event: error` and the same close**. No new terminal
  state, no new frame type, no change to what the client does on receiving it.
- **New, additive:** `GET /scans/{sid}/history` returns the ordered event list. It is a plain
  owner-scoped JSON read, not a stream. `?after_seq=N` supports "what did I miss", which is what
  makes the ten-minute-laptop-sleep case answerable.

**A naming trap worth writing down:** `GET /scans/{sid}/events` is *already taken* — it is the
Assess live SSE stream. `GET /scans/{sid}/timeline` is *also taken* (`document_timeline`, requires
`?file=`). Hence `/scans/{sid}/history`. Getting this wrong would shadow a live endpoint.

### Ordering, restated as a rule

**A lifecycle event is appended *after* the durable write it describes has landed, never before.**
This is the direct lesson of `test_discover_completion_race.py`: `scan.inventory_saved` is written
after `add_inventory()` returns, not when listing finished. An event that a reader can act on must
not out-run the state it claims.

**Zombie writers**, per `test_job_completion_race.py`: the log is append-only, so both workers'
events are kept — a second `scan.completed` from a zombie does not overwrite anything, and carries
its own `job_id`/`worker_id`/`attempt` so the disagreement is *visible* rather than silently
resolved by whoever wrote last. This is strictly better than the mutable cell, and it is the
clearest single argument for the log's shape. Readers rendering a headline should take the
**first** terminal event by `seq`; `worker.py`'s existing re-read-before-announce guard already
prevents the common case from being written at all.

---

## Phased implementation plan

Sized like the rest of this repo's work — single-purpose PRs, each independently revertible.

**PR 1 — the table, unused.** `scan_events` DDL + indexes in `store._SCHEMA`; add to
`_ANALYTICS_TABLES` and `_RESET_USER_SCAN_TABLES`; `store.append_scan_event(...)` and
`store.list_scan_events(scan_id, after_seq=None, limit=…)` with tests (append/read-back, per-scan
`seq` monotonicity, concurrent-append uniqueness under threads, unknown scan reads empty,
reset-completeness). **No caller.** Zero behaviour change; the reset test is the one that would
otherwise fail closed later.

**PR 2 — write the run-level transitions.** Call `append_scan_event` beside the existing
`core.update_job` calls in `api/routes/scans.py` (thread path) and `api/handlers.py`
(durable-queue path), plus `worker.py`'s `on_retry` for `scan.retrying`. Every call wrapped and
best-effort — an append must never fail the scan it describes (`activity.py`'s contract, verbatim).
Ordering rule enforced: appended after the durable write. Tests assert the emitted sequence for a
normal run, a retried run, and a cancelled run — and that a raising `append_scan_event` does not
fail the scan.

**PR 3 — the read surface.** `GET /scans/{sid}/history` (owner-scoped, `?after_seq=`, always-200
degrade to `{"available": false}` like `/live` and `/status`). Frontend: render it in the existing
run-detail area. This is the PR where the user-facing win lands and where the design gets
validated against a real run before anything in the stream path is touched.

**PR 4 — enrich the checkpoint-fallback frame.** The single change to `stream_discover_state`
described above. Kept last, kept alone, and reviewed against the four regression tests named in
this ADR. **A candidate for stopping here** — PRs 1–3 deliver the whole user-facing story, and
PR 4 is the only one that touches code with a two-week bug history.

**PR 5 (deferred, not proposed here) — `Last-Event-ID` resume on a stream.** SSE's native resume
header, replaying `scan_events` from the client's last `seq`. Genuinely valuable and genuinely the
riskiest thing in this space: it changes the reconnect *contract*, not just a frame. It should be
its own ADR after PRs 1–4 have run in production, and it is the reason `seq` is designed as a
resume cursor now even though nothing resumes on it yet.

---

## Open questions — RESOLVED 2026-08-29 by the owner

**All three were signed off as recommended.** They are kept below as written, with the decision
recorded against each, because the reasoning is what a later reader needs — an ADR that silently
deletes the question it answered leaves the answer looking arbitrary.

| # | Question | Decision |
|---|---|---|
| 1 | Coexist vs. replace | **Coexist**, as recommended. Redis stays the live cell; Postgres becomes the history. Revisit only if the horizon moves from the current pilot to customer-production (ADR 0039) — that is a new ADR, not a refactor of this one. |
| 2 | Per-file events in or out | **Out**, as recommended. Run-level transitions only. |
| 3 | Does PR 4 ship | **Decide on production evidence**, as recommended — PRs 1–3 first; PR 4 is judged once the history read surface has run against real scans. Not cancelled, not pre-approved. |

The original framing follows.

---

These are close enough that a reasonable engineer could pick differently. **PR 1 is safe to start
regardless of how they land** (an unused, append-only table with no caller is the same table under
every answer); PR 2 onward should not start until the first is answered.

1. **Coexist vs. replace (the load-bearing one).** This ADR recommends coexistence — Redis stays
   the live cell, Postgres becomes the history — and accepts dual-write divergence as the price.
   The alternative (log as source of truth, SSE tails it) is a better end-state and a worse next
   step, for the cadence and race-surface reasons given above. If the owner's horizon is
   customer-production on a customer-controlled Azure environment (ADR 0039) rather than the
   current pilot, that calculus changes and the replace path deserves its own ADR rather than
   arriving as a later refactor of this one.

2. **Per-file events: in or out?** Excluded here, because `file_records` already persists per-file
   completion, because 7k rows/scan changes the retention answer from "never delete" to
   "partition or expire", and because 8 concurrent inserters makes the `MAX(seq)+1` assignment
   contended. If a per-file *narrative* (not just an outcome row) is wanted, it is a separate
   table with its own retention decision — not a widening of this one.

3. **Does PR 4 ship at all?** PRs 1–3 are additive and touch nothing with a race history. PR 4
   touches the discover stream's fallback path. The win is real (a reconnect after Redis expiry
   shows history instead of an empty panel) and the risk is concentrated in the file with four
   recent fixes. Shipping 1–3 and deciding on 4 with production evidence is a defensible outcome.

## Consequences

**Gained.** A run's history survives an ACA revision rollout, a replica loss, and Redis TTL expiry.
`document_timeline` gains the run-level source it currently lacks — "what happened to this run" becomes
answerable to the same standard as "what happened to this document". A user reconnecting after ten
minutes can see what they missed, not just where things stand. Deployments without Redis get
cross-replica lifecycle visibility for the first time. Zombie-writer disagreements become visible
rather than silently last-writer-wins.

**Cost.** One more table, ~15–30 small Postgres inserts per scan on a path whose write volume
caused an outage three days ago — bounded deliberately, and orders of magnitude below the
throttled checkpoint cadence, but not zero. Dual-write divergence is possible and is not
reconciled by design. Four PRs of work, one of which touches the most race-prone file in the repo.

**Explicitly not solved.** This does not make scans resumable (ADR 0038), does not make Redis
optional for live progress, does not change any KPI's source, and does not add a live-tail on the
log. Those are separate decisions, and naming them here is meant to stop this ADR being cited as
having settled them.
