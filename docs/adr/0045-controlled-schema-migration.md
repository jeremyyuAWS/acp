# ADR 0045 — Controlled schema migration: what makes a deploy safe, and what does not

Status: **Proposed** — nothing here is implemented. This is the design half of the boot-lock
work; the code half (replicas verify instead of replay) is a separate PR. No deployment-policy
change, pipeline change, or production migration is being asked for by this ADR alone · Date:
2026-08-31 · Related: [ADR 0029](0029-vendored-pdf-engine.md), `docs/db-connection-budget.md`

## Context

On 2026-08-30 production recorded startup failures inside `Store → init_schema → cur.execute`,
`/jobs` 503, and two queue-read 500s with database deadlocks, within fourteen seconds.

Reproduced on PostgreSQL 16 on 2026-08-31: six replicas booting against live reads, **five of
six failed with `DeadlockDetected` inside `init_schema`**. The cause was that `Store.__init__`
called `init_schema()` unconditionally, so every API and worker replica replayed all 139
statements of `_SCHEMA` + `_PG_VIEWS` on every boot, in one transaction, with no `lock_timeout`.
The statements are no-ops on an already-migrated database and that does not help:

```
NOTICE:  column "phase" of relation "jobs" already exists, skipping
AccessExclusiveLock|jobs|t
```

`ADD COLUMN IF NOT EXISTS` takes the exclusive lock *before* discovering it has nothing to do.

The accompanying code change stops the replay. This ADR is about what happens when the schema
genuinely does change, because that is not fixed and the obvious fix does not work.

## Moving DDL to a separate deployment step is NOT sufficient

This is the central claim of this ADR, and it is stated first because it is the conclusion most
likely to be assumed away.

A "run migrations once, before the rollout" step changes **who** runs the DDL and **when**. It
does not change **what locks the DDL takes**, and it does not change **who is reading at the
time**. Measured on the same reproduction, with replay eliminated and exactly one process
migrating: **three `queue_estimate` deadlocks still occurred** against that single migrating
process. One migrator is not a safe migrator.

Worse, a separate step introduces a failure mode the replay never had. The migration necessarily
runs **before** the new code is serving. So the first thing that meets the new schema is the
**old** code, on every replica still serving traffic. If a migration is not backward compatible,
the outage moves from "replicas deadlock at boot" — loud, self-limiting, visible in the deploy —
to "every serving replica errors against a schema it does not understand" — silent, estate-wide,
and not obviously connected to the deploy that caused it.

So the separate step is a **precondition** for the real mechanism, not the mechanism.

## What actually makes it safe

### 1. Every migration is additive (expand / contract)

The property that has to hold is not "the migration is fast". It is:

> Both the version that is running and the version being deployed must work correctly against
> both the schema before the migration and the schema after it.

That is the only thing that makes a rolling deploy safe, and it is also the only thing that makes
a **rollback** safe (see §4). It is achieved by never doing a destructive change in the same
deploy as the code that stops needing the thing being destroyed:

| Phase | Deploy N | Deploy N+1 (or later) |
|---|---|---|
| **Expand** | add the new column/table/index, nullable and unused | — |
| **Migrate** | new code writes both old and new; backfill runs as data work, not DDL | — |
| **Contract** | — | drop the old column/index, once no replica running the old code remains |

**Rule: no single deploy may both expand and contract the same object.** A contract is only
permitted once the code that depended on the expanded form is gone from every replica — which is
a *later* deploy, never the same one.

This constraint is what licenses the code change's behaviour of letting an older replica run
against a newer schema without migrating. That is safe **only** because the newer schema is
additive with respect to the older code. If a migration ever drops or retypes something an older
replica reads, that replica breaks — and no boot-time check can save it, because the damage is
to the running process, not the boot.

### 2. Lock classification, and a budget per class

Not all DDL is equal, and today's `_SCHEMA` mixes classes freely.

| Class | Statements | Lock | Held for |
|---|---|---|---|
| **A — safe** | `CREATE TABLE`, `ADD COLUMN` nullable (PG11+ with a non-volatile default too), `ADD CONSTRAINT … NOT VALID`, `CREATE INDEX CONCURRENTLY` | brief `ACCESS EXCLUSIVE`, or none | milliseconds |
| **B — blocking** | `CREATE INDEX` (non-concurrent), `DROP INDEX`, `VALIDATE CONSTRAINT` | `SHARE` / `ACCESS EXCLUSIVE` | duration of the build |
| **C — rewriting** | type changes, `SET NOT NULL` on a populated column, most `DROP COLUMN` follow-ups | `ACCESS EXCLUSIVE` | full table rewrite |

