# PRD — Work-Hours Capacity Scheduling and Queue Autoscaling

**Status:** Recommended  
**Owner:** Platform Operations  
**Product area:** Settings → Scheduling; Monitor → Workers & Queue  
**Decision:** Maintain higher warm worker floors during configured work hours while keeping
queue-driven autoscaling active at all times.

## 1. Summary

ACP should let platform administrators define the hours when users normally work. During that
window, ACP keeps additional Discover, Assess, and Remediate workers ready so accepted work starts
quickly. Outside the window, ACP returns to a lower-cost safe baseline. Queue-driven autoscaling
remains active in both modes, so unexpected work can add capacity at any hour.

The schedule is a **soft minimum**, not a fixed replica count or a shutdown instruction. When a
work-hours window ends, ACP releases the higher warm floor but keeps every replica that owns work
until its queue is drained or its work has reached a durable handoff point. The service ceiling,
database capacity, CPU quota, provider limits, and safe drain behavior remain authoritative.

Scheduling capacity must not schedule scans. Existing scheduled content sweeps remain a separate
feature and must execute once per due interval regardless of how many API or worker replicas are
running.

## 2. Problem

Low fixed worker counts reduce idle cost but make the first work of the day wait for cold starts.
High fixed counts improve responsiveness but waste capacity overnight. Queue-only autoscaling
cannot fully remove this delay because it observes work after users have submitted it and the
platform still needs time to start and ready a replica.

The current repository contains most policy-building and validation primitives, but a saved
capacity schedule is not applied or reconciled with Azure. Manual overrides similarly change
stored intent without changing running capacity. Separately, each API and worker process starts
an in-process scheduler for scheduled content sweeps. Autoscaling therefore increases the number
of processes capable of launching the same sweep.

## 3. Product outcome

During expected usage hours, users get warm capacity and short queue waits. During unexpected
bursts, the fleet scales beyond its scheduled floor. During quiet periods, excess replicas drain
safely and scale down. Operators can prove which mechanism requested capacity and whether the
platform delivered it.

### Success metrics

- At least 95% of jobs submitted during work hours are claimed by a compatible worker within
  15 seconds when the fleet is below its configured ceiling.
- At least 99% are claimed within 60 seconds, excluding documented provider throttling or a
  fleet-wide safety guard.
- Scheduled floors are ready no later than the configured work-hours start.
- A queue burst begins requesting additional capacity within 30 seconds of claimable work
  exceeding the lane threshold.
- No scheduled transition creates a new application revision.
- Scale-down loses or duplicates zero accepted jobs.
- One due content sweep produces one durable sweep execution, independent of replica count.
- At least 80% of autoscaled replica-minutes perform useful work after the initial tuning period.

## 4. Users and permissions

- **Platform administrator:** view, validate, save, apply, disable, and temporarily override a
  capacity schedule.
- **Operations viewer:** inspect the effective mode, desired and observed capacity, next
  transition, scaler health, safety guards, and drift.
- **Ordinary user:** sees queue status and useful wait estimates, but no infrastructure controls.

Backend authorization is authoritative. Every mutation and application attempt is audited.

## 5. Administrator experience

Settings → Scheduling provides:

- enabled/disabled state;
- IANA timezone;
- active weekdays;
- work-hours start and end;
- work-hours and off-hours floors per service;
- maximum replicas per service;
- queue scaling thresholds;
- a validation preview showing database connections, vCPU demand, and deployment overlap;
- saved version, applied version, last successful reconciliation, and configuration drift;
- temporary overrides with a reason and explicit expiry.

Saving records desired configuration. Applying publishes it to Azure. The UI must distinguish
**Saved**, **Applying**, **Applied**, **Drifted**, and **Apply failed**; it must never describe a
saved-only schedule as active.

Monitor → Workers & Queue remains read-only and shows:

- current mode and next transition;
- ready, starting, busy, and draining replicas per role;
- scheduled floor, queue-requested replicas, observed replicas, and maximum;
- current queue depth and oldest claimable job age;
- the active scale reason: scheduled, queue, manual override, deployment, or safety-limited.

## 6. Scaling behavior

### 6.1 Work-hours floor

For each service:

`desired replicas = min(maximum, max(active scheduled floor, queue demand, protected capacity))`

`protected capacity` is the capacity currently required by claimed jobs and replicas in the
draining state. It prevents the end of a cron window from being interpreted as permission to
terminate a busy replica.

The off-hours floor is the platform minimum. A KEDA cron rule requests the work-hours floor during
the configured local-time window. The rule carries the IANA timezone so daylight-saving changes
do not require schedule edits.

Transitions are evaluated by the scaling platform. ACP must not call `containerapp update` at the
start or end of every workday. The end transition only removes the work-hours floor from the
calculation; it does not issue a stop, restart, or replacement operation.

