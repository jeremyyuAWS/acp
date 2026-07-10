# ADR 0013 — Worker durability hardening: idempotent finalize + worker-process isolation

Status: Partially accepted — finalize-once SHIPPED 2026-07-08; worker-process isolation code + deploy path CODIFIED 2026-07-10 (dormant behind `ACP_DEPLOY_WORKER=1`, live spin-up greenlit separately when load warrants — billable Redis + second app)
Date: 2026-07-08

## Context

The 2026-07-08 full-path production audit (Discovery → Assess → Remediate → Publish)
cleared every P0 and P1 finding and most P2s. Two P2 findings were **deliberately not
fixed in that pass** because a safe fix changes worker/queue semantics that were, at the
time, being actively edited by concurrent work on the remediate/finalize path — a rushed
change there is exactly the architectural entropy the project guards against. This ADR
records both so they land deliberately, with test coverage, rather than as a blind edit.

Both are follow-ons to the durable job queue (ADR 0004), the fan-out scan pipeline
(ADR 0007), and per-batch jobs (ADR 0008).

### Finding 1 — non-idempotent finalize trigger (`bump_files_done`)

The fan-out scan finalizes exactly once via an atomic counter: each `scan_file` /
`scan_batch` job calls `store.bump_files_done(scan_id)` (`api/store.py`) which does
`UPDATE scan_runs SET files_done = files_done + N ... RETURNING files_done, files`, and the
worker that observes `done >= total > 0` enqueues `scan_finalize`
(`api/handlers.py`, per-file `scan_file` and batch `scan_batch` paths).

The counter is bumped **before** `complete_job`, and is not idempotent per file. If a
`scan_file`/`scan_batch` job crashes (or its worker is killed) *after* the bump but
*before* completing, the lease sweeper re-queues it and it bumps **again**. Two failure
modes follow:

1. **Early finalize** — `done` overshoots the true distinct-file count, so `done == total`
   can be reached while a file's result has not yet persisted → `scan_finalize` fires before
   the scan is actually complete.
2. **Duplicate finalize** — `scan_finalize` can be enqueued twice; `core.finalize_scan`
   (HITL auto-routing + audit-log emission) has no double-run guard, so HITL items / audit
   entries can be double-emitted.

The scan *summary* self-corrects (`finalize_scan_run` recomputes from `file_records` via
`COUNT`/`SUM`, and `save_file_result` is upsert-idempotent), so this is masked in the happy
case; the exposure is duplicate HITL/audit emission and a transient "done-but-short" window.
It requires a crash in a millisecond-wide window, so it is rare — but it is a correctness
bug, and it gets more likely as estates grow (more jobs → more crash surface).

### Finding 2 — event-loop starvation (workers share the API process)

`core.start_workers()` spawns N in-process worker **threads** (`ACP_WORKERS`) inside the
same uvicorn process that serves the FastAPI app. Job handlers do heavy **pure-Python,
CPU-bound** work — OOXML/Office parsing (ADR 0012 analysers via subprocess, plus in-process
XML work), PII detection, remediation — which holds the GIL and starves the async event
loop (the access-gate middleware) and the sync-route threadpool in the *same* container.

Consequences: raising `ACP_WORKERS` to parallelize CPU-bound scanning degrades API latency
in the same process; there is no true horizontal scale for the worker tier. The Redis-backed
scan-token store (`core.register_scan_tokens` / `get_scan_tokens`) was already built to
support cross-replica workers, but Redis is not currently provisioned, so the in-memory
fallback is per-replica and the co-located default doesn't benefit.

## Decision

Two independent changes; either can ship alone.

### 1. Make finalize idempotent (correctness) — SHIPPED 2026-07-08

- **Trigger on a real count, not a running counter.** Replace the `bump_files_done`
  increment-and-compare trigger with a comparison of the **actual persisted count** —
  `SELECT COUNT(*) FROM file_records WHERE scan_id = %s` vs `scan_runs.files` — evaluated
  after each file's `save_file_result`. A retried job re-saves the same `file_records` row
  (upsert), so the count cannot overshoot: the trigger is naturally idempotent and can never
  fire early. Keep the atomic-read shape so exactly one worker observes the crossing.
- **Guard `scan_finalize` against double-run.** Add a `finalized_at` timestamp on
  `scan_runs`; `core.finalize_scan` no-ops (returns early) when it is already set, and sets
  it in the same transaction that emits HITL/audit. This makes a duplicate `scan_finalize`
  enqueue harmless regardless of the trigger.
- Cover both with a test that simulates a `scan_file` retry (bump/observe twice) and asserts
  a single finalize + no duplicate HITL/audit rows.

  **Shipped:** `store.count_files_done` (COUNT of file_records vs `scan_runs.files`) replaced the
  `bump_files_done` running-counter trigger in `scan_file`/`scan_batch`; `store.mark_finalized`
  (atomic `SET finalized_at WHERE finalized_at IS NULL`, `finalized_at` added to the scan_runs
  CREATE + a Postgres ALTER) guards `core.finalize_scan` so duplicate/concurrent `scan_finalize`
  jobs no-op. Covered by `tests/test_finalize_idempotent.py` (idempotent count + once-only).

