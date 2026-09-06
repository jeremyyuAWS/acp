# PRD — Settings → Scheduling

**Status:** Accepted · **Product:** ACP · **Scope:** scheduled platform capacity

## Outcome

ACP is warm when people normally use it, economical when they do not, and still processes
unexpected overnight work. Scheduling controls capacity, not scan execution: scheduled re-scans
remain in Monitor.

## Experience

Settings adds **Scheduling** beside **Worker Configuration**. It shows whether the desired policy is
enabled, its timezone and weekdays, business/off-hours windows, per-service warm floors and maximums,
validation results, and whether Azure has actually applied it. Administrators may edit; view-only
Settings users may inspect. A save that only persists intent must say so plainly.

Initial proposal:

| Service | Work hours | Off hours | Maximum |
|---|---:|---:|---:|
| Web | 2 | 1 | 3 |
| Discovery | 2 | 1 | 4 |
| Assess | 5 | 1 | 10 |
| Remediate | 5 | 1 | 10 |
| GPU vision | 1 | 0 | 1 |

The schedule is a floor, not a cap. Role-specific queue scaling may raise capacity at any hour.
Scale-down drains claimed work. Ordinary time transitions must not create Container App revisions.

## Safety contract

Before save, validate every floor against its maximum, keep one off-hours replica for every required
non-GPU role, validate the IANA timezone and time window, and price maximum vCPU plus database
connections including old/new revision overlap and operational reserve. Unsafe schedules are rejected.
Configuration changes are admin-only, optimistic-concurrent, and audited. Desired and observed Azure
state are distinct; drift or missing telemetry is never presented as success.

## API

- `GET /control/capacity-schedule` — desired policy, application state, and validation.
- `POST /control/capacity-schedule/validate` — admin-only dry-run.
- `PUT /control/capacity-schedule` — admin-only, versioned, atomic desired-policy save.
- A later reconciler applies combined cron and queue rules after scaler and fleet-budget validation.

## Rollout

1. Persist, render, validate, authorize, version and audit the desired policy without mutating Azure.
2. Repair and verify Assess/Remediate queue scalers and graceful drain.
3. Reconcile the desired policy to combined cron plus queue rules; prove normal transitions create no
   revision and no job loss in staging.
4. Add expiring, reason-required overrides and tune floors from a week of measurements.

## Acceptance

The tab is keyboard accessible; read/write permissions are enforced by the API; DST, invalid windows,
unsafe fleet budgets, version conflicts, and overnight minimums are tested; saved-but-unapplied state is
explicit; existing scheduled re-scans are unchanged; and staging demonstrates a day/off-hours transition
without lost or duplicate jobs.
