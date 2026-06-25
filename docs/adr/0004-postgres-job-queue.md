# ADR 0004 — Durable Orchestration via a Postgres Job Queue

**Status:** PROPOSED
**Date:** 2026-06-25
**Authors:** ACP team

---

## Context

Today a scan runs as an in-process FastAPI background thread
(`scanner.run_scan` on a `threading.Thread`; progress kept in an in-memory `JOBS`
dict). That is fine for the demo and for libraries up to a few hundred files, but
it has three structural limits:

1. **No durability.** If the container restarts mid-scan, the run is lost — there
   is no record of what was done or what remained.
2. **No retry.** A transient Drive/API/engine failure on one file fails (or silently
   drops) work; there is no per-unit retry with backoff.
3. **No pause/resume or distribution.** Work can't be paused, resumed, prioritized,
   or spread across workers.

The PRD goals that need this are **#2 (partial remediation — resume from the last
completed step)** and **#4 (phased remediation across thousands–millions of files —
batches, priority queues, pause/resume)**. Both are specified in
[ADR 0003](0003-document-lifecycle-model.md), which defines the durable *state*
(`documents`, `remediation_state`, `campaign`, `campaign_batch`). ADR 0003 is the
*what*; this ADR is the *how* — the execution engine that drives those state rows.

Temporal is the obvious heavyweight answer, but it is a whole additional system
(server + workers + its own datastore) to deploy and operate **inside every
customer VPC** — which directly fights the platform's "standalone, `docker compose
up`, zero external dependencies" property (see `deploy/compose/`). The earlier
Temporal standup was also operationally costly.

## Decision

Add a **Postgres-backed job queue** as the durable execution layer. It keeps the
deployed footprint at exactly what it is today — **Postgres + the app** — and reuses
the database that already holds every scan and audit record.

### Schema

```
jobs
  id            TEXT PRIMARY KEY
  type          TEXT          -- 'scan_file' | 'remediate_file' | 'finalize_scan' | …
  payload       JSONB         -- e.g. {scan_id, file, drive_file_id, ai_enabled}
  status        TEXT          -- queued | running | done | failed | dead | cancelled
  priority      INT           -- lower = sooner (department/business-criticality)
  attempts      INT  DEFAULT 0
  max_attempts  INT  DEFAULT 5
  run_after     TIMESTAMPTZ   -- backoff / scheduling gate (default now())
  locked_at     TIMESTAMPTZ   -- set when a worker claims it
  locked_by     TEXT          -- worker id (for stuck-job reclaim)
  campaign_id   TEXT          -- nullable; ties a job to an ADR 0003 campaign/batch
  batch_id      TEXT          -- nullable
  scan_id       TEXT          -- nullable; ties to scan_runs
  last_error    TEXT
  created_at    TIMESTAMPTZ
  updated_at    TIMESTAMPTZ
```

Indexes: `(status, run_after, priority)` for the claim query; `(campaign_id)`,
`(scan_id)` for rollups.

### Claiming work — the load-bearing primitive

A worker atomically claims the next eligible job with Postgres row-locking:

```sql
UPDATE jobs SET status='running', locked_at=now(), locked_by=:worker,
                attempts=attempts+1, updated_at=now()
WHERE id = (
  SELECT id FROM jobs
  WHERE status='queued' AND run_after <= now()
  ORDER BY priority, run_after
  FOR UPDATE SKIP LOCKED
  LIMIT 1
)
RETURNING *;
```

`FOR UPDATE SKIP LOCKED` is what makes this safe and contention-free: any number of
worker loops can run this concurrently and each gets a distinct job, no double-
processing, no external broker. This is the well-trodden "Postgres as a queue"
pattern (the same primitive behind Que, Graphile Worker, River, etc.).

### Worker loop

```
while running:
    job = claim_one()                  # the query above
    if not job:
        sleep(poll_interval); continue
    try:
        handle(job)                    # type-dispatched; idempotent
        mark_done(job)
    except Retryable as e:
        backoff = base * 2**job.attempts (capped, jittered)
        if job.attempts >= job.max_attempts: mark_dead(job, e)
        else: requeue(job, run_after=now()+backoff, last_error=e)
    except Fatal as e:
        mark_dead(job, e)