### 6.2 Queue autoscaling

Discover, Assess, and Remediate have separate queue signals because their work has different
costs. A scaler counts only jobs the role can claim now:

- queued status;
- `run_after` is due;
- attempts remain;
- job type is supported by that role;
- tenant or provider admission controls permit progress.

Initial thresholds remain configurable starting values, not performance claims:

| Role | Initial work per additional replica | Maximum decision delay |
|---|---:|---:|
| Discover | 4 claimable jobs | 30 seconds |
| Assess | 8 claimable jobs | 30 seconds |
| Remediate | 4 claimable jobs | 30 seconds |

Oldest claimable job age acts as a second trigger so a small stalled queue still scales. Thresholds
must be tuned from observed queue wait and replica utilization after rollout.

### 6.3 Readiness and scale-up

A starting replica does not count as available capacity until it reports its role, build version,
pool size, and readiness. The scaler and wait estimator must subtract ready idle slots, not merely
running replicas, from demand.

Work-hours warming should begin early enough that workers are ready at the configured start. The
system derives this lead time from the rolling p95 cold-start duration, bounded between one and
ten minutes. Until enough measurements exist, use a five-minute lead.

### 6.4 Safe scale-down

When demand or the scheduled floor falls:

1. Recalculate desired capacity with claimed work included as protected capacity.
2. Select only idle excess replicas as scale-down candidates.
3. Mark candidates draining and prevent them from claiming new work.
4. Allow active handlers to finish or reach a durable handoff checkpoint.
5. Persist and requeue safely when a job cannot finish inside the drain window.
6. Report the replica as safe to remove only after it owns no running job and has no live lease.
7. Let the platform remove only replicas carrying that safe-to-remove signal.

Use a five-minute stabilization window initially. The termination grace period remains a final
recovery boundary for crashes and infrastructure eviction; it is not evidence that an ordinary
cron scale-down drained successfully. A scale-down must never interrupt or requeue an active
document solely because work hours ended.

The queue-depth trigger alone is insufficient for scale-in safety because a queue can contain
zero waiting rows while every replica is still processing claimed work. The production policy
must therefore include an active-work/protected-capacity signal, or use a controller that performs
the drain handshake before lowering replica count. Until one of those mechanisms is verified,
work-hours scale-up may be enabled but automatic cron-driven scale-down must remain disabled.

### 6.5 Safety limits

Before saving and immediately before applying, validate the worst attainable fleet against:

- PostgreSQL connection demand, including old/new revision overlap and operational reserve;
- Container Apps environment vCPU quota;
- per-service CPU and memory limits;
- worker threads and database pool size per replica;
- provider concurrency and rate limits;
- required scaler credentials and readable queue queries.

An unknown database ceiling or vCPU quota blocks capacity increases. It may not be treated as a
warning when applying a larger fleet.

## 7. Control-plane architecture

### 7.1 Persistent policy

Each worker service receives one complete scaling policy:

- `minReplicas`: off-hours floor;
- `maxReplicas`: validated ceiling;
- cron trigger: work-hours floor;
- PostgreSQL triggers: claimable depth and oldest claimable job age.
- protected-capacity trigger or drain controller: retains replicas that own active work after the
  cron floor ends.

The apply operation submits the complete intended rule set atomically per service. It must not
append a new rule with a guessed name or accidentally remove an existing out-of-band rule.
Discovery remains blocked from application until its observed Azure rule is imported and assigned
a durable identity.

### 7.2 Desired, applied, and observed state

Persist separately:

- desired schedule version;
- last successfully applied schedule version;
- canonical applied policy digest per service;
- Azure-observed policy digest;
- application status, actor, correlation ID, timestamps, and error summary.

A bounded reconciler retries transient apply failures with exponential backoff. Validation errors
and authorization errors do not retry. Reconciliation reads observed state after applying and
marks success only when the canonical policies match.

### 7.3 Temporary overrides

An override changes the effective floor without becoming permanent. It requires a reason, actor,
expiry, and validated capacity. Because KEDA cron rules cannot express a short arbitrary override
without a policy change, ACP must either:

- use a supported external demand signal that can publish the temporary floor without a revision;
  or
- clearly defer overrides until that mechanism is available.

Stored-only overrides are not considered supported.

## 8. Scheduled content-sweep isolation

Autoscaling must not multiply scheduled scans. Replace process-local execution with a durable,
idempotent enqueue operation:

- calculate an occurrence key from schedule ID and due window;
- insert one `scheduled_sweep` job under a database uniqueness constraint;
- let the normal queue claim exactly one execution;
- record skipped, succeeded, and failed outcomes against that occurrence;
- allow another worker to recover the job through the existing lease mechanism.