This is `store.py` + `handlers.py` + `core.py` and **must be sequenced after** the
in-flight remediate/finalize-path work merges, then tested on the finalize path — not
applied as a blind three-file dance.

### 2. Run workers as their own replicas (scale — larger; infra)

- Provision **Redis** (Azure Cache for Redis, or a container) and point
  `register_scan_tokens` / `get_scan_tokens` at it so scan/remediate tokens survive
  cross-replica and restart (this also lets ADR 0013-unrelated token durability stop relying
  on the payload copy — see the terminal-row token scrub already shipped).
- Split the worker tier into its **own Container App** (same image, a `worker` entrypoint
  that calls `start_workers()` with `ACP_WORKERS>0` and does **not** serve HTTP), and run the
  API with `ACP_WORKERS=0`. Scale the two independently. CPU-bound parsing then never
  contends with the request path.
- This is a deploy-topology change (`deploy/public/deploy.sh` + a second app + Redis) with a
  cost/latency tradeoff, so it is gated on real load justifying a second replica set.

**Code-ready (2026-07-08):** the standalone worker entrypoint `api/worker_main.py` is
implemented + committed (dormant until wired) — it calls `core.start_workers()`, blocks the
main thread, and on SIGTERM runs a graceful `core.stop_workers()` drain; no HTTP port. The
Redis token plumbing already exists (`core.REDIS_URL` → `_get_redis()` → register/get_scan_
tokens).

**Deploy path codified (2026-07-10):** `deploy/public/deploy.sh` now carries the whole
topology behind `ACP_DEPLOY_WORKER=1` (billable → still greenlit separately, so it stays off
by default and this path is not yet exercised against live infra). When set, one deploy run:
brings up (or updates) an `acp-worker` Container App from the SAME image with command
`python -m worker_main`, `ACP_WORKERS=N` (`ACP_WORKER_COUNT`, default 2), the same
DB/Blob/Langfuse secrets + `REDIS_URL`, no ingress, min-replicas 1 — FIRST; then flips the
API to `ACP_WORKERS=0`. `REDIS_URL` is a new inheritable secret wired onto both tiers; the
run refuses `ACP_DEPLOY_WORKER=1` without it. To actually spin it up (greenlit):

```
# 1. one-time: provision Redis (cheapest tier is fine for tokens) and capture the SSL DSN
az redis create -g mdk-accessibility -n acp-redis --sku Basic --vm-size c0 --enable-non-ssl-port false
REDIS_URL="rediss://:$(az redis list-keys -g mdk-accessibility -n acp-redis --query primaryKey -o tsv)@acp-redis.redis.cache.windows.net:6380/0"

# 2. deploy both tiers (worker up first, API flipped to 0) in one run
ACP_GOOGLE_CLIENT_ID=<gis-id> REDIS_URL="$REDIS_URL" ACP_DEPLOY_WORKER=1 bash deploy/public/deploy.sh

# 3. one-time (first create only): grant the worker's managed identity Blob access, else its
#    remediation writes 403 (run against the Customer Demos subscription used for the deploy):
MI=$(az containerapp show --subscription "Customer Demos" -g mdk-accessibility -n acp-worker --query identity.principalId -o tsv)
SCOPE=$(az storage account show --subscription "Customer Demos" -n acpremediatedstore -g mdk-accessibility --query id -o tsv)
az role assignment create --assignee "$MI" --role "Storage Blob Data Contributor" --scope "$SCOPE"
```

To roll back to co-located workers: redeploy without `ACP_DEPLOY_WORKER` and pass
`ACP_WORKERS=4` (the API reclaims job processing; the idle `acp-worker` app can be deleted).

## Consequences

- **Finalize (1):** duplicate HITL/audit emission and the transient done-but-short window are
  eliminated; the finalize trigger becomes provably idempotent under retries and crashes.
  Small schema add (`finalized_at`) via the existing idempotent `ADD COLUMN IF NOT EXISTS`
  migration list; no behaviour change on the happy path.
- **Isolation (2):** the worker tier scales horizontally without degrading API latency, and
  cross-replica token durability stops depending on the in-memory fallback. Adds a Redis
  dependency and a second Container App — real cost, so it ships when load warrants it, not
  by default.
- Until (2) ships, the operational guidance stands: keep `ACP_WORKERS` modest on the
  co-located process; heavy scans should prefer off-peak windows.
- Neither change alters the `/api/v1` surface, storage schema (beyond the additive
  `finalized_at` column), or the fan-out contract; both are internal durability hardening.
