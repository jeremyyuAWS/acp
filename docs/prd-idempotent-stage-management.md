# PRD: Idempotent Workflow Stage Management

Status: Proposed  
Priority: P0 — correctness, trust, and recoverability  
Scope: Discover → Assess → Remediate → Conformance → Release  
Primary consumers: stage APIs, workers, durable events, Live Operations, stage cards, audit exports

## 1. Problem

ACP executes one user workflow across several asynchronous stages, worker pools, browser sessions,
and durable stores. A request can be retried by the browser, replayed by a queue, reclaimed after a
lease expires, or resumed after a deployment. Without one stage-management contract, each subsystem
can be internally correct while the workflow as a whole becomes inconsistent.

Observed failure modes include:

- Duplicate submissions create multiple executions for the same immutable input.
- An older execution updates counters after a newer execution becomes current.
- Queue rows, event rows, stage cards, and stage-specific endpoints disagree.
- A worker retry increments totals or repeats an external write.
- “Complete” describes queue processing while evidence or reconciliation remains incomplete.
- A cached or delayed event moves the UI backward.
- A deployment interrupts work without a durable continuation point.
- Counts with different units are combined into a plausible but false total.

The system needs a single durable authority for stage identity, state transitions, outputs, and
cross-stage handoffs.

## 2. User outcome

For any workflow and stage, a user or auditor must be able to answer:

1. Which immutable input snapshot did this execution consume?
2. Was this request reused, newly accepted, resumed, or rejected as conflicting?
3. Which execution is current?
4. What work is queued, leased, completed, failed, or awaiting a decision?
5. Which outputs and evidence belong to this execution?
6. Have all expected inputs reached exactly one terminal outcome?
7. Can a retry safely occur without duplicating work or external effects?
8. Which revision produced the values currently displayed?

Refresh, navigation, reconnection, repeated submission, worker replay, and deployment must not
change the answer.

## 3. Required terminology

| Term | Definition |
|---|---|
| Workflow | The durable user-owned lifecycle spanning all stages |
| Workflow revision | A monotonic revision of workflow state and stage selection |
| Stage | Discover, Assess, Remediate, Conformance, or Release |
| Input snapshot | Immutable, content-addressed inputs consumed by one stage |
| Request fingerprint | Canonical digest of user intent, policy, scope, and options |
| Stage execution | One idempotent attempt group for a stage and immutable input |
| Execution ID | Stable identity derived from workflow, stage, snapshot, and request fingerprint |
| Work item | One independently claimable unit within an execution |
| Attempt | One lease-bound worker effort for a work item |
| Durable event | Append-only fact with a globally idempotent event ID |
| Output manifest | Immutable list of outputs and evidence produced by an execution |
| Current execution | The only execution allowed to update the stage’s current projection |
| Terminal processing | Every expected work item has a terminal processing outcome |
| Reconciled | Every expected input and output is accounted for with invariant checks passing |

“Accepted,” “processing complete,” “reconciled,” “successful,” and “published” are distinct states.

## 4. Design principles

1. **Identity before work.** Persist or reuse the stage execution before enqueueing work.
2. **Immutable inputs.** Workers consume a snapshot ID, never mutable live scope or settings.
3. **One current writer.** Only the current execution may update the current stage projection.
4. **At-least-once delivery, exactly-once effects.** Queue and event delivery may repeat; durable
   state and external writes must not.
5. **Compare-and-set transitions.** Every mutable record advances from an expected revision.
6. **Append facts, project views.** Events and evidence are durable; UI snapshots are projections.
7. **Unknown is not zero.** Missing or unverifiable values remain `null` and fail visibly.
8. **Units never mix.** Every counter names and preserves its unit.
9. **History is immutable.** Superseded and failed executions remain queryable evidence.
10. **Fail closed.** Invariant breaches set integrity failure; they are never repaired cosmetically.

## 5. Canonical identity model

### 5.1 Input snapshot

Each stage must consume a content-addressed snapshot containing all inputs that can affect output:

