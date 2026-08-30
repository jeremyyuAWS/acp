# PRD — ACP reliability hardening

**Status:** Draft for product and engineering review; no implementation or environment changes authorized by this document.
**Prepared:** 30 August 2026. **Priority:** P0 incident mitigation; P1 durable hardening.
**Scope:** Production and staging API, database access, Discover/Monitor reads, scan submission, deployment startup, and operational telemetry.
**Proposed accountable roles:** Backend lead (submission and database access), frontend lead (shared reads and failure UX), platform lead (capacity, logging, migrations), QA lead (release evidence). Named owners and delivery dates remain to be assigned.

> **Draft re-verification, 30 August 2026 (this commit).** Every source reference in
> §3 was re-read against `origin/main` at `039b7c9c` and each line number below is
> current as of that commit, not the `b460e291` the analysis session read. Two items
> §7 left open have since been resolved and are recorded inline: the open-PR overlap
> clearance (§7.1) and the status of H-01 (§4). The `evidence/` bundle described in §8
> is **not** checked into this repository — see §8.

## 1. Product outcome

Users must be able to submit discovery while browsing a large inventory and monitoring work. ACP must either acknowledge one durable job or explain that submission was not accepted. Temporary capacity shortages must not appear as an empty queue, a dead worker, a completed scan, or lost documents.

The 30 August incident occurred before enqueue. Increasing worker concurrency cannot repair that submission path. The verified exception is local API pool exhaustion, but the database was also CPU-saturated. Therefore, increasing the pool alone is an experiment with explicit safety gates, not an established safe fix.

This PRD extends the existing production checklist in [`docs/production-hardening.md`](production-hardening.md); it does not replace it or claim that the older checklist accurately describes today's architecture.

## 2. Evidence and limits

### Review window and method

Historical production window: **29 August 2026 16:45 UTC through 30 August 2026 16:45 UTC** (09:45 PDT to 09:45 PDT). Incident window: **30 August 16:40–16:43 UTC**. Queries used Azure Log Analytics `ContainerAppConsoleLogs_CL` and Azure Monitor one-minute database metrics. Configuration and staging tail samples were read around 09:53–10:00 PDT, while deployments were progressing.

Code review used fetched `origin/main` at `b460e291`; deployed image tags at the initial configuration capture referenced `11bd03c`. Code observations below describe the reviewed source; incident stack frames corroborate the specific submission failure. No production load test, direct SQL session inspection, or end-to-end reproduction was performed in this analysis. The requirements below specify that verification work.

### Confirmed production findings

| Finding | Evidence | Implication |
|---|---|---|
| Preflight returned 500 at 09:41:03 PDT | `discovery_preflight`, `job_stats`, terminal `PoolError` | Capacity checks themselves depend on the constrained database |
| Queued Drive submission returned 500 at 09:41:10 PDT | `start_scan`, line 131, `active_scan`, terminal `PoolError` at 09:41:11 | Failure precedes scan ID allocation, supersession, and `enqueue_scan` on this path |
| Inventory and queue reads failed concurrently | Five `/jobs` failures including the queued filter; one inventory failure at offset 5000, limit 1000; plus the two POST failures | Eight HTTP 500s in this incident; the inventory failure concerns the page covering approximately rows 5001–6000 |
| Pool failures recur across five revisions | 88 terminal pool exception lines; 177 text mentions | Count exceptions separately from repeated traceback text |
| Production database CPU was sustained near its ceiling | 24-hour mean of minute averages 98.36%; 1,434 of 1,440 minutes averaged at least 90% | A local pool increase can increase database contention |
| Database connection ceiling was not reached in the incident minute | Limit 150; 09:41 minute maximum 38, average 33.5; 24-hour maximum 74 | Connection count headroom is not CPU headroom |
| Startup deadlocks are an additional failure class | 16 API and 38 worker terminal `DeadlockDetected` lines; 14 API startup-failed messages | Deployment/schema initialization needs separate hardening |

The supplied revision counts **16, 29, 26, 42, 64** are reproduced as text mentions. Terminal `psycopg2.pool.PoolError` counts for revisions **825, 818, 816, 815, 776** are **8, 14, 13, 21, 32**, respectively. They sum to 88. These are log exception counts, not deduplicated affected users or scans; request IDs are missing.

