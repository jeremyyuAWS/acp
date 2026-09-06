# ADR 0054 — One versioned realtime operations event contract

**Status:** Accepted — contract only; no publisher or consumer adopts it in this change
**Date:** 2026-09-06
**Related:** ADR 0042 (`scan_events`), ADR 0043 (snapshot streams), ADR 0051
(`Last-Event-ID` for remediation), ADR 0052 (structured remediation progress). Contract:
`api/realtime_events.py`. Proof: `tests/test_realtime_events.py`.

## Context

ACP has truthful facts but no common realtime wire shape. Discover and Assess send replace-in-place
snapshots; Remediate adds replayable `scan_events`; worker state and operational transitions live
in `worker_instances` and `orchestration_events`; Azure capacity and alerts are readings. A future
operations surface must not infer identity, ordering, tenancy, freshness or urgency differently for
each source. This decision defines those semantics before any emitter or client is changed.

The two durable logs remain authoritative for their current purposes. Redis is a bounded fan-out
and replay buffer, not a new system of record. Existing SSE payloads remain supported during an
additive migration.

## Decision

### Envelope and versioning

Every new event is the JSON object produced by `RealtimeEvent.to_dict()`:

```json
{
  "schema_version": "1.0",
  "event_id": "4b25c618-417d-4d90-9154-3ef7b61b44c4",
  "stream_id": "1788726645123-0",
  "kind": "assess.progressed",
  "priority": 3,
  "owner_scope": "3c70f0f0f4212b53ee81c0cd",
  "occurred_at": "2026-09-06T12:30:45.123Z",
  "observed_at": "2026-09-06T12:30:45.551Z",
  "stale_after_ms": 30000,
  "scan_id": "scan-1",
  "job_id": "job-4",
  "correlation_id": "attempt-2",
  "coalesce_key": "scan-1",
  "payload": {"completed": 3, "total": 12}
}
```

`schema_version` is MAJOR.MINOR. A minor release may add an optional field or a new registered
`kind`; consumers must ignore unknown fields. Removing, renaming, changing meaning/type, or making
an optional field required needs a new major version, media type, SSE event name and Redis prefix.
Publishers never emit an unregistered kind. `payload` is kind-specific and additive within a major
version; it must not contain content, credentials, tokens, prompts, model responses or PHI.

`event_id` is a producer-created UUID, generated once and preserved across publish retries,
Postgres replay and Redis rehydration. Consumers de-duplicate on it. `stream_id` is assigned once
by Redis `XADD`; it is transport position, not identity, and must not be copied between streams.

### Scope, clocks, freshness and ordering

The current ACP tenant boundary is normalized `owner_email`. It is SHA-256 hashed and truncated to
24 hex characters by `owner_scope()` before entering a Redis key or wire event; raw email never
appears in either. Request authorization still resolves the signed-in owner before choosing a
stream. Global worker/capacity/alert observations are copied into each owner stream they are
authorized to see; there is no cross-tenant stream.

`occurred_at` is the source's UTC instant; `observed_at` is when ACP formed the envelope. Both are
RFC 3339 UTC with milliseconds. They communicate time, never order. A source-native monotonic
position such as `scan_events.seq` may be carried as `source_seq`, but the total delivery order is
only Redis `stream_id`. Events for the same aggregate use one stream and are applied in increasing
stream-ID order. Concurrent events therefore get a deterministic delivery order without claiming
that wall clocks established causality.

`stale_after_ms` applies to readings (progress, queue depth, worker busy state and capacity), not
historical transitions. A consumer marks a reading stale when `now > observed_at + stale_after_ms`;
it does not invent zero, offline, failure or recovery. Absence of the field means no freshness
claim. Clock skew is visible as the difference between `occurred_at` and `observed_at`.

### Redis, retention and replay

One stream exists per owner and major contract version:

`acp:realtime:v1:owner:{owner_scope}:events`

Fields are `event` (the compact envelope JSON, initially without `stream_id`) and `event_id` (for
operational inspection). `XADD` assigns the entry ID; a reader binds that ID as `stream_id` while
deserializing and before SSE delivery. The stored entry is not rewritten.
Trimming retains events that are either younger than 24 hours **or** among the newest 10,000. In
other words, delete only rows outside both windows. A periodic trimmer chooses the earlier of the
24-hour cutoff ID and the 10,000th-newest ID; `MAXLEN` alone does not implement this rule.

SSE frames use `event: acp-event`, `id: {stream_id}`, and the envelope as `data`. An authenticated
fetch client sends its last applied Redis ID in `Last-Event-ID`. The server validates `<ms>-<seq>`
and replays exclusive of that ID in ascending order, at most 500 per page, before live reads. A
missing cursor means “snapshot, then live from `$`”, not historical backfill. A malformed/ahead
cursor, a cursor older than the retained first entry, or an unexpected stream version produces
`reconciliation-required`; the client fetches an authoritative snapshot before continuing. The
server never guesses from a timestamp.

### Priority and coalescing

Priorities are stable integers: 0 critical, 1 high, 2 normal, 3 low. The kind registry assigns the
priority; callers cannot promote or demote one instance. Redis order does not change by priority.
Priority controls buffering and notification only.

- Critical events and terminal events are lossless and never coalesced.
- High events may replace an identical aggregate state for at most 1 second.
- Normal readings may retain only the latest `(kind, coalesce_key)` value for at most 2 seconds.
- Low readings may retain only the latest value for at most 10 seconds.
- No `coalesce_key` means lossless. Coalescing occurs before `XADD`; published stream entries are
  immutable and are never deleted merely because a newer reading arrived.

The closed registry covers Discover, Assess, Remediate, queue, worker lifecycle, Azure capacity
and alerts. Adding a kind is an explicit contract change with a registry entry and test.

### Compatibility and rollout

Current default SSE `message` frames are unchanged byte-for-shape: their existing snapshot payload
remains directly in `data`, with no envelope and no `id`. During migration, a route sends those
legacy snapshots exactly as today and sends versioned events as the separate `acp-event` type.
Old consumers ignore named events; new consumers use named events for narrative and snapshots for
reconciliation. No current `done`, `error`, `remediation-event`, or
`reconciliation-required` meaning changes. A publisher/consumer migration is a later task and must
name which legacy frame it can finally retire; this ADR authorizes none.

## Consequences

All operational sources can share identity, tenant isolation, replay and freshness semantics
without collapsing their existing durable models. Redis loss cannot lose authoritative state: a
client reconciles from a snapshot and durable logs. Per-owner duplication of global observations
costs memory, accepted in exchange for making cross-tenant disclosure impossible by key choice.

The contract deliberately does not define UI labels, publisher timing, alert policy, Azure polling,
or durable database migrations. Those are consumers and producers of this contract, not part of it.

## Alternatives considered

**One global stream with tenant fields.** Rejected: every read would rely on a filter being applied
perfectly, while a per-owner key makes the isolation boundary structural.

**Wall-clock timestamps or UUIDs as resume cursors.** Rejected: neither is a gap-free total order
under concurrent writers. Redis IDs already provide the stream-local order replay needs.

**Replace existing SSE payloads immediately.** Rejected: snapshot consumers already ship. A named,
additive event type permits independent producer and consumer rollout and preserves ADR 0043's
snapshot-reconciliation model.
