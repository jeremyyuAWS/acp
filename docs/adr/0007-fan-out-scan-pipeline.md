# ADR 0007 — Fan-out scan pipeline (discover → scan_file → finalize)

**Status:** ACCEPTED
**Date:** 2026-06-26
**Authors:** ACP team

---

## Context

Scanning is a **single monolithic job**: `run_scan` lists the source, downloads
*every* file to the container's ephemeral disk, analyses them (per-file analysis
is thread-parallel, but it's one job on one replica), and saves once at the end.

That ceilings out well before **10K files / user**:

- One container holds all files in memory + the **1 GiB ephemeral disk**, and the
  whole scan is bounded by one box's wall-clock.
- Downloads are **sequential** (the Google client/httplib2 isn't thread-safe).
- The .NET Office engine processes **all** Office files in one subprocess call.
- Hard caps (`_search_drive` 500, `_search_folder` 1000) truncate large estates.

Meanwhile **remediation already scales** — it fans out one durable `remediate_file`
job per file across the worker pool (now multi-replica via Redis tokens). Scanning
should use the same machinery.

## Decision

Decompose the **queued** scan into three durable job types, mirroring remediation:

```
POST /scans?queue=true&fanout=true
  └─ enqueue  scan_discover
        scan_discover:  list source (paginated, no cap) → create scan_runs(status=running,
                        files=N, files_done=0) → open Langfuse trace → enqueue one
                        scan_file job per file → (if N==0) enqueue scan_finalize
        scan_file:      download ONE file → analyse (right engine; Office invoked
                        per-file) → detect PII → assess against the rubric → persist
                        that file's rows → emit its Langfuse spans → atomically
                        increment files_done; the job that makes files_done==N
                        enqueues scan_finalize
        scan_finalize:  aggregate the summary from the persisted file_records, set
                        scan_runs(status=done, …summary…, completed_at), finish the
                        Langfuse trace, run finalize_scan (HITL routing), clear tokens
```

### Why this works at scale

- **Memory/disk bounded** — each `scan_file` job streams one file (download →
  analyse → discard). 10K files never coexist on one disk.
- **Horizontally parallel** — N independent jobs drained by the worker pool across
  replicas; atomic `claim_job` prevents double-processing; per-file retry/dead-letter.
- **Parallel downloads** — each job builds its own Drive client, so downloads
  parallelise safely (the thing the thread-pool couldn't do).
- **Reuses proven machinery** — the same durable queue remediation already uses.

### Cross-job concerns

- **Langfuse trace** is id-keyed (`trace_id = scan_id`); each `scan_file`
  upserts the trace and adds its file span; `scan_finalize` writes the summary +
  score. No shared in-process handle needed.
- **Finalize trigger** is race-free: `UPDATE scan_runs SET files_done=files_done+1
  … RETURNING files_done`; the job whose increment equals `files` enqueues finalize.
- **Aggregation** moves to `scan_finalize`, computed from the persisted
  `file_records` (avg score, certifiable/uncertain/error counts) — no in-memory
  accumulation.

### Schema (additive, backward-compatible)

`scan_runs` gains `status TEXT` (`running`/`done`) and `files_done INT`, written at
discover and updated as files complete. Existing columns and the monolithic
`save_scan` path are unchanged.

### Compatibility / rollout

- Gated by `?fanout=true`. Shipped opt-in first, then promoted to the **default
  for the durable (queued) path** once the wiring was verified end-to-end (real
  worker draining discover→scan_file→finalize, finalize-fires-exactly-once, and
  aggregation matching `file_records`). The monolithic `run_scan`/`scan` handler
  stays as the fallback and still backs the sync/in-process paths and tests, so a
  caller can always force the old path with `?fanout=false`.
- Discovery cap is `ACP_FANOUT_MAX_FILES` (default 50k) on the fan-out path; the
  monolithic path keeps the conservative 500/1000 caps that protect its one-box disk.
- Per-file persistence reuses the exact column writes `save_scan` already does,
  factored into `store.save_file_result(scan_id, file_result)`.

## Consequences

- **+** Scales to 10K+ files/user; scan throughput grows with workers + replicas;
  per-file durability (a flaky file retries without restarting the whole scan).
- **+** Live progress is now real (files_done/files updates as jobs complete) — no
  more "scoring…" guessing.
- **−** More moving parts (3 job types) and more queue rows per scan (one per file).
  Acceptable — it's the same pattern remediation runs.
- **−** Office per-file invocation pays the .NET process-startup cost per file;
  mitigated by parallelism and, later, small per-batch chunks.

## Alternatives considered

- **Raise the caps + bigger container** — postpones the wall, doesn't remove the
  monolithic-job ceiling (memory/disk/one-box time).
- **Per-batch jobs (N files each)** — fewer queue rows, but reintroduces the
  batch-memory problem and complicates retry granularity. Per-file is the clean
  unit; batching is a later tuning knob.
