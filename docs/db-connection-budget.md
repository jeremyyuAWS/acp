# Postgres connection budget — proposal (H-02)

**Status:** Proposal for the platform owner. **Nothing here is applied**, and no Azure setting was
read or changed to produce it. **Created:** 30 August 2026.

The arithmetic below is executable: `tests/test_db_connection_budget.py` derives every pool from
the same `db_max_conn()` the containers use, so a change to the formula moves these numbers
instead of silently invalidating them. A budget nobody can run is a budget nobody checks — which
is how #1045, correct about the incident it targeted, took production's ceiling from 230 to 328
against a 150-connection server without anyone noticing.

## 1. Inputs, and how far each is trusted

**Verified in this repository at `a50d067c`:**

| Fact | Where |
|---|---|
| Pool per process = `max(2, ACP_WORKERS + 16)` | `api/store.py` |
| `ACP_DB_MAX_CONN` is set by **no deploy script** — no override is in force anywhere | `deploy/` |
| **One process per replica** — `uvicorn app:app` carries no `--workers`; the worker tier is one process of N threads | `deploy/public/Dockerfile`, `deploy/public/deploy.sh` |
| deploy.sh's **create-time** limits: API `1–1`, worker `1–3`, `ACP_WORKER_COUNT` default `2` | `deploy/public/deploy.sh` |

**Carried from the 2026-08-30 Azure read, not re-verified here** (this environment has no Azure
access; reading live configuration is a separate authorised step):

| | Production | Staging |
|---|---:|---:|
| API replicas min–max | 1–3 | 1–1 |
| Worker replicas min–max | 3–10 | 1–3 |
| `ACP_WORKERS` (worker tier) | 12 | 2 |
| `max_connections` | 150 (user override) | 50 (system default) |
| Observed 24h peak connections | 74 | 27 |

> **These two sets disagree, and that matters.** `deploy.sh` passes replica flags only on
> `containerapp create`, never on `update`, so live limits persist from whatever was set out of
> band. **The deploy script is not the source of truth for a running deployment.** Re-read the
> live values from Azure before applying anything below.

## 2. Where we are

One process per replica, so the fleet ceiling is `replicas × pool`. "During deploy" adds the
outgoing revision at its **minimum** replicas — a rolling deploy runs both, and it is the incoming
one that scales under load, so min-of-old + max-of-new is the realistic worst case rather than a
doubling of everything.

| | Pool/process | Steady ceiling | During deploy | `max_connections` |
|---|---:|---:|---:|---:|
| Production API (`ACP_WORKERS=0`) | 16 | 48 | | |
| Production worker (`ACP_WORKERS=12`) | 28 | 280 | | |
| **Production total** | | **328** | **428** | **150** |
| Staging API | 16 | 16 | | |
| Staging worker (`ACP_WORKERS=2`) | 18 | 54 | | |
| **Staging total** | | **70** | **104** | **50** |

Both environments' ceilings exceed their servers. These are **potential** ceilings — pools grow on
demand, and the observed peaks were 74 and 27 — so nothing is breached today. What has changed is
that the gap is now wider than when the incident was analysed, and the binding constraint in
production is CPU (98.36% mean over 24h), not connection slots.

**Why the fix is not "shrink the pools".** At 10 worker replicas the worker term dominates: even a
pool of 10 per process — below one connection per thread, so every job thread would contend — still
leaves nothing for the API within 150. There is a test for exactly this
(`test_no_per_process_pool_can_rescue_ten_worker_replicas`). Worker **max-replicas** has to come
down, or the database tier has to go up.

## 3. Proposal

Role-specific and explicit, because one formula for every role is what took the worker tier from
20 to 28 as a side effect of fixing the API. `ACP_DB_MAX_CONN` is the override that breaks the
coupling between a tier's thread count and its connection budget; #1045 deliberately preserved it
for this decision.

### Production — fits 150 with reserve

| Setting | From | To |
|---|---:|---:|
| Worker `--max-replicas` | 10 | **4** |
| `ACP_DB_MAX_CONN` on the API app | unset (→16) | **12** |
| `ACP_DB_MAX_CONN` on the worker app | unset (→28) | **12** |

```
API     (3 max + 1 outgoing min) × 12 =  48
worker  (4 max + 3 outgoing min) × 12 =  84
                            during deploy 132  + 15 reserve = 147  ≤ 150
                                   steady  84                      (observed peak 74)
```

Reserve 15 covers schema migrations, `scripts/monitor.py`, an admin `psql`, and Azure
diagnostics. It is a **stated allowance, not a measurement** — revise it once the real count of
non-application clients is known.

Worker threads stay at 12 against a pool of 12: one connection per thread, no in-process
contention. Capacity is reduced by cutting replicas, not by starving each one.

### Staging — fits 50 exactly, and that is the finding

| Setting | From | To |
|---|---:|---:|
| `ACP_DB_MAX_CONN` on the API app | unset (→16) | **9** |
| `ACP_DB_MAX_CONN` on the worker app | unset (→18) | **6** |

```
API     (1 max + 1 outgoing min) × 9  = 18
worker  (3 max + 1 outgoing min) × 6  = 24
                           during deploy 42  + 8 reserve = 50  ≤ 50
                                  steady 27                    (observed peak 27)
```

The steady ceiling lands **exactly on staging's own observed peak**. That is not a comfortable
budget, and the cause is that staging's `max_connections` is **50, the Postgres system default** —
never raised the way production's was raised to 150.

**Recommendation: raise staging's `max_connections` before using it to validate anything.** As it
stands, staging cannot rehearse production's connection budget; it would be the first thing to run
out, and a load test there would prove nothing about production. That is a server-parameter change
and therefore the owner's, not this document's.

## 4. What must happen before any of this is applied

1. **Re-read live configuration from Azure** — replica minima/maxima, `ACP_WORKERS`, and
   `max_connections` for both environments. §1 says which numbers are carried rather than
   verified; do not apply a budget on top of stale inputs.
2. **Confirm the reserve** by counting real non-application clients rather than accepting 15/8.
3. **Validate in staging first**, after its `max_connections` is raised — otherwise the validation
   environment is the constraint.
4. **Watch CPU, not only connections.** Production sat at 98.36% mean CPU for 24h. Fewer, better
   queries move that; more connections do not. The inventory fix (#1051, 8.0× → 1.0× read
   amplification) and shared `/jobs` polling (#1054, five pollers → one) both reduce the load this
   budget has to accommodate, and are worth measuring before re-tuning anything.

Do not raise pools or replicas for a demo. The observed peaks (74, 27) sit comfortably inside
today's actual usage; the risk being managed here is the **ceiling**, which only bites when
scaling does.
