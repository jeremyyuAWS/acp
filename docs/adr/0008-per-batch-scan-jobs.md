# ADR 0008 — Per-batch scan jobs for very large estates

Status: **Accepted** · Supersedes nothing · Extends [ADR 0007](0007-fan-out-scan-pipeline.md)
· Date: 2026-06-29 · Implemented 2026-06-29 (`scan_batch` handler, opt-in `batch=true`,
auto above `ACP_SCAN_BATCH_THRESHOLD`)

## Context
ADR 0007 made scans a durable fan-out: `scan_discover` → **one `scan_file` job per
file** → `scan_finalize` (triggered by an atomic counter). This is excellent for
parallelism and resumability up to ~tens of thousands of files.

It does **not** scale cleanly to the hundreds-of-thousands-of-files estates we now
target (`ACP_FANOUT_MAX_FILES` is 250k):

- **Queue bloat** — 250k `jobs` rows per scan. Postgres handles it, but enqueue is one
  INSERT per file, the queue table churns hard, and `claim_job` contention rises.
- **Per-job overhead dominates** — for small/fast files (HTML), the fixed cost of
  claim → run → complete → counter-bump per file swamps the actual analysis.
- **Discovery is already a single long step** — listing 250k Drive files (paginated)
  happens before any per-file job runs; the per-file enqueue loop adds to that latency.

## Decision
Introduce a **`scan_batch`** job that analyses **N files** (default **50**) in one
durable unit, sitting between discover and finalize:

```
scan_discover ──> M × scan_batch (≈ files/50 jobs) ──> scan_finalize
                    each: download+analyse+persist 50 files, then bump_files_done(+50)
```

- `scan_discover` chunks the discovered file list into batches of `ACP_SCAN_BATCH_SIZE`
  (default 50, env-overridable) and enqueues one `scan_batch` job per chunk, carrying the
  chunk's file descriptors in the payload.
- `scan_batch` loops the chunk: per file it does the **same** download → analyse →
  deep-scan → persist as today's `scan_file` (the per-file analysis code is unchanged —
  it's refactored into a shared `_analyse_and_persist_one(...)` helper used by both
  `scan_file` and `scan_batch`). It bumps the finalize counter **once** by the number of
  files it successfully processed (`bump_files_done(scan_id, n)`), so the existing
  finalize-once trigger is preserved.
- A single file failing inside a batch is isolated (error record + counted), exactly as
  `scan_file` does today — the batch never fails wholesale on one bad file.

## Compatibility (non-negotiable)
- **`scan_file` stays.** The per-file path is the proven default; `scan_batch` is **opt-in**
  via `fanout=batch` (or auto-selected above a file-count threshold, e.g. > 20k). Existing
  `?fanout=true` behaviour is unchanged.
- **`bump_files_done` gains an optional increment arg** (`bump_files_done(scan_id, n=1)`),
  defaulting to 1 — backward compatible with `scan_file`.
- **Langfuse / storage shapes are identical** — a batch writes the same per-file spans and
  `file_records` rows; only the *job granularity* changes, which is invisible downstream.
- **Resumability holds** — a dropped `scan_batch` re-runs its whole chunk; `save_file_result`
  is already idempotent (delete-then-insert per file), so re-running a partially-done batch
  is safe.

## Consequences
- ~**5,000 jobs** instead of 250k for a 250k-file estate (at batch=50): far less queue
  churn and claim contention; discovery's enqueue loop shrinks 50×.
- **Trade-off: coarser parallelism + retry granularity** — a batch is the unit of retry, so
  one transient failure re-does up to 50 files' downloads. Batch size is the dial: smaller =
  finer retry + more parallelism, larger = less overhead. 50 is the starting point; tune by
  measuring p95 batch time vs. queue depth.
- **Worker memory** — a batch holds up to N files' temp data at once; we bound this by
  streaming (download → analyse → free per file within the batch, not all-at-once).
- The `.NET` Office analyser already processes a directory in one invocation, so batching
  Office files is a *natural* fit (fewer CLI spawns) — a secondary win.

## Open questions
1. **Auto-select threshold** — fixed (> 20k files → batch) or always honour the explicit
   `fanout=` choice? Proposed: explicit wins; auto-batch only when `fanout=true` AND
   files > threshold.
2. **Adaptive batch size** by engine (HTML 100/batch, Office/PDF 20/batch)? Defer — start
   with one global size, revisit with telemetry.
3. **Payload size** — 50 file descriptors per job payload is small; at very large batch
   sizes the JSON payload grows. Cap batch size (≤ 200) to keep payloads bounded.

## Rollout
1. Refactor per-file analysis into `_analyse_and_persist_one` (no behaviour change).
2. Add `bump_files_done(scan_id, n=1)`.
3. Add the `scan_batch` handler + `scan_discover` chunking under `fanout=batch`.
4. Load-test on a synthetic 100k-file corpus; compare wall-clock + queue depth vs. per-file.
5. Promote to the auto-selected default above the threshold once verified.
