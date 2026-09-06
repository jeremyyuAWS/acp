# Shadow realtime operations experiment

This package is a separate, default-off experiment. It does not import or change ACP's production
polling, SSE, worker, Redis, or deployment paths. Its keys begin with `realtime:v1`; it never reads
`REDIS_URL`, and no production manifest enables it.

## Collector

The collector emits one `infrastructure.sample` envelope per configured Azure resource at a minimum
30-second interval. Azure credentials are acquired only after explicit opt-in. Use a workload identity
or an authenticated developer session with metric-read access.

```bash
export SHADOW_REALTIME_ENABLED=1
export SHADOW_REALTIME_REDIS_URL='redis://localhost:6379/15'
export SHADOW_REALTIME_AZURE_SUBSCRIPTION_ID='<subscription>'
export SHADOW_REALTIME_TENANT_ID='local-test'
export SHADOW_REALTIME_AZURE_RESOURCE_IDS='<resource-id-1>,<resource-id-2>'
python -m shadow_realtime.collector
```

With no opt-in, the command exits without contacting Azure or Redis. Keep the Redis database and
credentials separate from production during the experiment.

## Load and chaos proof

The deterministic CI run uses an in-memory Redis Streams model and writes machine-readable JSON:

```bash
python -m shadow_realtime.harness --output shadow-realtime-results.json
```

For the Tuesday decision, repeat against the candidate Redis and gateway network path:

```bash
python -m shadow_realtime.harness --events 50000 --retention 50000 \
  --redis-url 'redis://localhost:6379/15' --output shadow-realtime-results.json
```

During that run, restart the candidate Redis and gateway once each. A Redis outage may interrupt the
producer; rerun after recovery and retain both result files. The report covers event-to-browser p95/p99
latency, publish throughput, cursor replay, Redis memory and retention, slow-client lag, lifecycle loss,
process CPU, and reconnect recovery. A `GO` requires every threshold in the JSON to pass: p95 ≤ 500 ms,
p99 ≤ 1 s, ≥ 250 events/s, 100% retained replay, zero lifecycle loss, ≤ 2 KiB per retained event,
retention overshoot ≤ 10%, slow-client lag ≤ 500 events, CPU ≤ 80%, and recovery ≤ 10 s.

The in-memory result is a CI regression gate, not production evidence. The Tuesday decision must use a
real-Redis result from the intended topology plus an observed gateway restart. Do not enable the shadow
flag in production manifests as part of this experiment.
