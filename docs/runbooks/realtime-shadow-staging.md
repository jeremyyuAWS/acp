# Realtime shadow — staging enablement and acceptance gate

This phase is diagnostics-only. Existing polling and per-scan SSE remain authoritative; the
shadow panel writes no application state. Production is ineligible in code even if an opt-in flag
is set accidentally.

## Live preflight

Do not enable until all of these are true:

1. `acp-app-staging` and `acp-worker-staging` report the same commit containing PRs #1584 and
   #1587, and both have `ACP_DEPLOY_ENV=staging`. On 2026-09-06 the app had the changes, but the
   worker was still on an older image and reported `production`; activation at that point would
   produce an empty feed.
2. Both services reference staging's `redis-url-isolated` secret. Never copy or print its value.
3. The durable queue has no active jobs before the configuration revision turns over.
4. Production has none of the realtime flags below.

After preflight, configure only staging:

- API: `ACP_REALTIME_V1_ENABLED=true` and
  `ACP_REALTIME_V1_REDIS_URL=secretref:redis-url-isolated`.
- Worker: `ACP_REALTIME_SHADOW_ENABLED=true` and
  `ACP_REALTIME_SHADOW_REDIS_URL=secretref:redis-url-isolated`.

Use the same staging Redis service but the isolated `acp:realtime:v1:owner:*:events` namespace.
Do not enable the standalone HMAC gateway; the browser uses ACP's same-origin authenticated bridge.

The operator commands are intentionally separate and explicit (review the app names before use):

```bash
az containerapp update -g mdk-accessibility -n acp-app-staging --set-env-vars \
  ACP_DEPLOY_ENV=staging ACP_REALTIME_V1_ENABLED=true \
  ACP_REALTIME_V1_REDIS_URL=secretref:redis-url-isolated
az containerapp update -g mdk-accessibility -n acp-worker-staging --set-env-vars \
  ACP_DEPLOY_ENV=staging ACP_REALTIME_SHADOW_ENABLED=true \
  ACP_REALTIME_SHADOW_REDIS_URL=secretref:redis-url-isolated
```

Rollback clears only the shadow flags and leaves the shared durable services online:

```bash
az containerapp update -g mdk-accessibility -n acp-app-staging --remove-env-vars \
  ACP_REALTIME_V1_ENABLED ACP_REALTIME_V1_REDIS_URL
az containerapp update -g mdk-accessibility -n acp-worker-staging --remove-env-vars \
  ACP_REALTIME_SHADOW_ENABLED ACP_REALTIME_SHADOW_REDIS_URL
```

## Acceptance run

Use two staging test accounts, A and B, and a mixed small scan for each. Record browser timestamps
and SSE `id` values from the shadow diagnostics only; never paste bearer tokens into logs.

| Gate | Pass condition |
| --- | --- |
| Delivery latency | Terminal-event p95 ≤ 750 ms and maximum ≤ 2 s across at least 20 jobs. |
| Reconnect/resume | Interrupt A's stream for 2–5 s. It reconnects within 3 s, sends the last Redis stream ID in `Last-Event-ID`, produces no duplicate terminal event, and reconciles if the cursor is deliberately expired. |
| Tenant isolation | A receives zero B event IDs, scan IDs, job IDs, or payload fields, and vice versa. Test both simultaneous streams. |
| Fallback | Block only `/api/realtime/v1/stream`. The panel says fallback while existing workflow status continues updating and the scan completes normally. |
| Legacy no-impact | Compare the existing status/SSE sequence and final scan snapshot with shadow off and on. Counts, terminal state, output digest, retries, and queue timings must match; shadow failures must not fail or retry a job. |
| Loss | The number of unique terminal event IDs equals the number of completed/failed jobs, and Azure logs contain zero `realtime_shadow` publish/drop errors. |

Keep the feature in staging for one business day and one overnight schedule transition. Stop the
trial and clear both enable flags if tenant isolation fails, any legacy result changes, a shadow
failure affects a job, reconnect duplicates a terminal event, or terminal-event p95 exceeds 750 ms.
Production enablement is a separate decision after the measurements are reviewed.