```json
{
  "workflow_id": "wf_123",
  "stage": "remediate",
  "upstream_execution_id": "exec_assess_abc",
  "document_manifest_digest": "sha256:...",
  "policy_digest": "sha256:...",
  "rubric_digest": "sha256:...",
  "configuration_digest": "sha256:...",
  "created_at": "ISO-8601"
}
```

The snapshot is immutable. Changing documents, scope, policy, rubric, approved decisions, or
relevant configuration creates a new snapshot.

### 5.2 Request fingerprint

Canonicalize request intent as sorted JSON with explicit defaults, normalized identifiers, and no
ephemeral values. Exclude timestamps, request IDs, browser session IDs, and presentation-only data.

```text
request_fingerprint = SHA-256(canonical request intent)
```

### 5.3 Execution ID

```text
execution_id = SHA-256(
  workflow_id,
  stage,
  input_snapshot_id,
  request_fingerprint
)
```

The same semantic request against the same snapshot must return the same execution ID. A changed
snapshot or changed intent must return a different execution ID.

## 6. Target data model

### 6.1 Stage execution

```json
{
  "execution_id": "stable idempotency key",
  "workflow_id": "wf_123",
  "workflow_revision": 12,
  "stage": "remediate",
  "input_snapshot_id": "sha256:...",
  "request_fingerprint": "sha256:...",
  "state": "processing",
  "revision": 31,
  "is_current": true,
  "expected_items": 142,
  "terminal_items": 34,
  "output_manifest_id": null,
  "created_at": "ISO-8601",
  "updated_at": "ISO-8601"
}
```

Unique constraint:

```text
(workflow_id, stage, input_snapshot_id, request_fingerprint)
```

At most one nonterminal execution may be current for `(workflow_id, stage)`.

### 6.2 Work item

```json
{
  "work_item_id": "deterministic identity",
  "execution_id": "exec_...",
  "input_id": "stable document or finding identifier",
  "state": "queued",
  "revision": 4,
  "attempt": 2,
  "lease_owner": null,
  "lease_expires_at": null,
  "result_digest": null,
  "terminal_reason": null
}
```

Unique constraint: `(execution_id, input_id)`. Retrying an execution updates its existing work
items; it does not add another generation beside them.

### 6.3 Attempt

Attempts are append-only and identify worker, lease interval, start/end timestamps, outcome, and
error classification. Attempts do not own business outcomes; the work item does.

### 6.4 Durable event

```json
{
  "event_id": "publisher-stable id",
  "execution_id": "exec_...",
  "work_item_id": "item_...",
  "event_type": "work_item.completed",
  "expected_revision": 3,
  "resulting_revision": 4,
  "payload_digest": "sha256:...",
  "occurred_at": "ISO-8601",
  "recorded_at": "ISO-8601"
}
```

`event_id` is globally unique. A duplicate event returns the already-recorded result and performs
no state change.

### 6.5 Side-effect receipt

Every external write—SharePoint upload, Drive write, release publish, notification—must use a
deterministic effect ID and persist a receipt:

```text
effect_id = SHA-256(execution_id, work_item_id, effect_type, destination, content_digest)
```

The receipt is written before retry acknowledgement. A repeated request reuses the receipt or
verifies the destination; it never blindly writes again.

## 7. State machine

Allowed execution states:

```text
accepted → queued → processing → processing_complete → reconciling → succeeded
                         │                 │                 │
                         ├──────────────→ failed             └→ integrity_failed
                         ├──────────────→ cancelled
                         └──────────────→ paused → processing
```

Rules:

- `processing_complete` means all work items are terminal; it does not imply success.
- `succeeded` requires reconciliation and a sealed output manifest.
- `failed`, `cancelled`, and `integrity_failed` are terminal for that execution.
- A retry of a failed execution either requeues failed work items in the same execution under the
  same idempotency key or creates a new execution only when snapshot or intent changes.
- A superseding execution atomically sets the previous execution `is_current=false`.
- Events from non-current executions may update their historical records but cannot update the
  current stage projection.

All transitions use:

```sql
UPDATE stage_execution
SET state = :next_state,
    revision = revision + 1,
    updated_at = :now
WHERE execution_id = :execution_id
  AND revision = :expected_revision
  AND state IN (:allowed_prior_states)
```

