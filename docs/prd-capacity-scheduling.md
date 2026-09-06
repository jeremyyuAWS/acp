# PRD — Settings → Scheduling

**Product:** ACP
**Status:** Phases 1–3 implemented; production capacity prerequisite completed 2026-09-06

> **R3 resolved in production (2026-09-06).** PostgreSQL moved from Burstable
> `Standard_B2s` to General Purpose `Standard_D2ds_v4`. The server's explicit
> `max_connections=150` override was raised to the SKU's PostgreSQL 16 default of **859**, and
> `ACP_PG_MAX_CONNECTIONS=859` is published to `acp-app` so validation uses the live ceiling.
> Assess now runs **5–10** with the claimable-work PostgreSQL scaler (8 queued jobs per replica),
> rather than the out-of-band 10–10 pin found immediately before the change. Discovery is 4–6
> and Remediation is 5–10. `/healthz`, `/readyz`, all three worker heartbeats, and the latest
> Container App revisions were healthy after both required PostgreSQL restarts.
**Owner:** Platform Operations
**Scope:** Scheduled warm capacity for Discover, Assess, Remediate, web, and optional GPU services

> **How to read this document.** §1–§15 are the proposal as submitted. §16 is the engineering
> review of it against this repository, and it **changes three things in the body above**:
> placement (§4), the service capacity table (§5.3), and what validation is evaluated against
> (§7). Each amendment is marked inline where it applies. Everything else stands as written.

---

## 1. Summary

Add a **Scheduling** tab to Platform Settings that lets authorized administrators define when ACP
maintains higher warm processing capacity and when it returns to a lower-cost baseline.

Scheduling controls capacity, not scan execution. Existing scheduled re-scans remain in Monitor
and are not moved or duplicated.

ACP will combine:

- A time-based warm-capacity schedule.
- Queue-driven autoscaling at any hour.
- A safe overnight minimum so accepted work continues processing.
- Fleet-wide CPU and database protections.
- Audited manual overrides.

## 2. Problem

ACP currently relies on fixed minimum replica counts or manual capacity adjustments. This creates
two undesirable states: high capacity remains online when little work is expected, and low
capacity must cold-start when users begin work, making Assess and Remediate appear slow.

Manually changing replica settings is also operationally risky. Each Azure Container Apps
configuration update creates a new revision, which can restart workers, interrupt active jobs, and
produce retries.

Administrators need a safe way to express expected operating hours without repeatedly modifying
live infrastructure.

## 3. Product outcome

**ACP is warm when people normally use it, economical when they do not, and still capable of
processing unexpected overnight work.**

### Success criteria

- Administrators can configure business-hour capacity without editing Azure directly.
- Scheduled transitions do not create a new application revision on every transition.
- At least one worker remains available overnight for every required processing role.
- Queue depth can raise capacity beyond the scheduled baseline at any hour.
- Scale-down drains active work instead of terminating it.
- The complete fleet remains within CPU and database connection limits.
- Every schedule change and manual override is audited.
- Users can see the current capacity mode in Monitor without receiving infrastructure controls.

## 4. Navigation and permissions

> **AMENDED — see review finding R1.** The writable surface is **Settings → Scheduling**, placed
> immediately after **Worker Configuration**. **Live Operations gains a read-only capacity-mode
> strip** (current mode, next transition, drift) that links to it, and no control. This keeps the
> repository's existing invariant that capacity CONTROLS live in one place
> (`frontend/src/queuePanelCapacity.test.jsx`) while answering "what mode are we in?" where
> operators already look.

Proposed order:

`Owners · Users · Roles · My Data · My Scope · Worker Configuration · Scheduling · AI Governance · Review Memory`

### Access

- Platform administrators can view and modify schedules.
- Users with view-only Settings access can view the active schedule but cannot change it.
- Ordinary users cannot create overrides or alter capacity.
- Backend authorization remains authoritative; hiding controls in the browser is not sufficient.