Across the fixed window, production access logs contain **4,600 responses: 4,470 HTTP 200, 28 HTTP 304, 12 HTTP 401, and 90 HTTP 500**. The observed 500 fraction is 1.96%, including health probes and deployment traffic; this is not a user-journey SLO. Failed routes include `/jobs` (36), job detail (10), inventory (10), source status (6), decisions (6), scan decisions (4), queue estimate (4), scan listing (3), HITL queue (3), PII (3), preflight (2), readiness (2), and submission (1). Do not attribute all 90 responses to pool exhaustion without request correlation.

Production worker logs show three startup messages for revision 454 at approximately 09:27, each reporting 12 worker threads. No corresponding new job claim appears in the sampled incident window. That supports the pre-enqueue diagnosis; startup messages alone do not prove continuous worker health. Separately, one earlier discovery job was dead-lettered after a suspicious zero-file result against a 6,916-file prior scan, with three subtree-listing failures. Preserve that distinct failure category rather than classifying every discovery failure as a pool issue.

At 09:41, production CPU averaged **99.50%**, memory averaged **66.92%**, and the CPU-credit metric reported **1 remaining credit**. Credits were not observed at zero; do not label this proven credit exhaustion. Sampled startup deadlocks show `Store → init_schema → cur.execute(stmt)` with AccessExclusive/AccessShare lock contention. The exact conflicting SQL and relation names remain to be established.

### Staging comparison

| Configuration / metric | Production | Staging |
|---|---:|---:|
| API `ACP_WORKERS` | 0 | 0 |
| Explicit `ACP_DB_MAX_CONN` | Unset | Unset |
| Derived API pool maximum per process | 10 | 10 |
| API configured replicas, min–max | 1–3 | 1–1 |
| Worker threads per replica | 12 | 2 |
| Worker configured replicas, min–max | 3–10 | 1–3 |
| Derived worker pool maximum per process | 20 | 10 |
| Database SKU | Standard_B1ms | Standard_B1ms |
| Database `max_connections` | 150 | 50 |
| Observed 24-hour connection maximum | 74 | 27 |
| Mean database CPU over sampled minutes | 98.36% | 16.55% |
| Historical environment log export | Log Analytics | No destination; no environment diagnostic settings |

Staging's available API tail shows startup around 09:50 and a local `/scans` HTTP 200 at 09:51:11 followed by successful polling. That request did not use `queue=true`; it does not validate durable queued discovery under load. The worker tail shows two workers starting. No pool error appears in those short samples, but **staging's historical error rate is unknown**, not zero. Its lighter load and smaller worker tier prevent treating it as a production-equivalent validation environment.

The production revision had advanced from incident revision 825 to 826 during this review. Staging worker metadata and streamed revision names also changed during rollout; latest-ready metadata is not an inventory of all active replicas.

## 3. Problem model

Source review identifies several amplification paths. Line numbers are current at `origin/main` `039b7c9c`.

- **`api/store.py:1087–1113`** — `db_max_conn()` returns `max(2, workers) + _API_HEADROOM_CONN`, with `_API_HEADROOM_CONN = 8` at line 1112. With `ACP_WORKERS=0` (the split-topology API container) this is `max(2, 0) + 8 == 10` regardless of real HTTP concurrency. `ACP_DB_MAX_CONN` overrides it (line 1107).
- **`api/store.py:1156–1170`** — `_getconn` retries `pool.getconn()` every 50 ms for up to five seconds before re-raising `PoolError`. A bounded wait already exists. The fix must address capacity and fairness, not merely add another retry loop.
- **`api/routes/system.py:868–908`** — `/jobs` reads worker heartbeat, oldest queued job, statistics, dead-letter breakdown, and job list as five separate store calls. This means repeated acquisitions and queries, not necessarily five simultaneous held connections per request.
- **`frontend/src/Discover.jsx:233` and `:275`** — two independent effects each call `getJobs`, one filtered to `queued` and one unfiltered. Other `getJobs` consumers are `QueuePanel`, `AssessRunner`, `FailureLane` and `FixOutcomes`. Mount combinations require a DOM-level regression test.
- **`frontend/src/discoveryInventory.js`** — sequential pagination is bounded (`PAGE_LIMIT = 1000`, `MAX_PAGES = 30`) and rejects partial results, but has no shared in-flight cache. `Discover.jsx`, `Overview.jsx` and `DiscoverInventoryExport.jsx` independently invoke it. Logs show repeated first-page requests; they do not by themselves identify the originating component.
- **`api/routes/scans.py:1336–1352`** — every inventory page performs `get_scan` for ownership, then `list_inventory_page`, then `count_inventory`. Profile these reads and replace unnecessary aggregate work with a narrow owner-scoped lookup where justified.
- **`api/store.py:1136–1141`** — lazy pool creation (`_get_pool`) has no explicit initialization lock. Audit concurrent first-use behavior and prove only one pool is constructed; this is a code risk, not a verified cause of this incident.
- **`api/store.py:1143–1154`** — `init_schema` executes `_SCHEMA` and `_PG_VIEWS` statements at process initialization. Sampled historical startup deadlocks implicate this path; concurrent rollout can overlap API and worker initialization.
- **`api/routes/scans.py:73–133`, ordering** — `start_scan` reads `active_scan` at line 131 and calls `supersede_scan` at line 133, but does not reach `enqueue_scan` until line 179. Supersession therefore commits *before* acceptance is durable, so a pool failure between the two cancels the user's prior run and creates nothing. In the 30 August incident the failure was at line 131, before supersession — but the ordering hazard is real and is what H-03 addresses.

