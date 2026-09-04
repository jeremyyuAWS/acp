# Runbook — re-read the connection-budget inputs from Azure

**Read-only.** Nothing here changes a setting. It produces the six numbers per environment that
`tests/test_db_connection_budget.py` needs, so a capacity decision is made against live values
rather than carried ones.

**These commands were NOT executed when this runbook was written.** The environment that produced
it has no Azure CLI and no credentials; reading live configuration is a separate authorised step.
Treat the syntax as a starting point and check each command's output before recording it.

## Why this exists

`docs/db-connection-budget.md` states plainly that its Azure figures are *"carried from the
2026-08-30 Azure read, not re-verified"*, and its step 1 is to re-read them. Two things have since
gone stale in a way that is invisible from the numbers alone:

1. **The topology changed underneath the model.** That document computes one worker tier at 3–10
   replicas. Production runs `acp-app` plus three role-restricted worker apps. The split
   multiplied the term that already dominated: 328 → **384** on the same inputs.
2. **`deploy.sh` passes replica flags only on `containerapp create`, never on `update`.** Live
   limits persist from whatever was set out of band, so no script in this repo is the source of
   truth for a running deployment.

`ACP_WORKERS` is the sharpest unknown. `deploy/public/redeploy.sh` sets it on **none** of the
three worker apps, and `api/worker_main.py` forces `12` when it is unset — so the value in force
is not knowable from this repository at all.

## What to read

Per environment, for each of `acp-app`, `acp-discovery`, `acp-assess`, `acp-remediate`:

| Input | Why it matters |
|---|---|
| `minReplicas` / `maxReplicas` | the fleet ceiling is `replicas × pool`, and max is what sets it |
| `ACP_WORKERS` | pool is `ACP_WORKERS + 16`; unset means 12, not 0 |
| `ACP_DB_MAX_CONN` | the override that breaks pool from thread count; set by no deploy script |

And for the Postgres server: `max_connections`, the tier/SKU, and the observed peak connections
and CPU over a representative window.

## Commands

```bash
RG="${ACP_RG:-mdk-accessibility}"

# Replica ranges, per app.
for APP in acp-app acp-discovery acp-assess acp-remediate; do
  az containerapp show -g "$RG" -n "$APP" \
    --query "{app:name, min:properties.template.scale.minReplicas, max:properties.template.scale.maxReplicas}" -o tsv
done

# The two env vars that set the pool. Absent output means UNSET — which is 12, not 0.
for APP in acp-app acp-discovery acp-assess acp-remediate; do
  echo "== $APP"
  az containerapp show -g "$RG" -n "$APP" \
    --query "properties.template.containers[].env[?name=='ACP_WORKERS' || name=='ACP_DB_MAX_CONN'].{n:name,v:value}" -o tsv
done

# Server parameter and tier. Substitute the real server name.
az postgres flexible-server parameter show -g "$RG" -s <server> -n max_connections --query "value" -o tsv
az postgres flexible-server show -g "$RG" -n <server> --query "{tier:sku.tier, sku:sku.name, vcores:sku.name}" -o tsv
```

Observed peak connections and CPU come from Azure Monitor over a representative window — a single
instantaneous reading is not a peak, and the whole point of the exercise is the peak.

## Recording the result

Update these together, in one change, so they cannot disagree:

- `tests/test_db_connection_budget.py` — `RIGHTSIZE_REPLICAS`, `PLAUSIBLE_WORKER_THREADS`,
  `PROD_LIMIT`, `RESERVE_PROD`. The arithmetic is executable; changing an input moves every
  derived number rather than silently invalidating it.
- `docs/db-connection-budget.md` — its §1 table, and the carried/verified split above it.

If the fleet turns out to fit its server, several tests in that module fail **by design** — they
pin a finding, and a finding that has been fixed should stop being asserted. That failure is the
prompt to update the document, not a regression.

## Before changing anything

The four preconditions in `docs/db-connection-budget.md` §4 still apply, and the fourth is the one
most likely to be skipped: **watch CPU, not only connections.** Production was reported at 98.36%
mean CPU over 24h against an observed connection peak of 74 of 150. `api/store.py` records why
that ordering matters — connection-slot headroom and CPU headroom are orthogonal, and more
concurrent connections against an already CPU-saturated server can worsen contention rather than
relieve it.