## 5. Scheduling tab

### 5.1 Status summary

The top of the tab displays: current mode (**Business hours**, **Off hours**, or **Manual
override**), current local time and timezone, next scheduled transition, current warm replica
targets by service, queue-based scaling status, any configuration or dependency warning, and a
link to **Monitor → Workers & Queue**.

> **Business-hours capacity active**
> Pacific Time · next transition today at 8:00 PM
> Assess 5 warm · Remediate 5 warm · Discovery 2 warm
> Queue scaling remains available up to the validated fleet limit.

### 5.2 Schedule editor

Administrators can configure: enable/disable, timezone (IANA identifier), active days,
business-hours start and end, business-hours warm capacity, off-hours warm capacity, maximum
queue-driven capacity, optional GPU warm behaviour, optional holiday exceptions.

Default timezone: `America/Los_Angeles`. Times are shown and entered in the selected timezone. ACP
must handle daylight-saving transitions without administrators rewriting the schedule.

### 5.3 Service capacity table

> **AMENDED — see review findings R2 and R3.** The table below is the proposal as submitted. It
> **does not fit the production Postgres server** when evaluated at its own business-hours floors
> during a revision overlap: 152 connections plus a 15-connection operational reserve against a
> server that has 150. `tests/test_capacity_budget.py` computes this and fails if it stops being
> true. The maximums are not applicable until the decision in R3 is made.

| Service | Business-hours default | Off-hours default | Maximum |
|---|---:|---:|---:|
| Web app | 2 | 1 | 3 |
| Discovery | 2 | 1 | 4 |
| Assess | 5 | 1 | 10 |
| Remediate | 5 | 1 | 10 |
| GPU vision | 1 | 0 | 1 |

These are proposed initial values, not hard-coded product constants.

Consequence of reducing each off-hours value:

- **Web:** one replica is required for interactive access.
- **Discovery:** one replica permits scheduled and unexpected discovery work.
- **Assess:** one replica keeps accepted assessment jobs moving.
- **Remediate:** one replica keeps remediation and delivery jobs moving.
- **GPU:** zero reduces idle cost but introduces a cold start for the first vision request.

Redis, PostgreSQL, and other required state services are not controlled from this tab.

### 5.4 Manual override

Administrators can temporarily override the schedule: **Use business-hours capacity now**, **Use
off-hours capacity now**, or **Custom temporary capacity**.

Every override requires a duration (30 minutes, 1 hour, 2 hours, 4 hours, or until the next
scheduled transition), a plain-language reason, confirmation showing estimated capacity impact,
and automatic expiry. An override must never silently become permanent. The UI displays who
created the override, why, when it expires, and which schedule will resume afterward.

## 6. Scaling behavior

### 6.1 Scheduled capacity is a floor

The active schedule sets the desired warm baseline. It does not impose a hard processing ceiling.
If queued work exceeds available capacity, queue-driven scaling may increase replicas above the
scheduled baseline, including overnight.

### 6.2 Queue-driven scaling

Discover, Assess, and Remediate use role-specific queue signals. Scaling considers: number of
eligible queued jobs, age of the oldest eligible job, currently available processing slots, retry
eligibility, worker capability, provider throttling, and fleet-wide CPU and database headroom.

An incompatible worker must not count as available capacity for a job.

> **Note — the word "eligible" was doing unfunded work.** As of 2026-09-06 the deployed scalers
> counted every `status='queued'` row. See review finding R4; this is now implemented.

### 6.3 Safe scale-down

At the end of business hours: stop assigning new jobs to excess replicas; allow active jobs to
complete or reach a durable checkpoint; confirm that claims and progress are persisted; remove
excess replicas after the drain window; reclaim abandoned work if a replica fails during drain.

The schedule must not terminate active remediation solely because the business-hours window ended.

### 6.4 No twice-daily configuration deployment

