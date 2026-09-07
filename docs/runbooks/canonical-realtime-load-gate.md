# Canonical realtime load gate

This bounded gate tests the default-off publisher and gateway reader without changing application
configuration. Its in-memory mode is deterministic CI coverage. Its Redis mode is for an isolated
staging Redis/Valkey endpoint only; it creates owner scopes containing a random run ID and deletes
exactly those generated streams when finished.

Run the local gate:

```bash
python -m performance.canonical_realtime_gate
```

Run against an isolated staging event store:

```bash
python -m performance.canonical_realtime_gate --redis-url "$STAGING_REALTIME_REDIS_URL" \
  --output /tmp/canonical-realtime-gate.json
```

Do not point the command at the production queue Redis. A staging candidate is accepted only when
the command exits zero and reports `GO`. The fixed thresholds are: event-to-gateway p95 at most
250 ms, caller submit p95 at most 1 ms, at most 10% of burst progress submissions written, at most
2 KiB Redis memory per retained event, zero cross-owner leakage, zero missing retry/dead-letter
events, and zero publisher drops. Lifecycle and terminal events are never coalesced.
