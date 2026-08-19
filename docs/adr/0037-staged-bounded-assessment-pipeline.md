# ADR 0037 — Staged, bounded assessment pipeline (measure-first)

**Status:** Proposed. Design ADR for Track B of the scan-progress/parallelisation work; Track A (the
outcome-oriented progress UX) shipped in #452/#455/#458/#460/#463. This decides how the assessment
fan-out is parallelised at pilot scale (thousands of files) **without** the failure modes uncontrolled
concurrency would cause, and — the load-bearing principle — that worker counts are tuned from
**measured per-stage time**, not guessed.
**Date:** 2026-08-19
**Related:** `api/core.py` (the worker pool, `ACP_WORKERS`), `api/handlers.py`
(`_enqueue_analysis`, `_analyse_and_persist_one`), `api/store.py` (`bump_files_done`,
`save_file_result`, the retry/dead-letter jobs), ADR 0013 (idempotent finalize), ADR 0019/0022 (the
vision provider + GPU), ADR 0020 (Discover/Assess phase separation), #347 (retry + dead-letter).

## Context

The scan already parallelises — this ADR is about the *shape* of that parallelism, not introducing it.

**What exists today, and is not in question:**

- **A bounded worker pool, not thread-per-file.** `core.start_workers()` spawns `ACP_WORKERS`
  in-process worker threads (capped at 16) that drain a durable `jobs` queue. So the catastrophe of
  "one thread per file → Drive throttling / OOM / GPU overload" is *already avoided*: concurrency is
  bounded by the pool size.
- **Per-file isolation.** Each file is one job; `_analyse_and_persist_one` wraps its work so a single
  bad document fails that job, not the run.
- **Idempotency.** `save_file_result` upserts on `(scan_id, file)` and `bump_files_done` is reconciled
  by `count_files_done` (ADR 0013), so a retried job cannot double-count or double-insert.
