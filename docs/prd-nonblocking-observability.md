# PRD — Non-blocking observability and resilient Assess execution

**Status:** Implementation started. **Priority:** P0 worker isolation; P1 operational hardening.
**Incident:** Production Assess run `5cec433c609d`, 7 September 2026.

## Outcome

Assessment, remediation, discovery, and release work must continue and reach a durable terminal
state when an optional telemetry provider is slow, unavailable, or rejecting writes. Operators
must see that observability is degraded without mistaking provider health for pipeline health.

## Evidence

The production run contained 147 files. At investigation time 62 results had been persisted, but
only 30 jobs were complete: 32 jobs remained `running` after their analysis result was saved. Four
available replica tails contained eight completed file analyses, 71 Langfuse HTTP 500 messages,
and no `job.complete` event. The worker calls synchronous `lf.flush()` after persistence and before
returning to the queue. Langfuse `/api/public/health` and `/api/public/ready` both returned 200,
showing that shallow health did not cover ingestion.

An unrelated Ollama keep-alive request timed out in the API process. It was swallowed correctly
and did not block Assess, but emitted a full traceback for expected best-effort behavior.

## Requirements

### P0 — Failure containment

1. No pipeline worker may synchronously wait for telemetry export.
2. Export concurrency is bounded to one task per process; repeated flush requests are coalesced.
3. Telemetry exceptions never alter job outcome, retry count, lease, or file progress.
4. A stalled export must not create an unbounded thread, task, memory, or retry backlog.
5. Regression tests must simulate a flush that never returns and prove the worker-facing call
   returns promptly.

### P1 — Honest health and recovery

1. Record export attempts, successes, failures, duration, last success, and age without document
   names, content, user identity, or credentials.
2. Provider health must exercise a bounded ingestion canary or explicitly label shallow health;
   HTTP 200 from a landing/readiness endpoint is not proof that writes succeed.
3. Live Operations must distinguish `pipeline healthy / telemetry degraded` from worker failure.
4. Retries use bounded exponential backoff with jitter and a circuit breaker. Recovery performs
   one coalesced flush rather than replaying an unbounded in-memory queue.
5. Shutdown gets a small, explicit telemetry drain budget; expiration never delays graceful job
   requeue or container termination.
6. Expected best-effort dependency timeouts emit one structured warning rather than a traceback.

### P1 — Queue and deployment robustness

1. Reconcile running claims against current replica/worker capacity after deployment; stale claims
   remain visible as stale and are reclaimed within the documented lease bound.
2. Alert when persisted file count advances while completed job count does not, or when queue age
   rises while all slots are occupied beyond the per-file latency objective.
3. Validate the failure mode in staging by forcing telemetry ingestion to return 500 during a
   representative 147-file run. Assessment throughput and terminal job counts must remain within
   10% of the tracing-disabled baseline.

## Acceptance criteria

- With telemetry flush blocked for at least five minutes, all fixture assessment jobs complete.
- Twenty simultaneous flush requests create one exporter and at most one coalesced follow-up pass.
- No job remains `running` solely because telemetry is unavailable.
- Live Operations reports the provider degradation within two minutes and clears it after a
  successful ingestion canary.
- Existing trace redaction and deterministic trace identity remain unchanged.

## Delivery slices

1. **Started:** detach and coalesce Langfuse flush; add the stalled-provider regression.
2. Add bounded exporter state, circuit-breaker metrics, and structured logging.
3. Add ingestion-aware health and Live Operations presentation.
4. Add staging chaos coverage, throughput comparison, alerting, and the shutdown drain budget.

## Out of scope

Changing assessment findings, retrying user jobs because traces failed, storing document content
for telemetry replay, or changing production capacity during this implementation.