Scheduled transitions must be handled by a persistent scaling policy, such as combined cron and
queue rules. ACP must not run an external script every morning and evening that changes the
Container App template. Such updates create revisions and risk worker restarts.

Publishing or editing the schedule may create one reviewed configuration revision. Ordinary
schedule transitions must not.

## 7. Capacity safety

Before saving, ACP validates the complete fleet:

**API connections + worker connections + deployment overlap + operational reserve ≤ usable
database capacity**

> **AMENDED — see review finding R2.** This must be evaluated against the **worst mode the
> schedule can be in**, not the mode in force at validation time. The deployment-overlap term is
> driven by the FLOORS, and the schedule's whole purpose is to raise floors during business hours.
> `capacity_budget.worst_case_tiers` implements this.

Validation also covers: Azure environment vCPU quota; per-service minimum and maximum replicas;
worker threads per replica; database connections per replica; old/new revision overlap during
deployment; GPU availability; queue scaler configuration; required secrets and authentication.

### Blocking validation

Saving is blocked when a minimum exceeds its maximum; the proposed fleet exceeds the validated
database ceiling; the proposed fleet exceeds the known CPU quota; a required queue scaler is
invalid; a scheduled role could reach zero with no verified mechanism to wake it; or start and end
times form an ambiguous or empty window.

Warnings that do not block saving must state the concrete consequence.

## 8. API contract

### Read schedule — `GET /control/capacity-schedule`

```json
{
  "enabled": true,
  "timezone": "America/Los_Angeles",
  "days": ["mon", "tue", "wed", "thu", "fri"],
  "start": "06:00",
  "end": "20:00",
  "business_hours": {"web": 2, "discovery": 2, "assess": 5, "remediate": 5, "gpu": 1},
  "off_hours":      {"web": 1, "discovery": 1, "assess": 1, "remediate": 1, "gpu": 0},
  "maximums":       {"web": 3, "discovery": 4, "assess": 10, "remediate": 10, "gpu": 1},
  "effective_mode": "business_hours",
  "next_transition_at": "2026-09-07T03:00:00Z",
  "version": 4
}
```

### Update schedule — `PUT /control/capacity-schedule`

Administrator authorization; optimistic concurrency through `version`; server-side validation;
dry-run validation before application; atomic persistence; audited before/after values; explicit
failure when Azure rejects the policy.

### Validate without saving — `POST /control/capacity-schedule/validate`

Returns projected warm replicas, maximum replicas, vCPU requirement, database connection
requirement, deployment-overlap requirement, warnings and blocking errors.

### Manual override

`POST /control/capacity-schedule/override` and `DELETE /control/capacity-schedule/override`.
Overrides include reason, expiry, actor, and requested capacity.

## 9. Source of truth and reconciliation

The durable ACP schedule record is the intended configuration. Azure is the execution platform.
ACP must report both **desired policy** and **observed Azure policy**. If they differ, the
Scheduling tab shows **Configuration drift** rather than claiming the schedule is active.

A backend reconciler may reapply the desired policy after a transient failure, using bounded
retries and an audit trail. It must not retry continuously against an invalid policy.

## 10. Observability

Scheduling remains configuration; live operational details stay in Monitor.

**Settings shows:** desired schedule, effective mode, next transition, validation result, current
override, configuration drift, last successful reconciliation.

**Monitor shows:** current replicas by role, scheduled baseline, queue-requested capacity;
starting, ready, busy and draining replicas; queue age and depth; last scale event and reason;
cold-start duration; database and CPU guard status.

Metrics must distinguish scheduled scale-up, queue-triggered scale-up, manual override, deployment
replacement, and platform restart.

## 11. Audit requirements

Record every schedule creation or edit, enable/disable action, manual override and cancellation,
validation rejection, reconciliation attempt and result, and detected configuration drift.

Audit entries include actor, timestamp, reason, previous value, requested value, outcome, and
correlation ID. Secrets and raw connection strings must never appear in audit data.

