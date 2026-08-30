# PRD — Automatic Worker Provisioning and Transparent Job Processing

**Product:** ACP
**Scope:** Discover, Assess, Remediate, and Monitor
**Status:** Proposed
**Purpose:** Replace user-managed worker controls with reliable automatic processing and clear, evidence-based job visibility.

> **Relationship to the other reliability PRD.** This supersedes nothing in
> [`prd-reliability-hardening.md`](prd-reliability-hardening.md) but subsumes its scope: that
> document's H-01…H-16 map onto the phases below (see §13). Where the two disagree, **this
> document is the later decision** — §13 records the one place they actually conflict.
>
> §13 also records which requirements were checked against `origin/main` on 2026-08-30 and what
> was found, so the phase plan starts from the code as it is rather than as assumed.

## 1. Problem

Users submit jobs but cannot reliably tell:

- Whether the request was accepted.
- Why it is waiting.
- Whether workers are available, starting, or unhealthy.
- When processing is likely to begin.
- Whether displayed progress is current.
- Whether retrying will create duplicate work.

Manual worker-count controls expose infrastructure decisions to users who should only need to choose their documents and start work.

Increasing worker counts or database connection pools alone does not solve this problem. Unbounded concurrency can overload the database and make processing slower.

## 2. Product outcome

**Users request work; ACP supplies processing capacity automatically and explains what is happening.**

Users never need to provision workers, choose concurrency, or understand Azure infrastructure to complete a job.

### Success criteria

- Every accepted request has a durable job ID.
- Retrying the same submission does not create duplicate work.
- Eligible queued jobs trigger capacity independently of browser activity.
- Worker and database concurrency remain within validated limits.
- Discover, Assess, Remediate, and Monitor show consistent job states.
- Every live status identifies its freshness.
- Unavailable telemetry appears as **unknown**, not zero or healthy.
- No ordinary user-facing worker scaling controls remain.

## 3. Recommended capacity strategy

### Initial release: warm baseline plus queue-driven scaling

Maintain a small, configurable baseline of ready workers, initially proposed as one replica where its capabilities and database budget permit.

Increase capacity based on:

- Eligible queued jobs by processing capability.
- Age of the oldest eligible job.
- Available processing slots.
- Database and external-provider constraints.

The baseline and maximum capacity require staging validation and cost approval before deployment.

### Subsequent optimization: activity-based warming

If reducing idle cost justifies scaling to zero, introduce authenticated activity-based warming:

1. Successful login requests a short-lived warm-capacity reservation.
2. Opening Discover, Assess, or Remediate can refresh that reservation.
3. Multiple users or tabs share bounded capacity; they do not receive one worker each.
4. Reservations expire without continued relevant activity.
5. Queued and running jobs take precedence over reservation expiry.

Warm-up must be asynchronous and must not delay sign-in.

**Login is an optimization — not a prerequisite for job processing.** Scheduled jobs and jobs submitted through an API must work without an active user session.

## 4. Functional requirements

### A. Safe job acceptance

- Persist the job before returning an accepted response.
- Return a job ID, request ID, acceptance timestamp, and current state.
- Make creation of a replacement scan and supersession of the previous scan atomic where they must succeed together.
- Preserve the previous usable inventory if submission fails.
- Support owner-scoped idempotency keys for retried requests.
- Provide a way to reconcile an uncertain submission after a timeout.

Responses must distinguish:

- **Accepted:** durable job exists.
- **Not accepted:** confirmed that no job was created.
- **Acceptance unknown:** client must reconcile before resubmitting.

Do not use a global "No changes were made" message unless the specific operation can prove it.

### B. Automatic capacity management

- Remove ordinary-user worker count and start/stop controls.
- Use a backend-controlled capacity policy.
- Respect maximum replicas, processing concurrency, database budget, and provider limits.
- Distinguish worker capabilities so Discover capacity is not falsely reported as available for an incompatible Remediate job.
- Recover from zero workers through a mechanism that does not depend on those workers already running.
- Avoid conflicting scaling controllers.
- Apply cooldown and stabilization rules to prevent repeated startup/shutdown cycles.

Activity-based warming must be authenticated, deduplicated, rate-limited, and bounded by the same capacity limits.

### C. Database protection

Define a validated fleet-wide connection budget:

**API connections + worker connections + deployment overlap + operational reserve ≤ usable database capacity**

Requirements:

- Configure API and worker pool limits explicitly by role.
- Include maximum replica counts and overlapping revisions.
- Do not increase all pool sizes indiscriminately.
- Measure connection acquisition wait, hold duration, timeouts, and utilization.
- Investigate slow queries, CPU pressure, and lock contention.
- Bound database waits and retry attempts.
- Reduce or defer new processing when dependencies are saturated.
- Load-test against real PostgreSQL, not only mocked connection pools.

### D. Reliable execution and recovery

- Use durable claims, leases, and worker heartbeats.
- Detect and recover abandoned jobs.
- Prevent an expired worker from publishing results after another worker has taken ownership.
- Make retried work safe against duplicate side effects.
- Use bounded retries with backoff for temporary failures.
- Display retry reason and next eligible attempt time.
- Drain workers during deployment and scale-down.
- Preserve failure evidence rather than automatically clearing failed jobs.

A job waiting for a retry must not be presented as simply waiting for a free worker.

## 5. User experience

### Placement

- **Discover, Assess, Remediate:** compact, job-specific status card.
- **Monitor:** detailed job timeline, worker capacity, and Azure diagnostics.
- **Administrator settings:** capacity policy and audited emergency overrides.
- **Scan Analytics:** historical performance trends, not primary live operations.

"View activity" opens Monitor filtered to the originating job or scan.

### Job card

Display:

- Current job state.
- Waiting or elapsed time.
- Plain-language explanation of any delay.
- Relevant processing capacity.
- Latest progress and its timestamp.
- Pickup estimate when supportable.
- Cancel action where cancellation is supported.
- Link to detailed activity.

Example, using illustrative values:

> **Discovery queued**
> All eligible processing slots are busy.
> 2 workers ready · 4 slots busy · 1 additional worker starting
> Waiting 24 seconds · worker status updated 3 seconds ago
> **View activity**

Counts must have a clearly defined scope. Never subtract one customer's running jobs from a shared fleet count to infer global availability.

### Separate job state from capacity state

| Job state | Meaning |
|---|---|
| Queued | Durably accepted, not claimed |
| Assigned | A worker holds a valid claim |
| Processing | Worker has reported processing activity |
| Retry scheduled | Waiting until the next eligible attempt |
| Completed | Results durably finalized |
| Failed | No automatic attempts remain |
| Cancel requested / Cancelled | Cancellation requested versus confirmed |

| Capacity state | Meaning |
|---|---|
| Capacity requested | ACP requested additional capacity |
| Starting | Azure reports startup activity |
| Ready | Application-level readiness and heartbeat confirmed |
| Busy | Processing slots occupied |
| Draining | No new jobs accepted by this worker |
| Unavailable / Unknown | Confirmed failure versus missing evidence |

Container existence alone must not imply readiness.

### Queue position and estimates

- Show exact position only when scheduling policy supports a meaningful ordering.
- Otherwise show "jobs ahead in your processing queue" or a plain-language waiting reason.
- Account for priority, capability, delayed retries, and concurrent processing.
- Do not expose other customers' job details.
- Provide estimated pickup ranges using relevant historical observations.
- Show "Estimate unavailable" when evidence is insufficient.
- Never present an estimate as a guaranteed countdown.

### Live activity

Initially show available, truthful signals:

- Files discovered or processed.
- Folders visited.
- Recent observed throughput.
- Last progress event.
- Worker heartbeat freshness.

Folder trees require backend folder-level events before implementation.

For parallel traversal, show multiple active folders rather than inventing one serial "current folder." Distinguish a folder's own listing completion from completion of its entire subtree.

Use brief, subtle highlights when counters change. Respect reduced-motion preferences, avoid flashing, and do not announce every increment to screen readers.

## 6. Azure integration

ACP must correlate its application signals with Azure infrastructure signals.

### Application signals

- Durable queue and job state.
- Worker identity and capabilities.
- Valid claim and attempt identity.
- Heartbeat and readiness.
- Active and available processing slots.
- Progress and retry events.

### Azure signals

Where supported and verified:

- Replica and revision state.
- Provisioning and startup activity.
- Restarts and termination.
- Resource utilization.
- Relevant platform errors.
- Scaling configuration and observed capacity.

Azure Monitor supplies diagnostic context; delayed platform telemetry must not replace the durable queue as the authority for job acceptance or ownership.

Requirements:

- Read Azure through the backend using least-privilege credentials.
- Never expose Azure credentials to the browser.
- Cache and share platform reads.
- Timestamp each telemetry source independently.
- Distinguish an unsuccessful Azure query from zero workers.
- Provide permission-appropriate diagnostic links in Monitor.
- Verify actual API response shapes through the staging validation workflow.

Read-only validation and infrastructure-changing configuration must remain separate operations.

## 7. Durable orchestration history

Record significant lifecycle events in an append-oriented audit stream:

- Job accepted.
- Capacity requested.
- Worker registered and ready.
- Job claimed.
- Processing started.
- Progress milestone.
- Retry scheduled.
- Lease expired and job recovered.
- Cancellation requested and completed.
- Job completed or failed.
- Worker draining or unavailable.

Each event should include:

- Event ID and timestamp.
- Tenant/owner and environment.
- Job, scan, request, and attempt identifiers as applicable.
- Worker identity.
- Event type and reason code.
- Sanitized details and correlation identifiers.

Persist job-state transitions and their audit events atomically where appropriate. Use an independent operational logging path for database failures so exhausted database capacity does not erase evidence.

Do not store document contents, credentials, or unnecessary sensitive paths in diagnostics.

## 8. Performance and freshness

- Share job-status subscriptions across components.
- Avoid separate polling loops for the same information.
- Support resumable live updates, with polling fallback if needed.
- Mark disconnected or stale information explicitly.
- Keep last-known information visible with its timestamp.
- Bound event volume; aggregate frequent progress updates.
- Prevent inventory pagination and telemetry reads from starving job submission.

Proposed initial target: application job-state changes become visible within five seconds under normal conditions. Validate this target in staging.

Measure Azure observation delays separately; do not imply Azure telemetry has the same freshness.

## 9. Acceptance tests

Release requires evidence that:

1. A submitted job progresses without a user manually starting workers.
2. A job can trigger processing from zero capacity without an active browser.
3. Simultaneous logins do not create unbounded warm-up requests.
4. Duplicate submissions produce one logical job.
5. Failed replacement submission preserves the prior usable scan.
6. Lost responses can be reconciled without duplicate work.
7. Database saturation produces an accurate, actionable response.
8. A killed worker's job is safely recovered.
9. An expired worker cannot overwrite the replacement worker's result.
10. Scale-down does not silently discard active work.
11. All workflow tabs agree on job state.
12. Azure/API failures display unknown or stale capacity — not false readiness.
13. Real PostgreSQL load tests stay within the approved connection budget.
14. Cross-tenant tests prevent disclosure of other customers' jobs and diagnostics.
15. No ordinary user interface exposes worker scaling controls.

## 10. Delivery phases

### Phase 1 — Submission and database safety

Atomic acceptance, idempotency, truthful errors, connection budgets, and real database load tests.

### Phase 2 — Automatic capacity

Validated warm baseline, queue-driven scaling, lease recovery, safe draining, and removal of user controls.

### Phase 3 — Unified transparency

Worker registry, orchestration events, consistent job cards, freshness, and job-focused Monitor.

### Phase 4 — Azure verification and diagnostics

Live staging comparison, retained diagnostics, infrastructure correlation, and operational alerts.

### Phase 5 — Optimizations

Activity-based warming if justified, evidence-based pickup estimates, folder-level activity, and historical tuning.

## 11. Operational measurements

Track by environment and job type:

- Queue-to-claim latency: median and p95.
- Claim-to-first-progress latency.
- Capacity-request-to-ready latency.
- Oldest eligible queued-job age.
- Worker utilization and startup failures.
- Database acquisition waits and timeouts.
- Retry, recovery, and terminal failure rates.
- Duplicate-job prevention.
- Telemetry freshness and delivery delay.
- Idle-capacity cost and cost per completed job.

Establish a baseline before rollout and define approved latency and cost targets from staging measurements.

## 12. Release boundaries

This PRD does not authorize production scaling, database resizing, additional Azure permissions, or unrestricted spending.

Those changes require an approved configuration and rollout plan. Keep independent workstreams coordinated around shared queue, store, and UI contracts.

**Definition of done:** A user starts Discover, Assess, or Remediate without infrastructure controls; ACP safely provisions or assigns capacity, executes the job, recovers from failures, and provides an accurate explanation throughout.

## 13. Starting position — verified against `origin/main`, 2026-08-30