**Proposal: only Class A may run in an automatic deploy.** Class B and C require an explicit,
named decision with a window, and never run unattended.

Two concrete findings about the current schema, from reading it rather than assuming:

- **16 index statements, none of them `CONCURRENTLY`.** Every one is Class B today.
- **They cannot be made `CONCURRENTLY` where they are.** `CREATE INDEX CONCURRENTLY` may not run
  inside a transaction block, and `_apply_schema` wraps all 139 statements in one transaction.
  So index creation has to move **out** of the single-transaction migration into its own
  autocommit phase before this classification can be honoured at all.
- **`DROP INDEX IF EXISTS idx_jobs_claim` is already non-additive**, sitting in the same list as
  everything else. It is harmless in practice — dropping an index costs performance, not
  correctness — but it is exactly the shape of statement the additive rule exists to keep out,
  and it is there today with nothing preventing the next one from being a `DROP COLUMN`.

### 3. Bounded lock acquisition

Unbounded waiting is what turns one slow statement into an estate-wide outage: a DDL statement
waiting for a lock **queues every subsequent reader behind itself**, because a pending
`ACCESS EXCLUSIVE` blocks new `ACCESS SHARE` requests even while it is still waiting.

- `lock_timeout` on every migration connection (the code change sets 5s). A migration that cannot
  acquire its lock **fails**, leaving the previous schema untouched and the deploy visibly red.
- `statement_timeout` as a second bound, for a statement that acquires its lock and then runs
  long — a Class B index build on a large table.
- **Retry is bounded and belongs to the migration, not the request.** A timed-out migration may
  retry a small number of times with backoff, on the theory that the blocking reader has since
  finished. It must not retry indefinitely, and application requests must never retry a
  migration.
- Never `NOWAIT` — that fails on the first contended moment, which is most of them.

### 4. Rollback

The important property is that **the schema is not rolled back, and does not need to be.**

Under the additive rule, deploy N+1's schema is compatible with deploy N's code. So rolling the
*code* back to N is safe with the expanded schema still in place. This is the payoff for the
constraint in §1, and it is why "write a down-migration" is the wrong instinct here: a down
migration is itself a destructive DDL statement, run under incident pressure, against a schema
whose exact state nobody is certain of.

What must be handled explicitly:

- **A failed migration inside the transaction** rolls back completely — PostgreSQL DDL is
  transactional. The code change relies on this and re-raises after `rollback()`.
- **A failed `CREATE INDEX CONCURRENTLY` does not**, because it cannot be in a transaction. It
  leaves an `INVALID` index behind, which must be dropped before retrying. Any move of index
  creation out of the transaction (§2) has to carry that cleanup with it.
- **A partially-applied multi-phase migration** (expand succeeded, backfill failed) leaves an
  additive schema and no data dependency, so it is recoverable by re-running rather than
  reversing.
- **The deploy rolls back; the marker does not.** The schema-version marker records the highest
  version applied. Rolling code back to N leaves the marker at N+1, and the older replica
  correctly does nothing about it.

### 5. Compatibility, which is not the same as identity

The code change answers *"is the database at or ahead of the version this build needs?"* — an
integer comparison. That is deliberately **not** the same question as *"can this build run
against this database?"*, and the difference matters during a deploy.

The first attempt used a content **checksum** and got this wrong, in a way worth recording because
it looked obviously correct. A checksum answers "identical or not", which has no ordering, so an
old replica booting after a new one had migrated saw "different" and migrated *backwards*.
Measured, alternating versions across five boots: five migrations, the marker flapping between
two checksums — the exact lock storm the change exists to prevent, occurring precisely during a
rolling deploy. An integer with `>=` produces two migrations for two real transitions.

The integer is still only a proxy. A stronger form, not proposed for now because the additive
rule makes it unnecessary, is for a replica to verify the **objects it actually needs** are
present — a required-objects check against `information_schema` — which would let a replica
refuse to serve against a schema genuinely missing something, rather than inferring it from a
version number somebody has to remember to bump. The version number is guarded by a checksum
test for exactly that reason.

### 6. The app and the worker are deployed on different images, and that window is not protected

Everything above is about mixed **schema** versions. This deployment has a second mixed-version
window that has nothing to do with the schema, and `deploy/public/redeploy.sh:269-282` already
documents it as a deliberate, unprotected property rather than an oversight:

> `acp-worker` has NO INGRESS … It takes work by pulling from a shared job queue, so a second
> worker on a different image would pull from that SAME queue — blue and green racing over live
> production jobs, picked at random. There is no weight to set and nothing to split. The worker
> therefore CUTS OVER at promotion, and that step is not protected. … Consequence while green
> sits at 0%: the system is MIXED — green app on the new image, worker still on the old one.
> Anything that enqueues a job whose contract changed is NOT [safe]: green would enqueue work
> the old worker cannot correctly process.