## 12. Failure behavior

- If the schedule service is unavailable, retain the last successfully applied policy.
- If the queue scaler fails, show a prominent degraded-capacity warning.
- If Azure telemetry is unavailable, display capacity as unknown.
- If the database guard cannot be evaluated, block capacity increases but preserve the current fleet.
- If a scale-down drain times out, keep the affected replica until its lease is safely recovered.
- If the GPU scales to zero, AI work may wait; deterministic assessment and remediation continue
  where supported.
- A scheduling failure must never delete jobs or accepted work.

## 13. Non-goals

This feature does not schedule scans or remediation runs; replace Monitor's Scheduled re-scans;
guarantee completion by a particular time; allow per-user infrastructure schedules; expose Azure
credentials or raw infrastructure controls; automatically purchase quota or change database server
limits; turn required state services off overnight; or remove post-remediation verification.

## 14. Rollout

### Phase 1 — Safety foundations

- Repair and verify the Remediate PostgreSQL queue scaler.
- Add and verify an Assess queue scaler.
- Establish tested CPU and database fleet limits.
- Confirm graceful worker drain behavior.

### Phase 2 — Read-only Scheduling tab

- Display proposed schedule and observed capacity. Add validation endpoint. Surface configuration
  drift and scaler health. Make no infrastructure changes.

### Phase 3 — Administrator writes

- Enable schedule updates. Add audited temporary overrides. Apply combined cron and queue policies.
  Verify that normal transitions create no new revisions.

### Phase 4 — Optimization

After at least one week of measurements: tune business-hours floors; tune queue thresholds and
cooldowns; decide whether overnight GPU scale-to-zero provides worthwhile savings; add holiday
exceptions if administrators need them.

## 15. Acceptance criteria

1. Settings contains a keyboard-accessible **Scheduling** tab beside Worker Configuration.
2. An administrator can configure timezone, days, hours, service floors, and maximums.
3. A view-only user can inspect the schedule but cannot change it.
4. Pacific-time schedules remain correct across daylight-saving transitions.
5. At the start of business hours, warm capacity reaches its target without a new application revision.
6. At the end of business hours, excess replicas drain before removal.
7. At least one worker per required role remains available off-hours.
8. An overnight queue can scale above the off-hours baseline.
9. CPU or database-unsafe configurations are rejected before saving.
10. A broken queue scaler appears as degraded, not healthy.
11. Manual overrides require a reason and expire automatically.
12. Desired-versus-observed drift is visible.
13. Every mutation produces an audit entry.
14. Monitor identifies whether scaling was scheduled, queue-driven, manual, or deployment-related.
15. Existing Scheduled re-scans continue unchanged and are not duplicated into Settings.
16. Tests verify authorization, optimistic concurrency, DST behavior, overnight processing, queue
    bursts, safe drain, drift, validation failure, and override expiry.
17. A staging exercise demonstrates a complete daytime-to-off-hours transition with no lost or
    duplicated jobs.

---

# 16. Engineering review — 2026-09-06

Reviewed against `main` at `5b6dd6a`. Every number below is produced by code in this repository
and re-derived on every test run; none is carried.

## R1 — Placement contradicted itself, and the repo already had an answer

The request that accompanied this PRD asked for a Scheduling subtab in **Live Operations**. §4,
§10 and AC 1 all specify **Settings**, and §10 draws the line explicitly: Scheduling is
configuration, Monitor is live state.

The repository enforces that line today. `frontend/src/queuePanelCapacity.test.jsx` asserts that
no capacity adjust control renders outside Settings → Worker Configuration, and both
`AssessRunner.jsx` and `Monitor.jsx` point users there in prose. Putting a writable schedule in
Live Operations would be a second writable capacity surface.

**Decision (owner, 2026-09-06):** writable Scheduling tab in Settings; a **read-only capacity-mode
strip** in Live Operations showing current mode, next transition and drift, linking to Settings.
§4 amended.