Zero updated rows means conflict, stale event, or invalid transition—not success.

## 8. Submission semantics

For every stage submission, perform one transaction:

1. Resolve and validate the immutable input snapshot.
2. Canonicalize intent and compute the request fingerprint.
3. Compute the execution ID.
4. Acquire a workflow-stage advisory lock or equivalent serializable guard.
5. Return the existing execution when the identity already exists.
6. Reject a different submission while another current execution is nonterminal, unless the
   caller explicitly cancels or supersedes it.
7. Insert the execution and deterministic work items.
8. Commit.
9. Publish queue messages using an outbox tied to committed work-item IDs.

The response must distinguish:

```json
{
  "execution_id": "exec_...",
  "accepted": true,
  "reused": false,
  "resumed": false,
  "superseded_execution_id": null,
  "revision": 1
}
```

## 9. Worker and lease semantics

- Claim uses an atomic update or `SELECT ... FOR UPDATE SKIP LOCKED`.
- A lease heartbeat proves liveness only; it is not material progress.
- Material progress requires a durable event or terminal work-item transition.
- A reclaimed attempt increments attempt count but not business counters.
- Result application checks execution currency, work-item revision, and event ID.
- A late worker from an expired lease cannot overwrite a newer attempt’s result.
- Exhausted attempts produce one terminal failure outcome and one durable event.

## 10. Projection and snapshot contract

Every UI and operational surface consumes one canonical, revisioned stage snapshot:

```json
{
  "workflow_id": "wf_123",
  "workflow_revision": 12,
  "stage": "remediate",
  "execution_id": "exec_...",
  "input_snapshot_id": "sha256:...",
  "request_fingerprint": "sha256:...",
  "revision": 31,
  "state": "processing",
  "generated_at": "ISO-8601",
  "last_durable_update_at": "ISO-8601",
  "counts": {
    "documents": {"total": 142, "terminal": 34, "processing": 4, "waiting": 104},
    "findings": {"assessed": 159, "accounted": 96, "unaccounted": 63},
    "changes": {"applied": 2310, "verified": 2179}
  },
  "integrity": {"ok": true, "affected": [], "violations": []}
}
```

Requirements:

- No client reconstructs state or totals from another endpoint.
- Snapshots are monotonic by `(execution_id, revision)`.
- A lower revision is ignored.
- A changed execution ID replaces, rather than merges with, the previous snapshot.
- Terminal snapshots are durable and replayable after refresh, logout, and reconnect.
- Unknown values are `null`, never inferred as zero.

## 11. Reconciliation invariants

Each stage declares expected inputs, mutually exclusive terminal outcomes, and outputs.

Global invariants:

```text
expected work items = one current work-item row per expected input
expected inputs = sum(mutually exclusive processing outcomes)
current projection = rows from current execution only
output manifest entries = successful output receipts for current execution
```

Stage-specific invariants include:

- Discover: scoped source items equal discovered + excluded + inaccessible + failed.
- Assess: assessed documents equal completed + skipped + failed; finding totals equal failing trace
  instance counts.
- Remediate: assessed findings equal exactly one current finding disposition each.
- Conformance: assertions reference one Assessment snapshot and one Remediation output manifest.
- Release: published + failed + excluded equals the sealed release manifest; every published item
  has one side-effect receipt.

Any breach sets:

```json
{
  "integrity": {
    "ok": false,
    "affected": ["work_item_partition"],
    "violations": [{"code": "overcount", "expected": 142, "observed": 143}]
  }
}
```

The UI shows “Accounting temporarily inconsistent” and does not adjust totals to make them fit.

## 11.1 Canonical measurement dictionary

Every number shown from Discover through Release must come from this dictionary. A stage may omit
a metric that is not relevant, but it may not rename, reconstruct, or change the unit.