- **Retry + dead-letter.** Failed jobs retry and land in a dead-letter lane surfaced in Monitor (#347).
- **Durable, checkpointed progress.** `scan_runs.files_done` is bumped as each file lands; a
  deploy/restart mid-scan is recovered by the stuck-job sweeper and `rescue_unfinalized_scans`.
- **Safe cancellation.** `cancel_scan` kills outstanding (not-yet-started) jobs; work already done is
  kept.
- **Stable ordering.** `get_scan` returns files `ORDER BY file`, independent of completion order.
- **Observability.** Every AI call is traced with model / tokens / cost / zone (Langfuse, #368–#372).

**What is missing — the actual subject of this ADR:**

1. **The pool is FLAT, not staged.** One `ACP_WORKERS` pool runs the whole per-file chain —
   download → extract → deterministic checks → vision → save — inside a single job. So every stage
   shares one concurrency limit, even though the stages have *opposite* constraints: downloads are
   I/O-bound and want high concurrency but must respect Drive throttling; extraction is CPU-bound;
   vision is GPU-bound and wants *low, VRAM-shaped* concurrency; DB writes want batching. One number
   cannot be right for all five.
2. **No GPU micro-batching or VRAM-shaped limit.** Vision goes through `active_vision_provider()`
   per image; nothing groups compatible requests or bounds concurrent model calls by measured VRAM.
   More GPU concurrency past that point makes throughput *worse* (model contention / memory pressure),
   which a flat pool cannot express.
3. **No per-stage instrumentation.** We cannot today answer "which stage is the bottleneck?" — and the
   bottleneck varies by estate (downloads for many small cloud files, extraction for large PDFs/PPTX,
   vision for image-heavy documents). Tuning worker counts without that measurement is guessing.

## Decision

### 1. Separate the per-file chain into bounded *stages*, each with its own concurrency

Model the fan-out as a pipeline of stages, each a bounded pool sized to its own constraint, rather than
one job per file on one pool:

```
enumerate → download → extract → evaluate (deterministic) → vision (GPU) → save
```

Stages hand work forward through the existing durable `jobs` queue (so checkpointing, retry,
dead-letter, and cancellation are inherited unchanged). A file flows through the stages independently;
the slowest single-file chain, not the sum of per-stage worst cases, sets wall-clock.

### 2. Per-stage concurrency — starting points to benchmark, NOT constants

| Stage | Constraint | Starting concurrency |
|---|---|---|
| Folder enumeration | Drive/Graph API, paginated | limited async, backoff |
| File download | network I/O, throttling | 8–16 concurrent |
| Office/PDF extraction | CPU | 2–4 per CPU allocation |
| Deterministic checks | CPU | 4–8 workers |
| Vision inference | GPU VRAM | **one controlled queue per GPU**, micro-batched |
| Result writes | DB latency | batches of 25–100 |

These are the user-supplied starting points. They are **explicitly not** frozen constants: §4 makes
them adjust to measured throttling, CPU/memory pressure, VRAM, DB latency, and error/retry rates.

### 3. GPU handling — route only vision to the GPU, micro-batch, VRAM-bounded

Most deterministic checks stay on CPU. Only vision-dependent work (image alt-text, 1.1.1; scanned-PDF
page reads, ADR 0027) reaches the GPU. The vision stage:

1. extracts embedded images / page crops in parallel (a CPU-side extract stage),
2. queues only *eligible* visual assets,
3. groups compatible image requests into micro-batches,
4. limits concurrent model calls by *measured* VRAM,
5. returns results independently so CPU checks continue.

The rule that makes this non-obvious: **more GPU threads can make throughput WORSE** (model contention
/ memory pressure). The GPU stage's concurrency is therefore the one knob most likely to be *lowered*
by measurement, not raised — which is exactly why it cannot be a guessed constant.

### 4. Adaptive, not fixed — driven by measured signals

Worker counts per stage adjust on: Drive throttling responses (429/backoff), file sizes, CPU/memory
pressure, GPU VRAM headroom, DB latency, and error/retry rates. The `set_worker_count` runtime knob
already exists for the flat pool (`core.py`); this generalises it per stage.

### 5. Invariants to preserve (some already met) — the safety contract

Parallel execution is only safe if these hold, and the staged design must keep every one:
per-file isolation · idempotent processing (upsert) · exponential backoff for Drive throttling ·
durable queues + checkpointed progress · file-version validation before reuse · per-stage timeouts ·
retry limits + dead-letter · **fair scheduling** so one huge PDF does not starve small files ·
stable result ordering independent of completion order · safe cancellation of not-yet-started work.
Durable execution stays invisible to users — it is simply the platform's normal behaviour.

## Measure FIRST — the sequencing that makes this honest

The single most important decision here is ordering: **instrument, then tune, then split.** Choosing
worker counts before measuring which stage limits throughput would bake in guesses. So the migration
is staged, each step gated on the numbers the previous one produced:

- **Step 0 — instrumentation (the next PR).** Record time spent per stage (enumerate, download,
  parse/extract, deterministic checks, GPU queue-wait, GPU inference, DB write) per scan, and surface
  it (a `/scans/{id}/timings` rollup + the completed-scan summary). No behaviour change — it only
  *measures*. This also feeds Track A's stage strip, whose distinct per-stage counts were deferred
  precisely because this measurement did not exist.
- **Step 1 — split the vision/GPU stage** into its own bounded, micro-batched queue (the stage most
  likely mis-sized today), guided by Step 0's GPU numbers.
- **Step 2 — split download from CPU extract**, sized from Step 0's download vs parse split.
- **Step 3 — batch DB writes.**

Each step ships behind the guard suite and is re-measured before the next.

## How it is tested / benchmarked

- **Instrumentation is unit-tested** against synthetic stage timings (deterministic, no real scan).
- **Correctness is invariant-tested**, reusing the existing scale tests (#293–#296: 30k files, ~50
  concurrent users, per-user isolation, shared-drive dedup) — the staged pipeline must produce
  *identical* per-file results and counts to the flat one.
- **Throughput is benchmarked, not asserted:** a fixture estate is run and the per-stage timings
  compared before/after each split, so a change that does not move the measured bottleneck is not
  shipped as if it did.

## Consequences

- The flat `ACP_WORKERS` pool becomes a set of per-stage bounded pools; the durable `jobs` queue and
  its retry/dead-letter/cancellation machinery are reused, not replaced.
- A new per-stage timing table (or trace attributes) and a `/scans/{id}/timings` read.
- No change to the source-agnostic inventory, the capability matrix, or per-file results — the pipeline
  reorganises *how* work is scheduled, never *what* a scan concludes.

## Status / next step

Proposed. The next PR is **Step 0 — the instrumentation slice**: measure per-stage time with no
behaviour change, so every subsequent worker-count decision is made from data. Nothing about the flat
pool changes until its numbers are in.