## R2 — The capacity table does not fit the server, and it fails in the mode nobody validates

**This is the finding that must be resolved before Phase 3.**

The binding term in §7's inequality is not the maximum replica count — it is the deployment
overlap, and **overlap is driven by the floors**. Azure runs the outgoing and incoming revisions
together during a rollout, so the realistic worst case is max-of-new plus min-of-old. A schedule
raises floors during business hours, which is precisely when someone deploys.

Priced with `api/capacity_budget.py` against the reviewed baseline
(`deploy/public/rightsize-production.sh`), a 150-connection server and the 15-connection
operational reserve:

| Shape | Steady | During revision overlap | + reserve | Fits 150? |
|---|---:|---:|---:|:--|
| Reviewed baseline today | 82 | 120 | 135 | yes, 15 spare |
| §5.3 maximums, **off-hours** floors (1/1/1/1) | 96 | 118 | 133 | yes, 17 spare |
| §5.3 maximums, **business-hours** floors (2/2/5/5) | 96 | 152 | **167** | **no, over by 17** |

The middle row is the trap. Validate the mode you happen to be in at 2am and the table passes;
the same table is 17 connections over budget at 10am. `capacity_budget.worst_case_tiers` takes
each tier's largest floor across every mode the schedule can enter — including manual overrides —
and `evaluate` must be called on that. §7 amended.
`tests/test_capacity_budget.py::test_the_prd_capacity_table_fits_at_night_and_that_is_the_trap`
and its sibling pin both halves.

## R3 — Assess autoscaling is blocked by a connection budget, not by missing code

Phase 1 asks for an Assess queue scaler. `acp-assess` runs **5–5**: floor equals ceiling, so a
scale rule attached to it cannot add a replica no matter what it computes, and applying one costs
a revision — a worker restart — for a rule that provably cannot fire.

Raising the ceiling spends the same connections §5.3's floors want, and there was a second claim
on them. **That claim has now landed.** #1533 moved `acp-discovery` from 1–2 to 4–6 on
2026-09-06, spending 14 of the 15 connections that were spare:

| | Steady | During overlap | + reserve | Headroom |
|---|---:|---:|---:|---:|
| Before #1533 | 82 | 120 | 135 | 15 |
| **After #1533 (today)** | **90** | **134** | **149** | **1** |

One connection is not a replica. `acp-assess` is pinned at 2 connections per replica, so the
budget now affords **zero** additional assess ceiling — the question is no longer "how much" but
"where from".

**This needs an owner decision, and it is a capacity-purchasing decision, not an engineering one.**
The options, in order of preference:

1. **Raise the Postgres server's `max_connections`** (a larger SKU). §13 lists this as a non-goal
   for the *feature* to do automatically; it does not forbid the platform owner doing it once.
   This is the only option that does not trade one service's capacity for another's.
2. **Lower the business-hours floors.** Free, but it costs the cold-start latency at 8am that
   this feature exists to remove — and the amounts are small, because the floors are what the
   overlap term is made of. Priced against the §5.3 maximums, all figures during a revision
   overlap plus the 15-connection reserve:

   | Business-hours floors (web/discovery/assess/remediate) | Total | Fits 150? |
   |---|---:|:--|
   | 2 / 2 / 5 / 5 — **as §5.3 proposes** | 167 | no, over by 17 |
   | 1 / 2 / 5 / 5 | 151 | no, over by 1 |
   | 1 / 2 / 4 / 5 | 149 | yes, 1 spare |
   | 1 / 2 / 4 / 4 | 147 | yes, 3 spare |
   | 2 / 1 / 1 / 1 | 149 | yes, 1 spare |

   **The web tier's floor is the expensive one, and this is not obvious from §5.3.** `acp-app`
   holds a 16-connection pool (`ACP_WORKERS + 16`, ADR 0013 — it runs no worker threads but
   serves concurrent HTTP handlers); the three worker apps are pinned at 2 by `ACP_DB_MAX_CONN`.
   So raising web's business-hours floor from 1 to 2 costs 16 connections — the same as taking
   assess AND remediate from 1 to 5 each. A capacity table that treats "warm replicas" as one
   currency across services will keep producing shapes like §5.3's.