| Canonical metric | Unit | Meaning | Durable authority |
|---|---|---|---|
| `scope.documents` | documents | Immutable documents selected for the workflow revision | input snapshot manifest |
| `discover.candidates` | source items | Connector items examined before scope and eligibility rules | Discover execution snapshot |
| `discover.in_scope` | documents | Documents admitted to the immutable workflow scope | input snapshot manifest |
| `discover.excluded` | documents | Candidate documents excluded by an explicit rule | Discover work-item outcomes |
| `discover.inaccessible` | documents | Candidate documents ACP could not read | Discover work-item outcomes |
| `assess.documents_terminal` | documents | In-scope documents with a terminal Assessment outcome | Assess work-item outcomes |
| `assess.findings` | finding instances | Accessibility violation instances detected in the immutable Assessment snapshot | sum of failing criterion traces |
| `assess.criteria_failed` | criterion traces | Document-and-rule traces whose outcome is FAIL | criterion-trace rows |
| `remediate.documents_terminal` | documents | Documents with a terminal remediation-processing outcome | Remediate work-item outcomes |
| `remediate.findings_accounted` | finding instances | Assessed findings with exactly one current disposition | finding-disposition ledger |
| `remediate.review_items` | review cards | Human decisions currently represented in the review queue | review-item rows |
| `remediate.review_findings` | finding instances | Assessed findings represented by those review cards | ledger links to review items |
| `remediate.changes_applied` | changes | Recorded edits attempted or written | applied-change evidence |
| `remediate.changes_verified` | changes | Before/after changes that passed re-check | verification evidence |
| `release.manifest_documents` | documents | Documents sealed into the Release execution | Release manifest |
| `release.published_documents` | documents | Manifest documents with a successful publication receipt | side-effect receipts |
| `release.findings_resolved` | finding instances | Reconciled findings included in published document revisions | Release-to-ledger links |
| `release.residual_findings` | finding instances | Findings still open in the released revision | Release-to-ledger links |

Forbidden substitutions include:

```text
finding instances ≠ criterion traces
finding instances ≠ issue rows
finding instances ≠ review cards
finding instances ≠ changes
documents processed ≠ documents changed
documents changed ≠ documents published
```

## 11.2 Cross-stage cohort continuity

The workflow header must display one durable cohort line on every stage:

```text
Workflow scope · 142 documents · Assessment snapshot assess_abc · revision 12
```

The same `scope.documents` value and snapshot identity carry forward until a user deliberately
creates a new workflow revision. Stage-local filters may change what a panel displays, but they may
not change the workflow total. Filtered values must be labeled, for example:

```text
Showing 18 of 142 workflow documents
```

If a source document changes after Assessment, ACP must not silently replace it inside the cohort.
It is marked stale and requires a new snapshot or an explicit versioned exception.

## 11.3 Stage handoff equations

Discover:

```text
candidate source items
  = in-scope documents
  + excluded documents
  + inaccessible documents
  + unsupported items
  + failed discovery items
```

Assess:

```text
in-scope documents
  = assessed successfully
  + skipped with reason
  + failed assessment
```

```text
assessment findings
  = SUM(finding_count) over FAIL criterion traces
```

Remediate:

```text
in-scope remediation documents
  = completed
  + awaiting review
  + skipped with reason
  + failed
```

```text
assessment findings
  = resolved and verified
  + awaiting review
  + approved awaiting verification
  + unchanged — no eligible fix
  + remediation failed
  + excluded by policy
  + superseded by reassessment
```

Release:

```text
release manifest documents
  = published
  + publication failed
  + excluded before publication
```

```text
released finding set
  = resolved findings included in published revisions
  + residual findings included in published revisions
```

The left side of every equation is stored, not recomputed from the right. The equation is an
integrity check, not the source of the total.

## 11.4 Intuitive stage summaries

Each stage uses the same information order:

1. Workflow cohort and snapshot identity.
2. The stage’s primary progress unit.
3. The stage’s terminal outcome partition.
4. Secondary evidence in separate unit-labeled regions.
5. Reconciliation state and freshness.

Recommended summaries:

```text
Discover · 142 documents admitted to this workflow
166 source items examined · 18 excluded · 6 inaccessible
```

```text
Assess complete · 142 of 142 documents assessed
159 accessibility findings across 47 failing criterion traces
```