API and worker replicas may all observe that a sweep is due, but duplicate inserts must converge
on the same job. APScheduler's process-local `max_instances` is not a fleet-wide guarantee.

## 9. Queue-query performance

Queue scaler queries execute frequently and must remain index-backed as job history grows.

- Store `run_after` and `created_at` as native PostgreSQL `timestamptz`, or add matching expression
  indexes while migration is pending.
- Add a claimability index covering status, role/job type, due time, priority, and attempts as
  supported by measured query plans.
- Keep completed-job retention from bloating the active queue table.
- Run `EXPLAIN (ANALYZE, BUFFERS)` against a production-sized fixture for every scaler query.
- Alert when a scaler query exceeds 250 ms or when its plan stops using the intended index.

## 10. Observability and tuning

Record a durable scale event when desired or observed capacity changes:

- service and schedule version;
- trigger and reason;
- scheduled floor, queue depth, oldest age, and requested replicas;
- claimed jobs, protected replicas, drain candidates, and safe-to-remove replicas;
- observed replicas, ready time, and cold-start duration;
- database/vCPU/provider guard state;
- scale-up utilization and scale-down drain result.

Dashboards report p50/p95/p99 queue wait by role, cold-start duration, jobs per replica-hour,
useful autoscaled replica-minutes, drain duration, and safety-limited demand. After at least one
week of representative traffic, tune each role independently. Raw queue depth alone is not enough
to justify changing a threshold.

## 11. Failure behavior

- If schedule storage is unavailable, Azure retains the last applied policy.
- If reconciliation fails, desired state remains saved and the UI reports drift and the failure.
- If queue telemetry is unavailable, retain the scheduled floor and block further demand-based
  scale-up rather than guessing.
- If a safety limit cannot be evaluated, preserve current capacity but block increases.
- If a scale-down drain times out, retain or safely recover the affected work.
- If a scheduled sweep insertion races, the uniqueness constraint selects one execution.
- No failure may delete accepted jobs or silently substitute a different content source.

## 12. Rollout

### Phase 1 — Correctness foundations

- Make scheduled sweeps fleet-singleton and idempotent.
- Verify native or expression indexes for scaler queries.
- Import and identify every existing Azure scale rule, including Discovery.
- Add durable desired/applied/observed policy state.

### Phase 2 — Staging application

- Implement admin-only apply and bounded reconciliation.
- Publish combined cron and queue policies to staging.
- Exercise a work-hours transition without creating a revision.
- Exercise an overnight burst and a scale-down with active work.
- Prove that ending a cron window with an empty waiting queue and active claimed jobs removes no
  busy replica.

### Phase 3 — Production canary

- Enable one worker role with conservative floors and ceilings.
- Observe at least one week of queue waits, cold starts, utilization, and drain events.
- Expand to remaining roles only after safety and latency targets hold.

### Phase 4 — Tune and automate

- Tune per-role thresholds and cooldowns from measured outcomes.
- Enable temporary overrides only when they change runtime capacity without an unsafe revision.
- Add holiday optimization only if its measured savings justify the policy complexity.

## 13. Acceptance criteria

1. An administrator can configure work hours, timezone, days, floors, ceilings, and thresholds.
2. Validation blocks a floor above its ceiling and any database- or vCPU-unsafe fleet.
3. Saving does not imply application; the UI reports desired and applied versions separately.
4. Applying publishes one complete, reviewed policy per service and verifies it by readback.
5. Work-hours capacity is ready by the configured start across daylight-saving transitions.
6. Queue autoscaling can exceed the scheduled floor during and outside work hours.
7. An idle fleet returns to its safe off-hours floor after the stabilization and drain windows.
8. No normal daily transition creates an Azure Container Apps revision.
9. Ending work hours while jobs are claimed retains their owning replicas until every job finishes
   or completes a durable handoff.
10. A zero waiting-queue depth is not treated as safe scale-in while claimed work remains.
11. A scheduled sweep executes once when the fleet has one replica and once when it has many.
12. Scaler SQL uses the expected index on a production-sized fixture and completes within 250 ms.
13. Monitor shows scheduled, queue, manual, deployment, draining, below-floor, and safety-limited
    states.
14. A failed apply, drift, broken scaler, or unknown safety limit is visible and actionable.
15. Every mutation, apply, reconciliation, override, and validation rejection is audited.
16. Staging demonstrates zero lost or duplicated jobs during scale-up and scale-down.
17. Production meets the queue-wait objectives for one representative week before thresholds are
    declared tuned.

## 14. Non-goals

- Scheduling when scans or remediation campaigns execute.
- Per-user infrastructure schedules.
- Automatically purchasing cloud quota or resizing PostgreSQL.
- Guaranteeing completion time for a specific document.
- Scaling required state services to zero.
- Treating an unmeasured threshold as an optimized value.