3. **Reduce `acp-app`'s pool** (`ACP_DB_MAX_CONN` on the API tier). `api/store.py` argues against
   this at length: the 16-connection headroom was raised from 8 after a live pool-exhaustion
   incident. Not recommended.

Until one is chosen, `rightsize-production.sh` generates the assess rule and **skips applying it**,
printing why. That is Phase 1 delivered as far as it can honestly go.

> **Confirmed through the shipped code, 2026-09-06.** `GET /control/capacity-schedule` returns
> the §5.3 table with `blocked: true`, `over_connection_budget`, and a headroom of **-17**. The
> validator that Phase 3's write will call already refuses the schedule this PRD proposes, which
> is what the read-only phase was for.

## R4 — The queue scalers counted work no worker could claim (fixed)

§6.2 lists "retry eligibility" as an input to scaling. No scaler in the tree implemented it.

`store.claim_job` claims a row only when `status='queued' AND run_after <= now AND attempts <
max_attempts`. All four deployed scaler queries — two in `rightsize-production.sh`, one in
`deploy.sh`, two triggers in `packaging/chart/acp/templates/autoscaling.yaml` — tested the first
term alone. Both missing terms are populated in normal operation: `run_after` carries retry
backoff up to 600s, and an attempts-exhausted row sits at `status='queued'` until the reaper marks
it dead.

The consequences are asymmetric. On the depth trigger the tier scales up for work no replica may
take, and the extra replicas idle until cooldown. On the Helm chart's **oldest-job-age** trigger
the damage is unbounded: age has no ceiling, so one unclaimable row pins the tier at `maxReplicas`
indefinitely against an empty queue.

**Fixed.** `api/queue_scaler.py` owns the predicate; `scripts/gen_queue_scalers.py --check` holds
all four copies to it; `tests/test_queue_scaler.py` holds the predicate to `claim_job`'s own SQL.
The cast (`run_after::timestamptz`) is required because `jobs.run_after` is a TEXT column of
ISO-8601 strings — `docs/runbooks/verify-capacity-scalers.md` §4 is the check that no row in
production will refuse to cast.

## R5 — Scale-in had no drain guarantee of its own

§6.3 requires excess replicas to drain rather than die. `deploy/public/redeploy.sh` sets the ACA
termination grace (600s) and the application drain (540s) — but only on a **rollout**. Scale-in
has no rollout: the scaler removes a replica, Azure sends `SIGTERM`, and the app gets whatever
grace period it happens to carry. On an app created by `deploy.sh` and never redeployed that is
Azure's 30-second default.

**Fixed.** `rightsize-production.sh` now sets both on the worker apps, from the same environment
variables and defaults `redeploy.sh` uses, so the two scripts cannot disagree about what a drain
is. Confirming it took is §7 of the runbook.

## R6 — The vCPU limit in §7 has no source, and is not invented here

§7 requires validation against the "Azure environment vCPU quota". **No artifact in this
repository records it.** `capacity_budget.evaluate` therefore takes `vcpu_quota` with no default:
passed `None`, it reports the fleet's vCPU demand and states that the check was **not performed**,
rather than passing. Reading it from Azure is a step in the runbook.

## R7 — §6.4 is right, and the mechanism needs naming in Phase 3

"Do not run a script twice a day" is the correct instruction — every `containerapp update` creates
a revision. What §6.4 does not say is what replaces it. The mechanism is a **KEDA `cron` scale
rule alongside the existing `postgresql` one**: two rules on one app, where KEDA takes the maximum
of what they ask for. That gives a time-driven floor and a queue-driven ceiling with no
configuration change at the transition, which is exactly what §6.1 and §6.4 jointly describe.
Phase 3 should say so explicitly, because the obvious implementation — a cron job calling
`az containerapp update` — is the one §6.4 forbids.