Checked by running or reading the code at `origin/main`, not from the earlier PRD's assumptions.
Nothing in this section changes the requirements above; it records where Phase 1 actually starts.

### 13.1 Already shipped

| Requirement | State |
|---|---|
| §4.C *"Configure API and worker pool limits explicitly by role"* | **Partly.** `fb754290` (#1045) decoupled the pool from `ACP_WORKERS`. It is still ONE formula for every role — see 13.3. |
| §4.A *"Persist the job before returning an accepted response"* | **Yes.** `enqueue_scan` commits `scan_runs` + `jobs` + `scan_inputs` in one transaction. |
| §4.A *"Preserve the previous usable inventory if submission fails"* | **Yes, as of #1051.** It was not true before: supersession committed 46 lines ahead of `enqueue_scan`, so a failure between them destroyed the prior run and created nothing. |
| §4.A *"owner-scoped idempotency keys"* | **Server side only.** `enqueue_scan` honours `Idempotency-Key`; #1051 stopped a replay from superseding the scan it returns. **The frontend sends no key at all** — `frontend/src/api.js` has no `Idempotency-Key`, so acceptance test 4 cannot pass today. |
| §8 *"Prevent inventory pagination … from starving job submission"* | **Improved, not done.** #1051 removed an 8.0× read amplification from the inventory gate; the polling duplication in §13.2 remains. |

### 13.2 Confirmed gaps, with the evidence

- **Acceptance test 15 fails in three places.** `setWorkers()` is wired to ordinary-user surfaces —
  `Discover.jsx:300`, `AssessRunner.jsx:187`, `QueuePanel.jsx:154` — backed by
  `PUT /workers` (`api/routes/system.py:219`, `count` 0–16). §4.B's "remove ordinary-user worker
  count and start/stop controls" is three call sites and one route, not a redesign.
- **§8 "avoid separate polling loops for the same information" is violated in the same component.**
  `Discover.jsx` runs two independent `/jobs` effects (`:233` filtered to `queued`, `:275`
  unfiltered). Measured cost of one `/jobs` request: **5 connection-pool acquisitions, 6 queries**
  — so a single Discover tick is **10 acquisitions**, and `QueuePanel`, `AssessRunner`,
  `FailureLane` and `FixOutcomes` each add their own.
- **§5 "container existence alone must not imply readiness"** already has partial support:
  `/jobs` returns `worker_tier_alive`, `worker_heartbeat_age_s` and `worker_tier_pool_size`. The
  capacity-state vocabulary (requested / starting / ready / busy / draining / unknown) does not
  exist.

### 13.3 Where this PRD contradicts what shipped — both need a decision

1. **§4.A: "Do not use a global 'No changes were made' message unless the specific operation can
   prove it."** `api/app.py:64` returns exactly that global message, for every route that raises
   `PoolError`. It shipped in #1045 today. Its own handler docstring already concedes the gap:
   the claim holds when the pool fails on a request's first database touch, and not when an
   earlier `cursor()` in the same handler already committed. #1051 makes it true for scan
   submission specifically; it remains unproven for every other route. **Scoping this message per
   operation is Phase 1 work and contradicts code merged the same day.**

2. **§4.A: "Make creation of a replacement scan and supersession of the previous scan atomic where
   they must succeed together."** The earlier PRD's H-03 permitted *either* atomicity *or*
   deferral, and #1051 chose deferral — supersession now runs after `enqueue_scan` commits, and
   cannot fail the request. That closes the destructive case this PRD's §4.A cares about
   ("preserve the previous usable inventory if submission fails") but leaves a millisecond window
   in which both runs exist. If "atomic" here is a hard requirement rather than a description of
   intent, it needs `_end_running_scan` to accept a caller's cursor so the stop joins
   `enqueue_scan`'s transaction. **That is a deliberate, reversible design choice, and it is worth
   confirming which reading is meant before Phase 2 builds on it.**

### 13.4 Carried forward from the earlier PRD

The capacity finding in [`prd-reliability-hardening.md` §4.1](prd-reliability-hardening.md) is
this document's §4.C, unresolved: `max(2, workers + 16)` applied to every role took the fleet
ceiling to **328 against a 150-connection production server** and **70 against a 50-connection
staging server**, staging having been under its limit before. Those are potential ceilings, not
observed counts, and the numbers are the platform owner's to set via `ACP_DB_MAX_CONN` — but
§4.C's budget cannot be called validated until they are.
