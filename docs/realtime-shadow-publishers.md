# Realtime shadow publishers

The worker-side realtime adapter is an additive observation path. The durable queue and existing
polling/SSE paths remain authoritative. Publishing is disabled unless both of these are set:

- `ACP_REALTIME_SHADOW_ENABLED=1`
- `ACP_REALTIME_SHADOW_REDIS_URL=<isolated Redis URL>`

No deployment manifest enables or wires these settings. Operators may additionally set
`ACP_REALTIME_SHADOW_TIMEOUT_MS` (default `100`) and `ACP_REALTIME_SHADOW_RETENTION` (default
`10000` entries per tenant stream). Keys live under `realtime:v1`; they do not share the existing
job-state namespace.

Every message carries the v1 envelope fields `event_id`, `event_version`, `event_type`,
`occurred_at`, `tenant_id`, `correlation_id`, `source`, `priority`, `sequence`, and `payload`.
High-priority lifecycle transitions are queued individually and in order. Low-priority progress
events with the same tenant, correlation, and type coalesce to their newest value. Redis Streams
use bounded `MAXLEN` retention, and `RedisStreamTransport.replay()` reads strictly after the
provided `Last-Event-ID` cursor.

`metrics_snapshot()` exposes publish success, drop, total latency, and average latency counters.
All Redis work runs off the authoritative worker thread and uses bounded socket timeouts; observer,
queue, sequence, and transport failures are swallowed and counted rather than propagated to jobs.