## R7 — the mechanism, now that it is built

§6.4 forbids a script that changes the Container App template twice a day and does not say what
replaces it. `api/capacity_policy.py` builds the answer: **two KEDA rules on one app, and KEDA
takes the maximum of what they ask for.**

| | Value | Why |
|---|---|---|
| `minReplicas` | the off-hours floor | overnight capacity never drops below it |
| `maxReplicas` | the service ceiling | the only cap; the cron rule is not one |
| `cron` rule | asks for the business-hours floor, during the window | §6.1's floor, held without a deploy |
| `postgresql` rule | asks for whatever the claimable backlog needs, any hour | AC 8's overnight burst |

Nothing about the app changes at 06:00 — KEDA simply computes a different number — so the
transition creates no revision. Publishing costs one update per app, which is what §6.4 permits.

Two things this turned up that the PRD could not have known:

* **The queue rule's name is not derivable from the service.** Production's remediate rule is
  `remediation-queue`; the service is `remediate`. Generating the name would have added a second
  rule rather than replacing the first — invisible outside the scale block, and surviving every
  later edit.
* **Discovery gets no generated rule at all.** No discovery scale rule exists in this repository,
  and `--scale-rule-name` *replaces* the rules array, so emitting one could silently delete a
  hand-applied rule. §1 of the runbook is the read that settles it; until then, guessing is worse
  than abstaining.

## R9 — Phase 4's tuning cannot start, and saying so is the deliverable

§14 gates Phase 4 on *"at least one week of measurements"*. There are none: nothing has been
applied to Azure (Phase 3b needs a subscription), so no schedule has ever been in force and no
transition has ever happened. Three of Phase 4's four items depend on that data:

| Item | What it needs before it can be decided |
|---|---|
| Tune business-hours floors | Cold-start latency at the window's open, and queue wait at the floor, over a week of real mornings. Nothing has warmed on a schedule yet. |
| Tune queue thresholds and cooldowns | How often the queue asked for replicas that then idled, and how often it asked too late. `targetQueryValue` is 4 for remediate and 8 for assess; both are **stated starting points, not derived figures**. |
| Overnight GPU scale-to-zero | Idle GPU cost per night against first-request cold-start latency. `acp-ollama` is 4 vCPU and already 0–1, so the saving is real but unmeasured. |

Picking numbers now would produce figures indistinguishable, to every later reader, from measured
ones — which is the failure mode this repository has documented three times over. So they stay
open, with the measurement named.

**What was built instead is the apparatus those decisions need.** "Tune queue thresholds" is not a
decision anybody can make from a replica count that does not say what asked for it. AC 14 —
*"Monitor identifies whether scaling was scheduled, queue-driven, manual, or deployment-related"* —
was an outstanding acceptance criterion and is exactly that instrument.
`capacity_schedule.attribute_capacity` derives it from readings that already exist, so it costs no
storage and no background writer. It distinguishes five states, and the fifth is the one a bare
replica count hides:

* `deployment` — a rollout is in progress, so the count says nothing about demand. Outranks
  everything: reading a deploy as a demand spike is the classic misattribution.
* `manual_override` · `queue` · `scheduled` — the three §10 asks for.
* `below_floor` — **fewer** replicas than the floor. Not a scaling decision at all: a restart, a
  failed revision, or capacity Azure has not granted. Identical to `scheduled` in a bare count,
  and only one of them is a problem.

**A durable scale-event history is deliberately NOT built.** It is a table, a writer and a
retention decision, and it should be made against a week of the derived view rather than in
advance of it.

## R10 — holiday exceptions work in ACP and cannot work in Azure