```

### Semantics & rules

- **At-least-once + idempotent handlers.** A crash after work but before
  `mark_done` re-runs the job, so every handler must be safe to repeat (e.g.
  `scan_file` upserts its results; uses `ON CONFLICT`). This is the same contract
  the existing `_save_file_manifest`/`save_scan` upserts already satisfy.
- **Retry with capped, jittered exponential backoff** via `run_after`.
- **Dead-letter**, not silent drop: exhausted jobs become `dead` with `last_error`,
  visible for inspection and manual requeue.
- **Stuck-job reclaim.** A sweeper requeues `running` jobs whose `locked_at` is older
  than a lease timeout (worker died mid-job).
- **Pause/resume** = an `ADR 0003` campaign/batch status gate: a paused campaign's
  jobs are simply not claimed (the claim query joins/filters on campaign status, or
  paused jobs get `run_after` pushed out). Resume clears the gate.
- **Priority & phased rollout** fall out of `ORDER BY priority`: set `priority` from
  department / business-criticality so a campaign drains in the intended order.
- **Jobs drive ADR 0003 state.** A `remediate_file` job transitions the file's
  `remediation_state` (`in_progress → complete` / `awaiting_review`); `finalize_scan`
  rolls a scan up. The queue is the engine; `remediation_state` is the truth.

### Migration of the current path

`run_scan` is decomposed into enqueued units: one `scan_file` job per discovered
file + a `finalize_scan` job. The synchronous `?sync=true` path (used by tests and
small scans) stays as an in-process fast path. The in-memory `JOBS` dict is replaced
by querying the `jobs` table for live progress (so progress survives a restart).

### Local / SQLite

`FOR UPDATE SKIP LOCKED` is Postgres-only. For local SQLite dev, fall back to a
single-worker, short-transaction `BEGIN IMMEDIATE` claim (no concurrency, which is
fine for a dev box). Production (Postgres) gets the concurrent path. This matches the
existing dual-adapter pattern in `store.py`.

### Observability

The `jobs` table is natively visible in Grafana (queue depth, throughput, failure
rate, oldest-queued age) — add a panel to the ACP dashboard. Each job execution
emits a Langfuse span, so a file's scan/remediation is traceable end to end exactly
as scans are today.

## Consequences

**Gains**
- Durability, retries, pause/resume, priority, and distribution for scans and
  campaigns — the execution half of PRD #2 and #4.
- **Zero new infrastructure**: no broker, no Temporal, no extra service in the VPC.
  The whole stack stays "Postgres + app", preserving the `docker compose up` story.
- Reuses the database, the dual adapter, the upsert/idempotency patterns, and the
  Langfuse/Grafana observability already in place.

**Costs / limits**
- It is a **queue, not a workflow engine.** Multi-step DAGs, signals, child-workflow
  orchestration, and "wait for human for 30 days" are awkward — you model them as
  chained jobs + state in `remediation_state`, not as a workflow definition.
- You own the worker loop, the backoff, and the stuck-job sweeper (well-understood,
  but real code to test — treat retries/concurrency as the draft-then-harden areas).
- High-throughput polling adds DB load; tune `poll_interval` and consider
  `LISTEN/NOTIFY` to wake workers instead of tight polling.

**When to graduate to Temporal (or similar):** if workflows genuinely become
multi-step DAGs with signals, long human-wait timers, and cross-entity
orchestration that the queue-of-jobs model makes unreadable — *and* the operational
cost of running it in each VPC is acceptable. Until then, the queue is the right
altitude. Revisit in a follow-up ADR if that threshold is crossed.

## Implementation order

1. `jobs` table + claim query + a generic worker loop (one worker), with retry +
   dead-letter. Wire `run_scan` to enqueue `scan_file` + `finalize_scan` jobs.
2. Concurrency (multiple workers via `SKIP LOCKED`) + stuck-job sweeper.
3. Campaign/batch integration from [ADR 0003](0003-document-lifecycle-model.md):
   priority, pause/resume, department-ordered rollout.
4. Grafana queue panel + per-job Langfuse spans.

Each step is independently shippable; step 1 already replaces the fragile in-memory
background-thread path with a durable one.

## Implementation status (2026-06-25)

Step 1's **durable queue infrastructure** is implemented and tested:

- `jobs` table + claim index (`api/store.py`), timestamps as ISO-8601 TEXT for
  Postgres/SQLite portability.
- Store methods: `enqueue_job`, `claim_job` (optimistic conditional-update claim),
  `complete_job`, `fail_job` (backoff requeue / dead-letter / `force_dead`),
  `reclaim_stuck_jobs`, `job_stats`, `list_jobs`.
- `api/worker.py`: `JobWorker` (claim → dispatch → complete/retry loop), a
  `@handler("type")` registry, capped jittered exponential backoff, and
  `FatalJobError` for immediate dead-letter.
- `tests/test_jobs.py`: 10 passing tests (claim/complete, priority, retry→dead,
  force-dead, backoff gate, stuck reclaim, worker loop).

**Deferred (next):** wiring `scanner.run_scan` to enqueue `scan_file` jobs. The
open design question is **Drive-token handling** — a per-file Drive job needs an
access token, and persisting a user's GIS token in `jobs.payload` (at rest in
Postgres) is a security concern. Options to resolve before integration: scope jobs
to the local/ADC path first; pass a short-lived token via a side channel; or have
the worker mint a service-identity token rather than reuse the user's. The
multi-worker `SKIP LOCKED` claim (step 2) and campaign integration (step 3) follow.