```text
Remediation complete · 142 of 142 documents reached a terminal outcome
159 of 159 findings accounted for · 92 resolved and verified · 49 awaiting review
2,179 verified changes
```

```text
Release · 138 of 142 manifest documents published
92 resolved findings included · 49 residual findings included
4 publication failures
```

Numbers of different units must appear on separate lines or in visibly distinct regions. A tooltip
may explain a metric but cannot be the only place its unit is identified.

## 11.5 Unknown, pending, stale, and inconsistent values

These states must be visibly different:

| State | Display | Meaning |
|---|---|---|
| Known zero | `0 findings` | Authoritative query completed and found none |
| Unknown | `Not yet available` | No authoritative value exists yet |
| Pending | `Calculating…` | An execution is expected to produce the value |
| Stale | `159 findings · from revision 11` | Durable value exists but is not for the current revision |
| Inconsistent | `Accounting temporarily inconsistent` | An invariant failed |

The UI must never turn `null`, a missing field, a failed request, or a stale snapshot into zero.

## 11.6 Rounding, formatting, and accessibility

- Reconciliation and audit counts are always whole, unrounded integers.
- Rates, percentages, and durations are secondary; they never replace the underlying counts.
- Percentages identify numerator and denominator in accessible text.
- Compact notation such as `2.1k` is allowed only beside or behind an accessible exact value.
- Singular and plural units are correct in visible and screen-reader text.
- Color, animation, and iconography never carry the only distinction between units or states.
- Delta animation announces neither every tick nor decorative intermediate values.
- Every compact card and expanded panel uses the same canonical metric value and revision.

## 11.7 Snapshot consistency rules

- One rendered screen uses one snapshot revision; it never mixes fields from separate responses.
- A newer snapshot replaces all stage metrics atomically.
- If one metric cannot be produced, its value is `null`; sibling values retain their authoritative
  values and the integrity block identifies the affected metric.
- SSE events are invalidations or durable facts, not permission for the client to increment totals.
- After reconnect, refresh the complete snapshot before rendering later events.
- Stage cards, detail panels, Live Operations, exports, and release manifests all cite the same
  execution and snapshot revision.

## 12. Cross-stage handoff

A downstream stage accepts only a sealed upstream output manifest. The handoff records:

- Upstream execution and snapshot IDs.
- Upstream terminal revision.
- Manifest digest and item count.
- Policy/rubric/configuration digests.
- Actor and timestamp.

A newer upstream snapshot never mutates an existing downstream execution. It creates a new handoff
and a new downstream execution while preserving the previous chain as historical evidence.

## 13. Concurrency and stale-write protection

- Serialize submission per `(workflow_id, stage)`.
- Use revision compare-and-set for execution, work item, finding disposition, and output manifest.
- Validate lease token and attempt number when applying worker results.
- Validate `is_current` before updating current projections.
- Treat duplicate event IDs as successful no-ops.
- Treat the same event ID with a different payload digest as an integrity violation.
- Never allow one execution’s batch, counts, evidence, or receipts into another execution.

## 14. Pause, cancel, resume, and deployment

- Pause prevents new claims but does not mislabel leased work as stopped.
- Cancel marks queued work terminal and requests cancellation from leased attempts.
- Resume reuses the same execution and requeues eligible work items.
- Deployment checks durable queued/running work before worker replacement.
- Graceful worker shutdown stops claims, checkpoints work, and releases or completes leases.
- An emergency replacement is explicit, audited, and followed by lease reclamation.
- Reclaimed work must reuse deterministic work-item and side-effect identities.

## 15. Observability and auditability

Live Operations exposes, from the canonical snapshot:

- Workflow, snapshot, execution, work-item, and attempt identifiers.
- Current and historical execution status.
- Snapshot revision and last durable update.
- Queue, lease, retry, and terminal counts by unit.
- Reconciliation status and integrity violations.
- Output manifests and side-effect receipts.
- Links to evidence and human decisions.

Logs and traces carry `workflow_id`, `stage`, `execution_id`, `work_item_id`, `attempt`, and
`event_id`. They never serve as the source of truth for user-visible state.

## 16. API requirements

Minimum endpoints:

```text
POST /workflows/{workflow_id}/stages/{stage}/executions
GET  /workflows/{workflow_id}/stages/{stage}/executions/current
GET  /stage-executions/{execution_id}
GET  /stage-executions/{execution_id}/snapshot
GET  /stage-executions/{execution_id}/events
POST /stage-executions/{execution_id}/pause
POST /stage-executions/{execution_id}/resume
POST /stage-executions/{execution_id}/cancel
POST /stage-executions/{execution_id}/supersede
```

Mutations accept an idempotency key and expected revision. Conflict responses return the current
execution ID, revision, and allowed next actions.

## 17. Required tests

### Identity and submission

- Identical snapshot and intent return the same execution and work-item IDs.
- Semantically identical JSON with different key order returns the same fingerprint.
- Changed scope, policy, rubric, configuration, or upstream manifest creates a new execution.
- Two concurrent submissions create one execution.
- A conflicting live execution is rejected with its identity.

### Queue and workers

- Duplicate queue delivery causes one transition and one counter increment.
- A stale lease result cannot overwrite a newer attempt.
- Reclaiming work does not create another work item.
- Failed work requeues in place when retrying the same execution.
- Exhausted retries create one terminal failure.

### Events and revisions

- Replayed event IDs have no effect.
- Same event ID with different payload fails integrity.
- Wrong expected revision returns conflict without mutation.
- Events from historical executions cannot alter current totals.
- Snapshot revisions never move backward across SSE reconnect.

### Side effects

- Retried SharePoint/Drive writes reuse an existing receipt.
- Retried Release publish does not create duplicate artifacts.
- A crash after external success but before acknowledgement recovers by destination verification.

### Reconciliation

- Every stage’s mutually exclusive buckets equal its expected input count.
- Missing rows, duplicates, overcounts, and invalid states create visible integrity violations.
- Unknown inputs remain `null` rather than zero.
- Historical batches and executions never contribute to current reconciliation.

### Lifecycle

- Pause, resume, cancel, worker restart, deployment, and sign-in refresh preserve execution identity.
- Terminal snapshots survive navigation, reconnect, and process restart.
- A new upstream snapshot preserves the old execution chain as historical evidence.

## 18. Delivery phases

### Phase 1 — Canonical execution identity

- Introduce immutable stage snapshots and request fingerprints.
- Persist deterministic execution and work-item IDs.
- Enforce one current execution per workflow stage.
- Return explicit accepted/reused/resumed/conflict semantics.

### Phase 2 — Revisioned state and event idempotency

- Add compare-and-set revisions to executions and work items.
- Add append-only events with payload-digest replay protection.
- Enforce lease token and attempt checks.
- Requeue failed work in place.

### Phase 3 — Reconciled projections

- Define stage-specific partitions and integrity invariants.
- Build one revisioned snapshot per execution.
- Move all UI and Live Operations surfaces to that snapshot.
- Preserve terminal snapshots durably.

### Phase 4 — Exactly-once external effects

- Add deterministic side-effect IDs and receipts.
- Make provider writes and release publication retry-safe.
- Add destination verification for ambiguous outcomes.

### Phase 5 — Cross-stage lineage and recovery

- Seal output manifests and bind downstream stages to them.
- Preserve historical execution chains.
- Add graceful deployment checkpointing and audited emergency recovery.
- Add operator repair tools that append corrective evidence rather than rewrite history.

## 19. Acceptance criteria

This feature is complete when:

- Repeating any stage request with identical inputs never creates duplicate work or effects.
- Every stage consumes an immutable, identifiable upstream snapshot.
- Only one current execution can update a workflow stage’s current state.
- Late workers and historical executions cannot alter current projections.
- Every mutable transition is revision-protected and every event is replay-safe.
- Every expected input has exactly one current work-item outcome.
- Every external effect has one durable, deterministic receipt.
- All counts retain explicit units and reconcile exactly where declared exact.
- Unknown or inconsistent data fails visibly and safely.
- All UI and operational surfaces consume the same revisioned snapshot.
- Refresh, reconnection, retry, restart, and deployment preserve the same durable accounting.