So `acp-app` gets real blue-green — green provisions at 0%, is smoke-tested on its own FQDN, then
takes traffic in one reversible weight change — and `acp-worker` gets none, because ingress weight
is the only splitting mechanism ACA offers and a worker has no ingress.

**This is a different failure from anything in §1-§5, and the additive rule does not cover it.**
The additive rule protects the *schema* contract between old code and new. It says nothing about
the **job payload contract** between a new app that enqueues and an old worker that dequeues. A
payload field the new app adds and the new worker requires is perfectly additive at the database
level and still breaks: the old worker reads a job it does not understand, and the failure is a
dead-lettered scan rather than a SQL error.

The constraint that actually holds here is the mirror of the additive rule, one layer up:

> A deploy may not change what a job payload MEANS in the same release that starts producing it.
> Producing a new field is safe; requiring it is a later deploy, once no old worker remains.

Which is the same expand/contract discipline applied to the queue instead of the schema, and it
is currently enforced by nothing — not a test, not a check, not a review gate. The schema half
now has `_SCHEMA_VERSION` and a checksum guard; the payload half has neither.

Two things follow for this proposal:

- **The migration step's ordering guarantee is weaker than §1 implies.** "Runs before the new
  revision receives traffic" is true of `acp-app`, and the worker's cutover is a separate,
  unprotected moment that the migration step does not coordinate with at all. A deploy that
  migrates the schema, promotes the app, and cuts the worker over has three transitions, not one,
  and only the first two are sequenced.
- **`redeploy.sh` already names the fix and scopes it out**: queue partitioning, where green
  consumes its own queue and promotion swaps which queue the app enqueues to. It is correctly
  identified there as an application change (`worker_main.py` plus the job table), not a deploy
  script change. This ADR does not propose it either — it is a larger piece of work than the
  schema question, and naming it as the known answer is more useful than sketching a worse one.

What this ADR does add is that the two windows must not be reasoned about separately. A migration
that is additive at the schema level can still land in the middle of a worker cutover, and the
deploy sequence in the next section only orders the schema half.

## Proposed sequence for a deploy that changes the schema

1. **Pre-flight, read-only.** Assert the migration is Class A and additive. This is the gate; it
   is a review question today and should become a mechanical check.
2. **Migration step**, single process, `lock_timeout` set, bounded retries. Runs *before* the new
   revision receives traffic and *after* the old revision has been confirmed compatible with the
   new schema — which the additive rule guarantees, and which nothing else does.
3. **Index phase**, separate, autocommit, `CONCURRENTLY`, with `INVALID`-index cleanup on retry.
4. **Rollout.** Replicas verify and find the database already ahead; no DDL, no locks.
5. **Contract**, in a later deploy, once no old-code replica remains.

Note what this sequence does NOT order: the `acp-worker` cutover (§6). Steps 2 and 4 sequence the
schema against the app's revisions; the worker changes image at promotion, outside this sequence,
and the window between the app going green and the worker cutting over is one in which a new app
is enqueueing to an old worker. Reading this list as covering the whole deploy is the mistake §6
exists to prevent.

## Consequences

- Migration authorship gets a rule it did not have: additive only, contract later. That is a
  real constraint on contributors and the main cost of this proposal.
- `_SCHEMA` as a flat replayed list is not a migration system, and this ADR does not turn it into
  one. It proposes the constraints a migration must satisfy; the ordered-migration mechanism
  (numbered files, applied-set tracking) is a larger change and is not proposed here.
- Class B/C changes become explicitly manual. That is intended: they were always unsafe
  unattended, and were merely invisible.
- **None of this is implemented.** The deployment-pipeline change is held for review.

## What this ADR does not claim

- It does not claim moving DDL to a separate step makes deploys safe. Measured: three reader
  deadlocks against a single migrating process, with replay already eliminated.
- It does not claim the current `_SCHEMA` satisfies the additive rule. It contains a `DROP INDEX`
  today, and 16 non-concurrent index statements.
- It does not claim the boot-time version check protects a running replica. It protects boot. A
  replica already serving when a destructive migration lands is not protected by anything here
  except the additive rule itself.
- It does not claim to make the app/worker cutover safe (§6). That window is documented in
  `redeploy.sh`, unprotected today, and closed only by queue partitioning, which is not proposed
  here. The schema discipline in §1-§5 does not extend to the job payload contract, and treating
  it as though it does is the specific error §6 records.