Working hypothesis: sustained database CPU pressure and repeated reads increase connection hold time, allowing bursty UI activity to exhaust a small local pool. Query timings, lock waits, process/replica attribution, and transaction hold metrics are needed to determine each contributor's share. A leaked connection is not established.

## 4. Requirements

### P0 — Safe capacity mitigation

**H-01. Explicit role-based budgets.** API pool sizing must be independent of `ACP_WORKERS`. Preserve a documented explicit override, validate malformed and out-of-range values at startup, and log effective role, process count, pool maximum, and acquisition deadline without credentials. Pool size 20 is a candidate for the API only, subject to H-02; do not increase worker pools as part of that mitigation.

> **Overlap, 30 August 2026:** open PR
> [jeremyyuAWS/acp#1045](https://github.com/jeremyyuAWS/acp/pull/1045) already
> decouples the headroom term from `ACP_WORKERS`, raises `_API_HEADROOM_CONN` from
> 8 to 16, adds a `PoolError` handler returning 503 with `Retry-After`, and adds a
> concurrent-load reproduction test. **It merged as `fb754290` later the same day**, so
> H-01 and the 503 half of H-05 are **done**. H-02 was never run against it — see
> §4.1 for what running it now shows. The remaining H-05 obligations (stable
> `DB_CAPACITY_BUSY` code, request ID, incident time, `submission_state`) are still
> uncovered: the shipped body uses `detail: "database_busy"` and carries no request ID
> or timestamp.

**H-02. Capacity gate.** Before changing pool or replica limits, document the maximum budget per database:

`sum(active revision replicas × processes per replica × pool maximum) + migration/monitor/admin connections + reserved safety headroom ≤ server limit`

Include warm revisions and rolling-deployment overlap. Under a one-process assumption, production's current configured maxima already permit **3×10 + 10×20 = 230** pool connections before overhead, above 150. An API pool of 20 permits **260**. Staging permits **1×10 + 3×10 = 40** against 50 before overhead and overlap. Pools grow on demand; these are potential ceilings, not observed connection counts. The platform owner must verify actual process counts and adopt enforceable budgets before enabling those scale limits.

At current production CPU saturation, first measure expensive queries and reduce optional read pressure. Benchmark a pool of 10 versus 20 with bounded read concurrency on a representative staging workload. A capacity/tier change may be needed; provide its cost and rollout proposal for separate approval. Do not infer safety from the 150-connection setting.

### 4.1 H-02 applied to the merged H-01 fix — the gate's first real result

H-01 asked for the API pool to be sized independently of `ACP_WORKERS`, and said explicitly:
*"do not increase worker pools as part of that mitigation."* The merged fix
(`api/store.py`, `fb754290`) replaces `max(2, workers) + 8` with `max(2, workers + 16)`.
That is one formula for **every** role, so the constant — still named `_API_HEADROOM_CONN` —
is added to the worker tier's twelve threads as well:

| Role (`ACP_WORKERS`) | Pool before | Pool after |
|---|---:|---:|
| Production API (0) | 10 | **16** |
| Production worker (12) | 20 | **28** |
| Staging API (0) | 10 | **16** |
| Staging worker (2) | 10 | **18** |

Carried through H-02's budget formula at each environment's configured `maxReplicas`:

| Environment | Ceiling before | Ceiling after | Server `max_connections` |
|---|---:|---:|---:|
| Production | 3×10 + 10×20 = 230 | 3×16 + 10×28 = **328** | 150 |
| Staging | 1×10 + 3×10 = 40 | 1×16 + 3×18 = **70** | 50 |

Two things follow, and neither is a criticism of the fix — the incident it targets was real
and its own reasoning about connection count is sound:

1. **The worker tier was raised as a side effect**, which is the one thing H-01 asked not to
   do. The constant's name says API; its application does not.
2. **Staging's ceiling now exceeds its own server limit**, where before it did not (70 against
   50; production was already over at 230 and is further over at 328). Crossing the *server*
   limit is a worse failure than exhausting a local pool: `FATAL: too many connections` refuses
   everything, migrations and the monitor included, rather than making one request wait.

