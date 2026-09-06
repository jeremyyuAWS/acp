# Realtime shadow publishers

The worker-side realtime adapter is an additive observation path. The durable queue and existing
polling/SSE paths remain authoritative. Publishing is disabled unless both of these are set:

- `ACP_REALTIME_SHADOW_ENABLED=1`
- `ACP_REALTIME_SHADOW_REDIS_URL=<isolated Redis URL>`

No deployment manifest enables or wires these settings. Operators may additionally set
`ACP_REALTIME_SHADOW_TIMEOUT_MS` (default `100`) and `ACP_REALTIME_SHADOW_RETENTION` (default
`10000` entries per owner stream). Keys use the canonical private owner scope under
`acp:realtime:v1:owner`; they do not share the existing job-state namespace and never expose the
owner value in a Redis key.

Every message is validated by `RealtimeEvent` before it is queued and carries the canonical schema
version, UUID event ID, registered kind, numeric priority, private owner scope, timestamps, source
sequence, and relevant workflow identifiers. Redis stores the serialized envelope in `event` and
its UUID in `event_id`, exactly as the gateway expects. Lifecycle and terminal events are queued
individually and in order. Coalescible events with the same kind and coalesce key replace an older
pending value, bounding bursts without delaying the worker. Redis Streams use bounded approximate
`MAXLEN` retention; the gateway supplies the Redis stream ID used for replay and `Last-Event-ID`.

`metrics_snapshot()` exposes publish success, drop, total latency, and average latency counters.
All Redis work runs off the authoritative worker thread and uses bounded socket timeouts; observer,
queue, sequence, and transport failures are swallowed and counted rather than propagated to jobs.