Delivered as a first-class schedule field: `effective_mode`, `next_transition`, validation and the
tab all observe them, and an unparseable date **blocks the save** rather than being dropped (a
holiday ACP cannot read is one it will not observe, and the administrator would see their date
listed and get warm capacity anyway).

**The published Azure policy cannot enforce them, and this is a limit rather than a gap.** A KEDA
`cron` rule is a start expression, an end expression and a timezone. Cron can say *"the 25th of
December"*; it has no way to say *"every weekday except the 25th of December"*. Expressing the
exclusion needs one rule per contiguous run of working days between holidays — unbounded, and
republished as the calendar moves, when every republish is a revision §6.4 exists to avoid.

So on a holiday, **Azure holds the business-hours floor and ACP knows it should not.** That is a
day of wasted spend, not a correctness failure, and it is stated in three places rather than
discovered from a bill: `GET …/policy` returns `holidays.enforced_by_policy: false` with the
reason, the tab says it beside the dates, and the editor says it beside the field. The two ways to
actually close it — republish without the schedule for the day (two revisions), or a temporary
override (no revision, but four hours at a time) — are recorded next to the caveat.

**One bug this turned up.** `next_transition` searched nine local days. A schedule naming a single
weekday, with a holiday on the next occurrence of that weekday, has its next transition fifteen
days out — so the search returned `None`, and the tab renders `None` as *"no scheduled
transition"*. A valid schedule with one holiday would have reported itself as having nothing
scheduled, indefinitely. The horizon is now a year, with an early exit on the first day that
carries one.

## R8 — Smaller notes

- **§5.3's GPU row is not a Postgres client** and does not appear in the connection budget. It
  does appear in the vCPU one: `acp-ollama` is 4 CPU.
- **AC 4 (DST)** is testable without Azure and should be a Phase 2 unit test, not a Phase 3 one:
  the next-transition calculation is pure.
- **AC 10** ("a broken queue scaler appears as degraded, not healthy") should include *pinned*, not
  only *broken*. A rule on a 5–5 tier is neither broken nor healthy — it is inert, and
  `capacity_budget.evaluate` emits `ceiling_equals_floor` for exactly this case.
- **§9's drift detection already has its data source.** `GET /control/workers/capacity` returns
  `scale` per app — min, max, polling interval, cooldown and every rule's metadata — so the
  desired-versus-observed comparison needs no new Azure call.

## Revised phase plan

| Phase | Change from §14 |
|---|---|
| 1 | **Delivered except the Assess ceiling**, which is blocked on the R3 decision. Adds: predicate fix across four scalers, generator + `--check` guard, importable fleet budget, scale-in drain settings, verification runbook. |
| 1b | **New, and now the critical path.** Owner decides R3 — after #1533 the headroom is one connection, so assess cannot gain any ceiling at all. Then: raise the ceiling, apply the rule, run the runbook against staging. |
| 2 | **Delivered.** Read-only Scheduling tab in Settings, `GET /control/capacity-schedule` and the admin-only `POST …/validate`, scaler health (with the `pinned` state AC 10 was missing), the Live Operations capacity-mode strip (R1), and the DST tests moved forward (R8). No infrastructure changes, no persistence, no writes. |
| 3 | **Delivered, except applying to Azure.** `PUT /control/capacity-schedule` (validated, version-checked, audited), audited overrides that expire on read, `GET …/policy` rendering the cron+queue mechanism (R7), and the administrator editor. Persistence and application are separate steps: a saved schedule reports `azure_applied: false` until somebody pushes it. |
| 3b | **New.** Apply a published policy to Azure and verify a real transition creates no revision (AC 5, AC 17). Needs a subscription; `docs/runbooks/verify-capacity-scalers.md` §8 is the procedure. |
| 4 | **Split.** Holiday exceptions and AC 14's scale attribution are delivered — neither needs measurements. The three tuning items are **blocked on data that does not exist**: see below. |