These are potential ceilings, not observed counts — pools grow on demand and the observed
24-hour maxima were 74 (production) and 27 (staging), so nothing is breached today. But that
gap is exactly what H-02 exists to hold, and it is now wider than when this PRD was drafted.
**This is not a request to revert or to re-tune the constant in code**: per H-02 the numbers
are the platform owner's to set against verified process counts, using `ACP_DB_MAX_CONN`, which
the merged fix deliberately preserves as the override for precisely this decision.

### P1 — Durable submission and truthful overload behavior

**H-03. Atomic submission.** Success returns the durable scan/job identifiers only after commit. Preserve existing atomic scan/job/input-snapshot enqueue. Make prior-run supersession atomic with acceptance, or defer it until acceptance is durable; source review confirms supersession currently commits at `scans.py:133`, 46 lines before `enqueue_scan` at `:179`. Rejected submissions must not cancel the user's existing run.

> **Done — deferral, the second of the two options above.** `start_scan` now reads the prior
> run before enqueue but stops it only after `enqueue_scan` has committed
> (`_supersede_replaced_run`, `api/routes/scans.py`). Two guards came out of writing the
> regression: the stop skips the scan being returned, because an `Idempotency-Key` replay
> could otherwise kill the job it was handing back; and it never raises, because after commit
> the scan exists and a failure there would report a false rejection whose retry enqueues a
> real duplicate. `tests/test_scan_submission_atomicity.py` fails on the old ordering.
>
> The atomic option was not taken. It needs `_end_running_scan` to accept a caller's cursor so
> the stop joins `enqueue_scan`'s transaction; that helper kills jobs and stamps three tables,
> and threading a cursor through it for every existing caller is a larger change than the
> defect warrants. The residue is a millisecond window in which both runs exist and a worker
> could claim the new job before the old one is stopped — self-correcting (the next submission
> supersedes it, and `acquire_discovery_guard`'s stale reclaim covers abandonment), and
> strictly smaller than the destroyed-run failure it replaces. Revisit if that window is ever
> observed to matter.

**H-04 note.** The idempotency guard above is a *server-side* protection for a key the client
already sends when it chooses to. H-04's actual requirement — the UI minting one key per submit
intent and retaining it across retries — is not built.

**H-04. Idempotent retries.** The UI creates one owner-scoped idempotency key per submit intent and retains it across retries. A lost response after commit must resolve to the existing job. Do not automatically create a new intent after a timeout. Test concurrent retries and the order of idempotency lookup versus supersession.

**H-05. Explicit failure contract.** Exhausted capacity returns HTTP 503 with `Retry-After`, a stable `DB_CAPACITY_BUSY` code, request ID, UTC incident time, and `submission_state: not_created` only when known. An uncertain commit outcome must say `unknown` and offer status reconciliation. Authentication and authorization failures retain their own semantics. Never translate infrastructure failures into successful empty data.

**H-06. Bounded admission.** Limit low-priority read concurrency and waiting requests so polling cannot consume all submission capacity or HTTP execution slots. Define acquisition, statement, lock, and request deadlines as one budget. Prefer fair bounded scheduling over unbounded retries; verify rollback, cancellation, broken connections, and connection return on every exception. Do not hold transactions during external API calls or response streaming.

### P1 — Reduce unnecessary database work

**H-07. Shared jobs snapshot.** Provide one shared client subscription per environment, signed-in owner, and equivalent query. Derive compatible views from a common complete snapshot, but do not infer the complete queued list from a truncated recent-job list. Permit distinct filtered requests where required by correctness. Pause hidden-page polls; prevent overlap; use jittered backoff and `Retry-After`. Clear data and pending requests on logout or owner switch.

The backend should return the jobs dashboard snapshot using one acquired connection where practical, preserving owner filters and existing global infrastructure fields. Measure query count, acquisition count, and hold time; combining queries is not sufficient if it lengthens the critical transaction. Cache only with explicit scope and freshness metadata.

**H-08. Shared inventory loading.** Deduplicate identical in-flight requests and pagination across mounted consumers. Key by environment, owner, scan, filters, and inventory generation. Preserve all-or-nothing population accuracy, cancellation, invalidation after lifecycle edits, and rejection of stale responses after a scan change. For a static 6,916-row inventory at 1,000 rows/page, equivalent concurrent consumers should issue seven page requests total per refresh, not seven each.

**H-09. Efficient inventory API.** Profile the ownership lookup, page query, and count separately on a PostgreSQL fixture. Avoid assembling a full scan aggregate to authorize every page. Retain owner isolation and stable pagination. Use server-side summaries where a widget only needs counts; do not silently replace complete inventory with the first page. Ship only indexes supported by measured query plans and a safe migration plan.

### P1 — Status that survives the failure it reports

**H-10. Graceful status reads.** Operational endpoints may return a scoped last-known snapshot with `degraded`, `observed_at`, and age, or a structured 503 if none exists. Unknown worker availability must not become zero workers; unknown queue depth must not become an empty queue. Disable decisions requiring fresh evidence. Liveness remains lightweight; readiness reflects sustained inability to serve without causing restart storms from brief overload.

**H-11. Independent incident capture.** Emit a structured event to a sink that does not require the failing database pool. Monitor must expose the incident through a bounded independent retrieval/cache path, including during database trouble. Aggregate by environment, error category, revision, and time window; show occurrence count, affected operation, first/last seen, and recovery. No scan ID is required for pre-enqueue incidents. Do not synchronously write an incident into the exhausted database and repeat the failure.

**H-12. User-facing wording.** For verified rejection:

> **Discovery could not be submitted**
> ACP's database was temporarily at capacity. No scan job was created and no documents were changed by this submission. Try again shortly.
> Incident time: 9:41 AM PDT · View system status

For an ambiguous outcome: "We could not confirm whether discovery was submitted. Checking submission status…" Preserve the user's selections, announce the error accessibly, and provide a keyboard-accessible retry/status action. The Monitor incident reads "Database connection pool exhausted · Scan submission affected · API revision 0000825." Keep connector errors and worker failures separate.

### P1 — Observable, safe deployment

**H-13. Metrics and logs.** Export pool configured maximum, in-use, available, waiters, acquisition-duration histogram, timeout counter, connection-hold duration, and connection create/close/error counters. Label by environment, role, revision, process, and replica where cardinality permits. Request logs include route template, status, duration, request ID, and submission outcome. Keep tokens, document names, folder IDs, raw query strings, and personal data out of metrics and routine incident events.

Correlate pool metrics with database CPU, credits, memory, connections, lock waits, query duration, and queue age. Log one structured timeout event per failed acquisition; traceback text must not inflate incident counts. Proposed alerts: any failed submission; acquisition timeouts over a five-minute window; CPU above 85% for ten minutes; readiness degradation; migration/startup failures. Route alerts to existing authorized channels; channel changes need approval.

**H-14. Staging log parity.** Configure retained API, worker, and platform/system logs for staging with at least 30 days' searchable retention, access controls, and redaction. Validate a query for a known request across a revision change. Production and staging must use the same event schema. A lack of retained logs must appear as "no data," not "healthy."

**H-15. Schema startup safety.** Run versioned schema changes once in a controlled deployment step rather than repeatedly from every serving process. Use bounded serialization and lock deadlines, compatible migrations, and explicit failure handling. Application startup validates schema version. Test concurrent API/worker rollout while reads and job claims continue. Inspect the observed conflicting SQL before selecting the specific migration fix. Preserve graceful worker drain; signal-15 logs alone are not worker crashes.

### P2 — Connection proxy and sustained capacity

**H-16. Proxy decision.** Evaluate PgBouncer after establishing query and connection budgets; it does not cure CPU-heavy SQL. Both databases currently use a Burstable SKU. Azure's built-in PgBouncer is not supported on that tier, so the decision must compare a supported database tier with a separately operated proxy, including availability, TLS/authentication, transaction/session behavior, observability, and cost. Validate migration and session-state compatibility before switching traffic. [Microsoft PgBouncer documentation](https://learn.microsoft.com/en-us/azure/postgresql/connectivity/concepts-pgbouncer), [connection-pooling guidance](https://learn.microsoft.com/en-us/azure/postgresql/flexible-server/concepts-connection-pooling-best-practices).

## 5. Acceptance and release evidence

The targets below are proposed release gates, not claims about current performance. Freeze the load profile and approved capacity envelope before implementation is signed off.

| Test | Required evidence |
|---|---|
| Incident reproduction | Real PostgreSQL, API pool 10, static 6,916-row inventory, duplicate mounted consumers, concurrent jobs/HITL/decision/queue-estimate polls, and queued discovery submission. Show the baseline failure or identify the additional measured latency/concurrency needed; do not claim a reproduction from SQLite or mocked responses |
| Normal-load regression | At least 30 minutes and 1,000 submission attempts across 20 isolated synthetic owners, with representative background worker reads/writes. Every valid submission accepted within the declared capacity envelope; no pool-generated 500s, duplicate jobs, orphan scan records, or unintended supersession. Proposed submission p95 ≤2 s and p99 ≤5 s |
| Deliberate overload | Controlled connection holds, slow SQL, and worker/read bursts. Prompt structured 503 when outside the envelope; no unbounded waiting. Recovery within 30 seconds after pressure clears. All deliberately rejected attempts are counted as failures, not removed from the SLO denominator |
| Commit ambiguity | Drop the response after durable commit; retry the same key; exactly one job returned. Fail before commit; no job and no prior-run cancellation |
| Client sharing | DOM tests mount actual consumer combinations, use fake timers, and assert shared polls, seven inventory pages per refresh, no overlap, bounded retry, hidden-tab pause, owner-switch cleanup, and correct stale/unknown display |
| Connection lifecycle | Concurrent first-use creates one pool per process; cancellation, rollback failure, broken sockets, and timeouts do not leak capacity. In-use returns to baseline after a burst |
| Rollout | Concurrent revision startup under load produces no schema deadlocks; old/new code remain compatible; drain preserves durable jobs and budget includes overlapping revisions |
| Telemetry failure test | Exhaust the application pool and prove an incident remains visible without that pool; alert/event counts match failed requests; no personal data leaks |
| Capacity sign-off | Approved maximum topology fits server budget plus reserves. Proposed steady database CPU target <70% and no >85% ten-minute interval during representative soak; revise targets explicitly if evidence supports a different envelope |

Use synthetic local fixtures and a controlled connector stub for scale tests; separately test the real Drive path in an approved staging account. Do not generate load or document changes in production. Exercise 30,000-row inventory as a supported-size boundary in addition to the incident fixture — that is `MAX_PAGES × PAGE_LIMIT` in `discoveryInventory.js`, so it is the client's real ceiling, not an arbitrary number.

Run applicable backend and frontend suites with complete dependencies. For changes under the repository's rule paths, the backend CI evidence includes pytest and all three matrix/TODO/progress guards, with required commit trailers. Frontend branch verification must use DOM-level Vitest checks; the shared preview server does not prove worktree changes.

## 6. Delivery and rollout

1. **Evidence and containment — platform/backend:** retain staging logs; establish request/pool/SQL timing; review CPU pressure and top queries; calculate current and rollout budgets. Prepare, but do not silently apply, an API-only pool trial and any database tier proposal.
2. **Submission protection — backend/frontend:** structured overload contract, atomic acceptance/supersession, persistent idempotency keys, truthful UI, bounded read admission, and independent incident emission. Ship fixtures with fixes.
3. **Read efficiency — backend/frontend:** shared jobs/inventory reads, narrow inventory authorization, measured SQL improvements, freshness and tenant-isolation regressions.
4. **Deployment protection — platform/backend:** single-run migrations, startup and drain tests, capacity enforcement, and complete staging observability.
5. **Staging soak, then approved production canary — QA/platform:** pass the acceptance matrix; begin with limited traffic where supported; verify 30 minutes before expansion and review a 24-hour production window. Do not mistake a quiet canary for the representative load test.

Stop expansion or revert the changed setting/revision for any lost/duplicate job, false submission acknowledgement, cross-owner data, new startup deadlock, or sustained breach of the declared latency/CPU envelope. A pool trial also rolls back if it raises CPU/lock pressure or worsens submission latency. Preserve accepted jobs; do not delete scan data to recover. Keep migrations additive and rollback-compatible. If the preceding revision is also overloaded, rollback is containment, not resolution.

## 7. Non-goals and open decisions

No worker-queue replacement, blanket worker scaling, automatic production configuration change, destructive schema change, or source-document modification is part of this PRD. Do not reintroduce deliberately retired UI components to implement Monitor status — see the retired-component list in `CLAUDE.md`, which `unmountedComponents.test.jsx` enforces.

Before release, resolve: top CPU-consuming statements and lock holders; actual process/replica topology during overlap; whether pool creation or hold-time leaks contribute; the supported concurrent-user/SLO envelope; telemetry storage and named alert owners; database tier/proxy cost; and migration SQL responsible for the sampled deadlocks.

### 7.1 Open-PR overlap clearance — closed 30 August 2026

The draft recorded overlap clearance as incomplete because GitHub's shared API budget
was exhausted during the analysis session. It has since been run against the five open
PRs on this repository:

| PR | Touches | Overlap |
|---|---|---|
| [#1045](https://github.com/jeremyyuAWS/acp/pull/1045) | `api/store.py`, `api/app.py`, `tests/test_db_pool*.py` | **Direct — merged as `fb754290`.** Landed H-01 and the 503 half of H-05, plus an incident-reproduction test close to the §5 first row. H-02 was not run against it; see the H-01 note. |
| [#1040](https://github.com/jeremyyuAWS/acp/pull/1040) | `orchestration_events`, `worker_instances` tables | **Adjacent.** New tables arrive through the same `init_schema` path H-15 identifies as the startup-deadlock site. Sequence H-15 with it. |
| [#1041](https://github.com/jeremyyuAWS/acp/pull/1041) | auto-merge hold label | None. |
| [#790](https://github.com/jeremyyuAWS/acp/pull/790) | Power BI DirectQuery export | None. |
| [#787](https://github.com/jeremyyuAWS/acp/pull/787) | 1.3.5 detectors | None. |

No open PR touches `api/routes/system.py`, `api/routes/scans.py`,
`frontend/src/Discover.jsx` or `frontend/src/discoveryInventory.js`, so H-03, H-04 and
H-07 through H-09 are unclaimed. Re-run this clearance immediately before implementation
begins: it is a snapshot, not a standing fact.

## 8. Reproducible evidence

The `evidence/` bundle described by the analysis session — fixed-window KQL queries, JSON results, non-secret app configuration, staging console samples, database metric series, and a representative deadlock traceback — **is not checked into this repository.** It contains resource, job, and scan identifiers, and folder identifiers were redacted from the copied logs but nothing else was. It should be attached to the review through the internal operational-evidence channel rather than committed here; this section records what that bundle must contain so the analysis can be reproduced.

- `revision-errors.json` and `.kql`: revision-level exception counts versus text mentions.
- `http-summary.json`, `failed-requests.json`, and their queries: response denominators and failed routes.
- `incident.json` and `.kql`: timestamped preflight/submission/polling sequence.
- `worker-incident.json`, `other-errors.json`, `deadlock-sample.json`: separate worker/startup failure evidence.
- `*-config.json`, `*-tail.jsonl`: sampled app configuration and staging logs.
- `mdk-accessibility-pg-metrics.json`, `acp-staging-db-metrics.json`, `prod-cpu-credits.json`: one-minute resource metrics.

Server parameter reads verified production `max_connections=150` (user override) and staging `50` (system default). Environment configuration reads verified production Log Analytics workspace `3e4c5202-f541-41ea-ab71-a677d91cf38e`; staging returned a null log destination and no environment diagnostic settings. Those control-plane responses were reviewed in the analysis session. Log Analytics event timestamps and metric buckets are not precise request start/end timings; correlation requires the instrumentation specified above.
