# Canonical realtime load gate

This bounded gate tests the default-off publisher and gateway reader without changing application
configuration. Its Redis mode is for an isolated staging Redis/Valkey endpoint only; it creates
owner scopes containing a random run ID and deletes exactly those generated streams when finished.

Its in-memory mode runs in CI (`tests/load/test_canonical_realtime_gate.py`) and asserts the
STRUCTURAL checks only: zero cross-owner leakage, zero missing retry, dead-letter, failed, final
progress or warm-soak events, progress written in order, zero publisher drops, and a warm-path
batch from the persistent client. The TIMING checks — the two gateway p95s, the submit p95 and
the coalescing ratio — are measured and reported by that run but not asserted on it: a
percentile measured on a shared CI runner describes the runner (the same configuration measured
a tenfold spread in gateway p95 across fifteen identical local runs), and the coalescing ratio
counts how many publisher drains the scheduler interleaved with the submit loop. The verdict
logic itself is asserted with fixed inputs. The report carries both classes: `decision` is GO
only when every check holds and is what the staging gate exits on; `structural_decision` is
what CI asserts.

Run the local gate:

```bash
python -m performance.canonical_realtime_gate
```

Run against an isolated staging event store:

```bash
STAGING_REALTIME_REDIS_URL="$STAGING_REALTIME_REDIS_URL" \
  python -m performance.canonical_realtime_gate --redis-env STAGING_REALTIME_REDIS_URL \
  --output /tmp/canonical-realtime-gate.json
```

Do not point the command at the production queue Redis. A staging candidate is accepted only when
the command exits zero and reports `GO`. The fixed thresholds are: event-to-gateway p95 at most
250 ms (cold and warm), caller submit p95 at most 1 ms, at most 10% of burst progress submissions
written, at most 2 KiB Redis memory per retained event, zero cross-owner leakage, zero missing
final progress, retry, or dead-letter events, zero out-of-order progress, and zero publisher
drops. Lifecycle and terminal events are never coalesced.

The `validate-staging-realtime` workflow runs automatically after a successful staging deployment
and can also be dispatched manually. It executes the gate inside the staging Assess lane so the
Redis connection never leaves the Container Apps environment or appears in process arguments. A
nonzero gate exit makes the workflow a NO-GO; it does not enable the realtime feature or deploy
production. Reports say only that Redis was `configured`; they never serialize its URL. The
retired mixed-lane `acp-worker-staging` app is deliberately not used.
