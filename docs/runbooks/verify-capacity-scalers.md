# Runbook — verify the queue scalers against a live deployment

**Read-only up to §5.** §1–§4 change nothing; §5 is the one step that applies configuration, and
it is called out as such. This is Phase 1 of `docs/prd-capacity-scheduling.md`: the half of
"repair and verify the queue scalers" that cannot be done from a repository.

**These commands were NOT executed when this runbook was written.** The environment that produced
it has no Azure CLI, no Azure credentials, and no database. Check each command's output before
recording it, and read §4's caveat about the SQL cast before applying anything.

## Why this exists

Four KEDA `postgresql` scaler queries live in this tree, and until 2026-09-06 every one of them
counted a population no worker could claim. `api/store.py`'s `claim_job` claims a row only when

    status='queued'  AND  run_after <= now  AND  attempts < max_attempts

and the scalers tested the first term alone. Both missing terms are populated in normal operation:

* `run_after` is how retry backoff is expressed — `store.fail_job` writes `now + backoff_seconds`
  and the backoff runs up to 600s. A job waiting out its backoff was counted as queue depth, so
  the tier scaled up for work no replica was permitted to take, and the new replicas idled until
  the cooldown removed them again.
* An `attempts >= max_attempts` row stays at `status='queued'` until `reap_exhausted_jobs` marks
  it dead. It is permanently unclaimable — a floor the reported depth could never fall below.
* The Helm chart's **oldest-job-age** trigger is the worse of the two, because age has no ceiling.
  One unclaimable row makes it report a number that only grows, pinning the tier at `maxReplicas`
  indefinitely while the claimable queue is empty.

`api/queue_scaler.py` now owns the predicate and `python scripts/gen_queue_scalers.py --check`
holds the four copies to it. That guard is static; this runbook is how the fix is confirmed
against the deployment it was written for.

## 1. Confirm what is attached today

```
az containerapp show -g mdk-accessibility -n acp-remediate \
  --subscription "$AZURE_SUBSCRIPTION_ID" \
  --query "properties.template.scale" -o json
```

Repeat for `acp-assess`, `acp-discovery`, `acp-app`.

Record, per app: `minReplicas`, `maxReplicas`, and for each rule its `name`, `custom.type` and
`custom.metadata.query`. Two answers matter more than the rest:

* **`acp-assess` is expected to have NO rule and `minReplicas == maxReplicas`.** That is not an
  oversight — see §6.
* **`acp-discovery`.** `rightsize-production.sh` carries a comment saying discovery "can use its
  existing CPU scale rule". No such rule is created by any script in this repository, so either it
  was applied out of band or it does not exist. This query is the only way to tell, and the
  difference decides whether discovery autoscales at all.

## 2. Confirm the scaler's credential resolves

```
az containerapp show -g mdk-accessibility -n acp-remediate \
  --subscription "$AZURE_SUBSCRIPTION_ID" \
  --query "properties.configuration.secrets[].name" -o tsv
```

`database-url` must be listed. The rule's `--scale-rule-auth "connection=database-url"` resolves
against that secret; without it KEDA logs an authentication error and scales nothing, and the only
symptom is a tier that stays at its floor.

## 3. Run the query yourself, against the real database

Get the generated SQL:

```
python scripts/gen_queue_scalers.py
```

Run the `rightsize:remediation-queue` query against production **read-only** (a `psql` session on
the operational reserve — the budget in `tests/test_capacity_budget.py` allows for it). Then run
the old form beside it:

```sql
-- what the scaler counts now
SELECT count(*) FROM jobs WHERE status='queued' AND type IN (...)
  AND run_after::timestamptz <= now() AND attempts < max_attempts;

-- what it counted before
SELECT count(*) FROM jobs WHERE status='queued' AND type IN (...);
```

**A difference between the two is the defect, measured.** Record both numbers and the date. If
they are equal at the moment you look, that means only that nothing is in backoff right now —
re-run during or shortly after a failing run, when the difference is real.

## 4. Check the cast before you trust it

The predicate casts the column: `run_after::timestamptz <= now()`. `jobs.run_after` is a **TEXT**
column holding a UTC ISO-8601 string, because the application compares it lexicographically
against another string of that shape.

The cast is exact for every value this codebase writes (`store.enqueue_job` and `store.fail_job`
both write `datetime.isoformat()`), and `tests/test_queue_scaler.py` fails if either stops doing
so. What it cannot rule out is a row written by something else — an old migration, a manual
`INSERT`, a restored backup:

```sql
SELECT id, type, run_after FROM jobs
 WHERE status='queued' AND run_after !~ '^\d{4}-\d{2}-\d{2}T';
```

**This must return zero rows.** A value that will not cast makes the whole query error, KEDA logs
it, and the tier stops autoscaling entirely — a worse failure than the one being fixed. Fix or
delete such rows before §5.

## 5. Apply, and watch one transition

This step changes configuration. It creates a revision on `acp-remediate`, so run it when a worker
restart is acceptable — the app carries a 600s termination grace and a 540s application drain, so
in-flight jobs drain rather than dying, but they do stop being picked up.

```
bash deploy/public/rightsize-production.sh --dry-run     # read the az commands first
bash deploy/public/rightsize-production.sh
```

Then observe one scale-up and one scale-down:

```
az containerapp revision list -g mdk-accessibility -n acp-remediate \
  --subscription "$AZURE_SUBSCRIPTION_ID" \
  --query "[].{name:name,active:properties.active,replicas:properties.replicas}" -o table
```

What to record, because it is what Phase 2 will display and Phase 3 will rely on:

| Observation | Why it matters |
|---|---|
| replicas rise within ~1 polling interval of a backlog appearing | the rule fires at all |
| replicas do **not** rise while jobs sit in retry backoff | the fix works |
| replicas fall only after the cooldown, not at the first dip | scale-in is not thrashing |
| a job running on a removed replica completes or checkpoints | the drain in §7 holds |

## 6. Assess is pinned, and that is a budget decision, not a bug

`rightsize-production.sh` generates an `assess-queue` rule and then **skips applying it** while
`acp-assess` is at `5-5`. A scale rule on a tier whose floor equals its ceiling cannot add a
replica; applying it would cost a revision — a worker restart — for a rule that provably cannot
fire.

Raising the ceiling is not free. `tests/test_capacity_budget.py` derives what the connection
budget affords from the reviewed baseline, and the competing claim on the same connections is
`acp-discovery`'s replica range, which was under review when this was written. Read the current
answer rather than assuming:

```
python -m pytest tests/test_capacity_budget.py -q
```

To change the ceiling: edit the `update_app acp-assess` line **and** the
`apply_assess_autoscale` call together — a test asserts the two carry the same range, so the
guard cannot end up answering for a tier it is not describing.

## 7. Confirm the drain that scale-in depends on

`deploy/public/redeploy.sh` sets the termination grace and the application drain on a **rollout**.
Scale-in has no rollout: the scaler removes a replica, Azure sends `SIGTERM`, and whatever grace
period the app happens to carry is what the in-flight job gets. On an app created by `deploy.sh`
and never redeployed, that is Azure's 30-second default — not enough for a document-sized job.

`rightsize-production.sh` now sets both on the worker apps, from the same environment variables
and defaults `redeploy.sh` uses. Confirm they took:

```
az containerapp show -g mdk-accessibility -n acp-remediate \
  --subscription "$AZURE_SUBSCRIPTION_ID" \
  --query "{grace:properties.template.terminationGracePeriodSeconds, \
            drain:properties.template.containers[0].env[?name=='ACP_SHUTDOWN_DRAIN_SECONDS'].value}" \
  -o json
```

Expected: `grace: 600`, `drain: ["540"]`. The application drain must stay comfortably below the
platform grace — `tests/test_worker_deploy_drain.py` is the static half of that guarantee.

## 8. Apply a published schedule, and prove a transition costs no revision

This is Phase 3b, and it is the one claim in this feature that cannot be established from a
repository: that a scheduled transition creates no new revision (AC 5, and the staging exercise
AC 17 asks for).

Read what would be applied first — it is rendered, not run:

```
curl -fsS "https://$FQDN/control/capacity-schedule/policy" -H "$AUTH" | python3 -m json.tool
```

Each app should show its off-hours floor as `min_replicas`, its ceiling as `max_replicas`, a
`cron` rule carrying an IANA `timezone` and the business-hours window, and its existing queue
rule under the name it already has in Azure. **A queue rule under a name Azure does not already
carry means a second rule would be created rather than the first replaced** — stop and reconcile
the names before applying.

Apply the `az_commands` the same response renders, then record the revision count:

```
az containerapp revision list -g mdk-accessibility -n acp-assess \
  --subscription "$AZURE_SUBSCRIPTION_ID" --query "length(@)" -o tsv
```

**Then wait through one transition and read it again.** The count must be unchanged. That is the
whole of §6.4: publishing may cost one revision per app, and 06:00 must cost none. If the count
moved, something is still editing the template on a timer and the cron rule is not doing the work.

While waiting, confirm the composition behaves as designed:

| Time | Expected | What it proves |
|---|---|---|
| just before the window opens | replicas at the off-hours floor | `minReplicas` is the overnight floor |
| just after it opens | replicas at the business-hours floor, no new revision | the cron rule holds the floor without a deploy |
| a queue burst inside the window | replicas above the business-hours floor | the cron rule is a floor, not a cap |
| a queue burst **overnight** | replicas above the off-hours floor | AC 8, and the reason `maxReplicas` is the only ceiling |

The overnight burst is the row worth being careful about: if it does not rise, the cron rule is
being read as a ceiling somewhere and AC 8 has regressed silently.

### Staging gate before enabling the capacity gateway

Run `.github/workflows/validate-staging-scale-test.yml` manually with
`confirm_scale_test=true`. It targets `acp-discovery-staging`, `acp-assess-staging`, and
`acp-remediate-staging`; a resolved app or resource group that is not unmistakably staging is
rejected before Azure login. The workflow snapshots each app's complete `template.scale`, raises
only its floor, proves the rule array is unchanged, and restores the complete original block on
the failure path as well as the success path. Review all three seven-day artifacts before enabling
an application gateway. Do not substitute the retired `acp-worker-staging` app.

Configure these staging repository variables first:

* `STAGING_ACA_VCPU_QUOTA` — the measured quota of the staging Container Apps environment;
* `STAGING_PG_MAX_CONNECTIONS` — the separate staging database's actual server ceiling;
* `STAGING_PG_RESERVED_CONNECTIONS` — the connections reserved from that ceiling;
* the existing role-specific app variables when the default `*-staging` names are not used.

The running **staging API's managed identity**, not merely GitHub's deployment identity, must have
`Microsoft.App/containerApps/read` and `Microsoft.App/containerApps/write` on each of the three
staging worker apps. Contributor or Container Apps Contributor at that narrow scope satisfies the
check. Do not grant production scope and do not add a client secret: the API uses
`DefaultAzureCredential`. Confirm `database-url` exists on Assess and Remediate before publishing
their PostgreSQL rules.

After the adapter is enabled in staging only, record the three full scale blocks and revision
counts, apply the reviewed schedule through `POST /control/capacity-schedule/apply`, and reread all
three blocks. Each must contain the business-hours cron rule and every pre-existing queue/CPU rule
under its original name, with no duplicates and unchanged auth references. Cross both ends of a
short test window: replicas should move between floors, while revision counts remain unchanged.

For the soft scale-down proof, first confirm each worker reports
`terminationGracePeriodSeconds: 600` and `ACP_SHUTDOWN_DRAIN_SECONDS=540`. Start a traceable job,
cross the cron end, and retain evidence that the selected replica stops claiming new jobs, reports
itself draining, completes the claimed job exactly once, and only then disappears. Repeat with a
queue burst outside work hours to prove the queue rule can still rise above the off-hours floor.
A job that can exceed 540 seconds is still a blocker: the bounded SIGTERM drain is not protected
capacity, and such a job may be killed and lease-reclaimed. Do not describe scale-to-zero as fully
soft until an active-job capacity signal or equivalent controller protects that case.

## What this runbook does not establish

* **The environment's vCPU quota.** No artifact in this repository records it, so
  `capacity_budget.evaluate` reports the fleet's vCPU demand and states that the quota was not
  checked, rather than passing. Read it from Azure (`az containerapp env show`, and the
  subscription's quota for the region) and record it in `docs/db-connection-budget.md`.
* **Whether `acp-discovery` has a CPU scale rule.** §1 answers it; this repository cannot.
* **That the fleet fits at business-hours floors.** It does not, at the capacity table
  `docs/prd-capacity-scheduling.md` §5.3 proposes — see that document's review section. The
  `PUT` endpoint refuses that shape, so this is enforced rather than only documented.
* **That a transition creates no revision.** §8 above is the procedure; nothing in this
  repository can observe it.
