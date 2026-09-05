# PRD — Remediation Real-Time Operations Panel v2

**Product:** ACP
**Scope:** Remediate workspace, live job status, verification, review handoff, and corrected-copy delivery
**Status:** Proposed · **Priority:** High · **Dependency:** build on PR #1413 after it merges
**Owner outcome:** Make every remediation run understandable and trustworthy while it is happening, without requiring users to interpret queues, workers, or contradictory counters.

## 1. Problem

The current Remediate panel exposes useful signals, but it does not combine them into one coherent account of the run. A user can simultaneously see an "Applying fixes" action, zero active documents, all documents queued, corrected copies already saved, and a source label that does not match the selected scan. These may each reflect a real subsystem, yet together they make the product look unreliable.

The interface does not answer the questions a compliance officer actually has:

1. Did ACP accept this remediation run?
2. Is work progressing, waiting, retrying, or stalled?
3. What is ACP changing right now, and why is it allowed to do so?
4. Which corrected documents passed independent verification?
5. What failed, what needs human review, and what should I do next?
6. Where were corrected copies written, and can I recover the originals?

This is primarily a truth-model problem. Faster animation or more frequent polling cannot repair counters whose meanings, scopes, and freshness differ.

## 2. Product outcome

**The Remediation Real-Time Operations Panel is the authoritative, live narrative of one remediation run—from durable acceptance through corrected-copy delivery and independent verification.**

At any moment, a user can identify:

- the run and source being processed;
- its current phase and whether that phase is making progress;
- completed, active, waiting, review, failed, and skipped work;
- the current document and approved remediation lane;
- telemetry freshness and any uncertainty;
- a realistic completion estimate when evidence supports one;
- the next action required from ACP or the user.

The panel prioritizes outcomes and intervention. Infrastructure detail remains available through **View in Monitor**, but is not required to understand ordinary progress.

## 3. Goals

- Establish one server-owned run state and one reconciled set of counters.
- Show visible progress within two seconds of a durable state change.
- Distinguish "queued but healthy" from "waiting," "retrying," "stalled," and "unknown."
- Separate generated fixes, applied fixes, verified documents, and delivered corrected copies.
- Make automatic remediation policy and verification evidence inspectable.
- Route exceptions directly into grouped review or authoring workflows.
- Preserve accessible operation for keyboard and screen-reader users.
- Remain truthful during reconnects, deployments, worker loss, and partial telemetry failure.

## 4. Non-goals

- Replacing the Monitor workspace for fleet-wide infrastructure diagnosis.
- Showing raw logs in the primary remediation experience.
- Treating model confidence as proof that a fix is safe.
- Modifying original source documents in place.
- Inventing exact queue positions or finish times without sufficient evidence.
- Rendering every finding as a separate live row.
- Letting the browser infer completion from local timers or counter arithmetic.

## 5. Users and jobs to be done

### Compliance officer

- Confirm that the intended SharePoint, OneDrive, Google Drive, Blob, or upload scan is being remediated.
- Know whether the run is progressing and when attention is required.
- Review exceptions without watching routine work.
- Produce evidence that fixes were independently verified.

### Content owner or reviewer

- Understand what changed in a specific document.
- Compare before and after evidence.
- Supply missing content or approve ambiguous proposals.
- Locate the corrected copy and original.

### Operator or administrator

- Identify stalled work, worker loss, provider throttling, and delivery failures.
- Correlate the user-visible run with detailed Monitor telemetry.
- Retry only the failed scope without duplicating successful work.

## 6. Experience architecture

The panel has five persistent regions. Each region answers a different question and keeps its own information density.

### A. Run identity and control bar — "What am I looking at?"

Display:

- run status and plain-language summary;
- assessment timestamp and remediation start timestamp;
- immutable run ID with copy action;
- source provider, tenant/site, library or folder, and scan snapshot;
- policy version and execution mode: automatic, approved batch, or review-only;
- primary action appropriate to state;
- **Run details** and **View in Monitor** links.

The source shown here comes from the remediation run record. It must not be inferred from the signed-in account or default connector. If the run references a SharePoint scan, the panel must never label it OneDrive.

### B. Phase rail — "Where is the run?"

Show the ordered lifecycle:

1. Preparing
2. Applying approved fixes
3. Re-checking corrected documents
4. Saving corrected copies
5. Finalizing evidence

Each phase has one state: pending, active, completed, completed with exceptions, failed, or skipped. The rail is derived from durable phase events, not optimistic client transitions.

Parallel work is allowed. The rail shows the furthest active phases and explains overlap, for example: "Applying fixes while 18 completed documents are being re-checked."

### C. Outcome counters — "How much is done?"

Use a reconciled partition of the run's document scope:

| Counter | Definition |
|---|---|
| Completed | Document reached a terminal successful outcome for this run |
| Processing | A valid worker attempt is actively changing or verifying the document |
| Waiting | Eligible work has not yet been claimed |
| Review | Automatic work stopped because a human decision or authored value is required |
| Failed | No automatic attempts remain |
| Skipped | In scope, but no eligible approved fix was applied |

The six counters must always sum to **Total documents in run**. Findings and fixes are shown separately because one document can contain many findings.

Secondary outcome metrics:

- fixes applied;
- fixes independently verified;
- verification failures;
- corrected copies delivered;
- corrected copies pending delivery;
- individual review items and grouped review patterns.

Never use "Verified" without naming its unit. Use **Documents verified** or **Fixes verified**.

### D. Live workstream — "What is happening now?"

Show up to three active document cards, plus a compact "and N more" summary for parallel work. Each card contains:

- filename and document type;
- source location breadcrumb;
- active phase;
- criterion and fix strategy;
- policy lane: deterministic, independently verifiable automatic, grouped approval, individual review, or authoring;
- elapsed time in current phase;
- latest progress timestamp;
- attempt number when retrying.

Use human-readable activity messages:

- "Adding a text alternative to image 1 of 3"
- "Re-checking WCAG 1.1.1 after correction"
- "Saving the corrected copy to SharePoint"
- "Waiting for Microsoft Graph after a rate-limit response; retrying in 22 seconds"

Do not imply serial processing by naming one "current file" when several documents are active.

### E. Exceptions and recent activity — "Does anyone need to act?"

Lead with actionable exceptions, grouped by response:

- **Review patterns** — one scoped decision can cover equivalent proposals.
- **Individual review** — semantic or high-impact decisions.
- **Needs authoring** — ACP has no substantive proposed value.
- **Failed documents** — exhausted automatic retries.

Below the action groups, show a bounded, reverse-chronological activity feed. Events include document, phase, result, timestamp, and correlation link. Routine increments are summarized; failures and human-action transitions remain individually visible.

## 7. Run-state contract

The backend owns the state machine. The client renders it and may request reconciliation; it never derives a terminal state.

### Run states

| State | Meaning | Primary user message |
|---|---|---|
| Draft | Eligible fixes are calculated but no durable run exists | Review scope and start |
| Accepted | Durable run exists; no work has been claimed | Remediation accepted |
| Running | At least one eligible attempt is active or progress was recently observed | Remediation in progress |
| Waiting | Work remains but no compatible processing slot is currently active | Waiting for processing capacity |
| Retry scheduled | Remaining work is delayed until a known retry time | Temporary issue; retry scheduled |
| Needs attention | Automatic work can continue only after a user decision | Review required |
| Paused | An operator or policy deliberately stopped new claims | Run paused |
| Stalled | Work is non-terminal and has exceeded its phase-specific progress threshold | Progress has stopped |
| Completing | Document work is terminal; evidence or delivery reconciliation remains | Finalizing results |
| Completed | All scoped work is terminal and reconciled | Remediation complete |
| Completed with exceptions | Successful work is complete; review, skipped, or failed items remain | Automatic work complete; exceptions remain |
| Failed | The run cannot continue automatically | Remediation failed |
| Cancel requested | Cancellation is durable but active attempts may still be draining | Stopping safely |
| Cancelled | No further attempts may publish results | Remediation cancelled |

### State precedence

The displayed run state follows explicit server precedence, not whichever request returns last:

`Failed > Stalled > Needs attention > Retry scheduled > Waiting > Running > Completing > Completed with exceptions > Completed`

Cancellation states override normal processing states. "Applying fixes" is permitted only when at least one valid attempt is in the applying phase. A queued run with zero active attempts displays **Waiting**, not **Applying fixes**.

## 8. Real-time data model

### Durable run snapshot

Every snapshot includes:

- `run_id`, `scan_id`, owner/workspace scope, and source identity;
- monotonic `revision` and server `generated_at`;
- run state, reason code, and plain-language explanation key;
- total document and finding scopes;
- reconciled document counters;
- secondary fix, verification, review, and delivery counters;
- phase summaries;
- active attempt summaries;
- retry and stall metadata;
- links to Monitor, audit evidence, corrected copies, and review queues.

### Event stream

The preferred transport is Server-Sent Events because updates are server-to-client, reconnect semantics are simple, and ordinary enterprise proxies handle it well. Events include a monotonic ID and the resulting run revision.

Required event types:

- run accepted or state changed;
- phase started or completed;
- document claimed, progressed, retried, or terminal;
- fix applied;
- verification passed or failed;
- corrected copy delivered or delivery failed;
- review or authoring requested;
- heartbeat and reconciliation required.

The browser reconnects with the last event ID. On a gap, restart, revision mismatch, or event-retention expiry, it fetches a fresh snapshot before applying more events.

### Polling fallback

If streaming is unavailable, poll the run snapshot while active with bounded backoff and jitter. Polling stops for terminal runs. Browser visibility may reduce refresh frequency but must not affect backend processing.

## 9. Freshness, uncertainty, and reconciliation

Every live region displays freshness:

- **Live** — stream connected and snapshot within the expected heartbeat window.
- **Reconnecting** — stream interrupted; last confirmed update remains visible with its age.
- **Delayed** — update age exceeds the warning threshold.
- **Unknown** — the server cannot currently reconcile one or more required signals.
- **Stalled** — the backend has positively determined that progress stopped.

Never replace unknown data with zero. Never retain a green **Live** badge when the stream is disconnected.

The server validates these invariants before publishing a snapshot:

- document outcome partition equals total document scope;
- verified fixes do not exceed applied fixes;
- delivered corrected copies do not exceed successfully completed documents eligible for delivery;
- a terminal run has no publish-capable active attempt;
- source identity matches the referenced scan snapshot;
- every active attempt has a valid lease and recent heartbeat;
- all counters share the same run revision.

When an invariant cannot be reconciled, the panel displays **Status temporarily inconsistent**, names the affected metric, keeps the last confirmed values, and links to Monitor. It does not silently choose one subsystem's number.

## 10. Estimates and throughput

Show an estimated completion range only after enough recent, comparable work exists. The estimate must account for:

- document type and size;
- remediation and verification lane;
- active compatible slots;
- recent per-phase throughput;
- provider rate limits and scheduled retries;
- corrected-copy destination latency.

Display a range and confidence, such as **Estimated 8–12 minutes · based on 27 completed documents**. Before calibration, show **Estimating after the first results**. Do not show a countdown that resets repeatedly.

Throughput is reported as a rolling observed rate with its window, for example **6.4 documents/min · last 5 min**, not a timeless single number.

## 11. Error and recovery experience

Errors are classified by scope and user action:

| Class | Example | Panel behavior |
|---|---|---|
| Automatic retry | Provider throttle, transient network failure | Keep work in Retry scheduled; show next attempt |
| Document failure | Corrupt file, unsupported package | Mark document failed; continue other work |
| Verification failure | Fix did not clear criterion or introduced a regression | Preserve original; route to review; do not deliver corrected copy |
| Delivery failure | Corrected file exists but SharePoint write failed | Keep correction and verification success; retry delivery only |
| Authentication or permission | Graph consent expired, destination denied | Pause affected scope; state exact administrator/user action |
| Capacity or worker failure | Lease expired, worker lost | Reclaim safely; expose stall only after recovery threshold |
| Run integrity failure | Counter/source/revision mismatch | Stop presenting optimistic status; reconcile and alert operator |

Retries are idempotent by run, document, phase, and attempt identity. A stale worker cannot publish after its lease expires. The user can retry failed documents or failed delivery without reapplying successful fixes.

## 12. Accessibility requirements

- All state and progress information is available without color.
- The phase rail and counters have programmatic names and current values.
- Use a polite live region for material phase changes, failures, completion, and new required actions.
- Do not announce every counter increment or activity-feed event.
- Keyboard focus never moves because a live update arrived.
- Expand/collapse controls, exception actions, and document cards are fully keyboard operable.
- Preserve the user's expanded sections and scroll position during updates.
- Respect reduced-motion preferences; counter changes use no flashing or rapid animation.
- Status language avoids ambiguous symbols and announces freshness explicitly.
- All controls and text meet WCAG 2.2 AA contrast, focus-visible, target-size, and reflow requirements.

## 13. Permissions, privacy, and audit

- Run snapshots and events are owner/workspace scoped on the server.
- Filenames and source locations are visible only to authorized users.
- Cross-tenant or cross-workspace event subscription is rejected before streaming begins.
- Activity events contain no extracted document content unless the user opens an authorized detail view.
- Every automatic decision records criterion, strategy, policy version, generator where applicable, independent verifier, before/after artifact hashes, and reviewer action.
- Original and corrected-copy destinations are recorded without exposing credentials or signed URLs in event payloads.
- Cancel, retry, approve, reject, and delivery actions are audited with actor and timestamp.

## 14. Success measures

### Trust and comprehension

- At least 90% of usability-test participants correctly identify run state and next action within 10 seconds.
- Fewer than 2% of active-run sessions open Monitor solely to understand basic progress.
- Zero known source-label mismatches.
- Zero snapshots published with violated counter invariants.

### Timeliness and reliability

- P95 durable event-to-visible-update latency ≤ 2 seconds while connected.
- P99 snapshot reconciliation latency ≤ 5 seconds after reconnect.
- At least 99.9% of terminal runs reconcile all document counters.
- Stalled attempts are detected within the configured phase threshold plus one heartbeat interval.
- Streaming failure never interrupts backend remediation.

### Operational outcome

- At least 80% fewer support questions asking whether a remediation run is still working.
- Users can retry delivery-only failures without re-running remediation in 100% of supported cases.
- Every verified corrected copy has complete provenance and rollback evidence.

## 15. Analytics and observability

Instrument:

- time from acceptance to first claim and first visible progress;
- time in each phase by format and remediation lane;
- stream connection, reconnect, gap, and polling-fallback rates;
- snapshot invariant failures and reconciliation duration;
- queued, active, retrying, stalled, failed, and terminal document counts;
- verification failure and regression rates;
- corrected-copy delivery latency and retry rate;
- estimate error by predicted range;
- exception volume and time to human resolution;
- clicks from the panel to Monitor, review, evidence, and corrected copies.

Metrics and logs use run, document, attempt, phase, and correlation IDs. Dashboards must distinguish missing telemetry from a measured zero.

## 16. Delivery plan

### Phase 1 — one truthful snapshot

- Define the server-owned run state machine and counter glossary.
- Return one revisioned snapshot for the Remediate panel.
- Correct source identity and counter-unit labels.
- Replace optimistic "Applying fixes" with authoritative state and reason.
- Add freshness, last-confirmed timestamp, and reconciliation error treatment.
- Add contract tests for all snapshot invariants and screenshot states.

### Phase 2 — live execution

- Add durable phase and document progress events.
- Implement SSE with resumable event IDs and snapshot reconciliation.
- Add live workstream cards, retries, and estimate calibration.
- Add polling fallback and reconnect accessibility behavior.
- Correlate every user-visible event with Monitor.

### Phase 3 — exception-to-action workflow

- Add grouped review, individual review, needs-authoring, and failed-document summaries.
- Support scoped retry, delivery-only retry, cancellation, and safe resume.
- Add corrected-copy and audit-evidence completion actions.
- Validate keyboard and screen-reader workflows with live updates.

### Phase 4 — predictive operations

- Calibrate completion ranges by format, lane, and workload.
- Add proactive stall and provider-throttle explanations.
- Use production evidence to improve capacity recommendations without exposing infrastructure controls to ordinary users.

## 17. Acceptance criteria

1. A SharePoint remediation run always displays its SharePoint tenant/site/library identity and never falls back to OneDrive.
2. A run with zero active attempts and remaining work cannot display "Applying fixes."
3. The primary document counters always sum to total run scope for one snapshot revision.
4. Generated, applied, verified, and delivered counts are separately labelled and cannot be mistaken for one another.
5. When streaming disconnects, the **Live** indicator changes within one heartbeat interval and the last confirmed update age is shown.
6. A reconnect with a missed event fetches a fresh snapshot before rendering later events.
7. Multiple active documents are represented without inventing one serial current file.
8. Verification failure never increments corrected-copy delivery and routes the document to an actionable exception state.
9. A delivery-only failure can be retried without reapplying or re-verifying the fix unless the artifact has become stale.
10. Every terminal run has a reconciled summary, corrected-copy destination where applicable, audit evidence, and an explicit remaining-action count.
11. Screen readers announce material state changes without announcing routine counter increments.
12. Unknown or inconsistent telemetry is shown as unknown or inconsistent, never as zero, complete, or healthy.

## 18. Open decisions

**Answered in §22.** Each of these was genuinely open when this PRD was written; §22 now records a
buildable default for every one, taken from PR #1379's own recommendations. They remain reversible
configuration choices, not settled truths — the list is kept here so the questions stay legible
next to the answers.

- Should users be able to pause new claims, or should pause remain an operator-only action?
- What phase-specific thresholds define delayed versus stalled for each document format?
- How long should resumable remediation events be retained?
- Which corrected-copy destinations support delivery-only retry with stable idempotency?
- Which document classes require the live workstream to suppress filenames or source paths?
- Should completion estimates be enabled for small runs where the calibration sample is weak?
- What review budget should trigger grouped-exception prioritization in the same panel?

## 19. Relationship to existing product decisions

This PRD specializes the Remediate user experience described in `prd-remediation-autonomy-and-review.md` and adopts the durable job, capacity, freshness, and uncertainty contracts in `prd-worker-provisioning-and-job-transparency.md`.

Where those documents describe what ACP may remediate and how workers process jobs, this document defines how one remediation run is presented in real time. It does not expand automatic-remediation eligibility or weaken independent verification gates.

---

## 20. Implementation status

Phase 1 ("one truthful snapshot") is implemented, and so is Phase 2's live-execution spine —
resumable event IDs, snapshot reconciliation, retention, and a stream that stays open through
delivery. What exists, and where:

| Piece | Where |
|---|---|
| Run state machine, counter partition, phase rail, source identity, invariants | `api/remediation_run.py` (pure — no database, no clock, no HTTP) |
| The rows those functions judge | `store.remediation_run_facts` |
| `GET /scans/{sid}/remediation/snapshot`, and the same snapshot on the SSE frame | `api/routes/scans.py` |
| Client normalization + freshness (never run state) | `frontend/src/remediationSnapshot.js` |
| Regions A, B and C | `frontend/src/RemediationOpsPanel.jsx`, mounted in `Remediate.jsx` |
| Contract tests for every invariant and precedence rule | `tests/test_remediation_run_snapshot.py`, `frontend/src/remediationOpsPanel.test.jsx` |
| Resumable event IDs and reconcile-on-unhonourable-cursor (ADR 0051) | `routes/scans.py::_resume_plan` + `stream_remediation_status`; client cursor in `frontend/src/useRemediationRun.js` |
| Structured event record — document, attempt, phase, timestamp, event ID, correlation ID (ADR 0052) | `scan_events.document` / `.correlation_id`, `store.append_scan_event`, `store.list_scan_events(document=…)` |
| Material progress vs worker lease/heartbeat | `Store.MATERIAL_SCAN_EVENT_KINDS` / `LEASE_SCAN_EVENT_KINDS`, `store.latest_material_event_at`, `snapshot.progress` |
| Event retention — §22's 24h **or** 10,000 per run | `store.prune_scan_events`, run hourly by `api/sweeper.py` |
| Filename suppression on every read path | `routes/scans.py::_project_event`, `store.remediation_filename_privacy`, `remediation_run.document_ref` |
| Stream stays open through delivery and reconciliation | `routes/scans.py::_stream_is_finished` |
| Regression fixtures for all of the above | `tests/test_remediation_progress_events.py`, `tests/test_remediation_progress_wire.py`, `tests/test_remediation_stream_resume.py`, `frontend/src/remediationEventDocuments.test.js` |

Deliberately NOT implemented, and why — each of these would be a fabricated answer rather than a
missing feature:

- **`policy_version` and `execution_mode` (§6A)** are carried through as `null`. ACP records no
  version for the remediation lane table and has no per-run execution mode to read, so the panel
  shows nothing for them rather than a version number nothing stamps.
- **Completion throughput and ETA (§10)** now come from the server snapshot. Successfully
  completed document timestamps produce ten 30-second buckets across the latest five minutes;
  failures, review routes and heartbeats never count as throughput. ETA abstains below five recent
  completions and otherwise publishes an approximate 95% rate interval rather than a point guess.
  Per-format and per-lane calibration remains Phase 4 work once production history supports it.
- **Phase-specific stall thresholds (§18)** collapse to one `STALL_AFTER_S`. Five invented
  thresholds are worse than one honest one until there is per-format evidence to set them from.
  §22's *other* clause — stalled requires an expired or unhealthy lease as well as a stale
  progress clock — IS implemented, because it needed no per-format evidence. It was unreachable
  until the progress clock stopped counting heartbeats: while `latest_progress_at` was
  `max(jobs.updated_at)` and `touch_job` rewrote that on every beat, the age could not exceed the
  threshold and `stalled` could not be reached by any path. See ADR 0052.
- **`paused` (§7)** is declared in `RUN_STATES` and never derived: ACP has no pause control for a
  remediation run, and inferring it from an idle queue is the same class of error as inferring
  "Applying fixes" from a queued one.
- **Regions D and E** (live workstream cards, grouped exception routing) are Phases 2-3. The
  snapshot already carries `active_attempts` for D.
- **Resumable event IDs (§8)** ARE implemented (ADR 0051, extended by ADR 0052) — this entry used
  to say they were not, and is corrected here rather than deleted, because a status list that
  understates what shipped sends the next change to rebuild it. The stream still re-pushes the
  whole snapshot on change and the client still drops any frame whose `revision` went backwards;
  event frames are additive beside that, typed `remediation-event`, each carrying its `seq` as the
  SSE `id:`. A client that ignores them behaves exactly as it did before resume existed.

---

## 21. Implementation seams, and what each still owes this PRD

PR #1379 mapped this design onto ACP's existing surfaces. That map is absorbed here, CORRECTED for
what Phase 1 actually shipped — #1379 was written against `main` as it stood before #1376 merged,
so it listed as outstanding several gaps that are now closed. The correction matters more than the
table: a gap map that overstates what is missing sends the next change to rebuild something that
already exists.

| Surface | Where | What it still owes |
|---|---|---|
| Run state, counters, phases, invariants | `api/remediation_run.py` | Nothing for Phase 1. Phase 2 adds phase events as an input rather than deriving the rail from counts alone. |
| Snapshot facts | `store.remediation_run_facts` | Batch-scoped and one-row-per-document already. `latest_progress_at` now counts MATERIAL progress only and `latest_heartbeat_at` reports liveness beside it (ADR 0052) — it used to be `max(jobs.updated_at)`, which a lease heartbeat rewrites, so a wedged worker read as a progressing run. Owes per-attempt delivery state (§11's delivery-failure class is inferred from `drive_write_url`, not recorded as an outcome). |
| Snapshot endpoint | `GET /scans/{sid}/remediation/snapshot` | Carries revision, state, reason, freshness thresholds and the reconciled partition. Owes `links` (currently always `{}`) and `policy_version` / `execution_mode`, which nothing records. |
| Live updates | `GET /scans/{sid}/remediation/stream` | Nothing outstanding here. Resumable event IDs shipped (ADR 0051) and the close condition now reads the snapshot's own `completing` state rather than `in_flight` (ADR 0052) — it stays open through delivery and reconciliation, and deliberately does NOT stay open for `needs_attention`, where the wait is on a human and the client polls. |
| Legacy status | `GET /scans/{sid}/remediation-status` | Unchanged and still feeding the progress bar. Its `fixes_applied` / `verified_documents` mislabelling is corrected in the snapshot, not in this endpoint; the two must not be mixed in one view. |
| Activity | `activity.current(sid)` | One current line cannot represent parallel documents. Region D reads `snapshot.active_attempts` instead, which is already a list. |
| Client | `remediationSnapshot.js`, `RemediationOpsPanel.jsx` | Regions D and E. `RemediationRunProgress` still renders a serial "last fixed ‹file›" beside the panel — two accounts of one run, and the older one implies serial work. |

### On naming

#1379 proposed `GET /scans/{scan_id}/remediation-runs/{run_id}` and a nine-component frontend
decomposition. Both are reasonable designs; neither is adopted, because the shipped endpoint and
component already satisfy the *semantic* boundaries that proposal exists to protect — one
revisioned projection, batch-scoped, never mixing scan-wide totals with latest-batch job totals —
and renaming working, tested code to match a document costs a migration and buys a URL. The
boundaries are the requirement. The names are not.

Decompose `RemediationOpsPanel` when a region earns its own file by growing, not on a schedule.

## 22. Product decisions

These answer §18. Absorbed from PR #1379 §23, which turned a discovery list into buildable
defaults. Each is reversible configuration, and each is recorded here so an implementation can
cite a decision rather than invent a number.

- **Pause.** Ordinary users may request a safe pause of new claims; only operators can force-stop
  active attempts. The panel explains that documents already in flight will drain. Until a pause
  control exists, `paused` stays declared-and-never-derived (§20).
- **Delay and stall thresholds.** Configure by phase and format from observed P95 duration. Warn at
  `max(2 × P95, 60 seconds)` without progress; declare stalled after two further missed heartbeats
  AND an expired or unhealthy attempt lease. Until per-phase P95 evidence exists, the single
  `STALL_AFTER_S` stands — one honest threshold beats five invented ones.
- **Event retention.** Retain resumable events for 24 hours or 10,000 events per run, whichever is
  greater. Terminal audit evidence follows the product retention policy and is not bounded by this.
  *Implemented* — `store.prune_scan_events`, run hourly by the sweeper. "Whichever is greater"
  means a row survives if it is inside EITHER window and is deleted only when outside both; read
  the other way a busy run would lose its last hour on passing ten thousand events. A cursor older
  than what survives gets `reconciliation-required`, which is what ADR 0051 wrote that branch for.
- **Delivery retry.** Enable for SharePoint/OneDrive and Google Drive only, where destination
  identity and idempotency are durable. Blob and download-only outputs require explicit proof
  before activation.
- **Filename privacy.** Show names to users already authorized for the scan; suppress them in
  shared operational views and telemetry exports. *Implemented* — the cross-user Live Operations
  projection never selects the document at all, and a deployment whose filenames are themselves
  sensitive sets `remediation_filename_privacy = suppressed`, after which one projection
  (`routes/scans.py::_project_event`) withholds the name on the stream AND on the polling
  fallback, keeping a non-reversible per-run `document_ref` so §6D's parallel-document histories
  still group and order. An unreadable policy suppresses: a disclosure cannot be un-sent, and a
  withheld label can.
- **Small-run estimates.** Hide estimates until at least five comparable documents complete. Runs
  smaller than five show phase progress only.
- **Review prioritization.** Group first whenever a valid policy cluster exists; surface individual
  review when expected effort exceeds 20 decisions or 15 minutes.

## 23. Test and verification plan

### Contract and state-machine tests

- Every legal state transition, plus rejection of illegal terminal-to-running transitions.
- Counter partition and secondary-outcome invariants.
- Latest-run isolation when a scan has multiple remediation batches.
- Duplicate jobs, retried jobs, and stale worker publication attempts.
- Scan/source identity agreement across SharePoint, OneDrive, Drive, Blob, and upload.
- Terminal reconciliation with review, failure, skip, and delivery-only exceptions.

### Stream and reconnect tests

- Duplicate, delayed, missing, and out-of-order events.
- Reconnect with a valid last event ID.
- Event-retention expiry requiring a snapshot.
- Authentication expiry and permission revocation mid-stream.
- Server restart, deployment overlap, proxy buffering, and polling fallback.
- Browser backgrounding and return without affecting the backend run.

### UI state fixtures

Ship deterministic fixtures for: accepted with no worker; multiple documents active across apply,
verify and deliver; retry scheduled with an exact retry time; verification failure while other work
continues; delivery-only failure; disconnected with last known values; inconsistent telemetry;
stalled lease; completed cleanly; completed with review and failed exceptions; cancelled while
workers drain; and large counts, long filenames, localization expansion, 200% zoom, and 320
CSS-pixel reflow.

### Accessibility verification

Automated semantic, contrast, focus and reflow checks; keyboard-only completion of review and retry
flows; screen-reader testing for initial load, material live changes, reconnect, failure and
completion; reduced-motion validation; and confirmation that updates neither steal focus nor
repeatedly announce unchanged content.

### Production canary

Run the projection in shadow mode against existing status values. Block activation if any document
partition fails reconciliation, source identity disagrees, terminal status differs, a stale update
would move the run backward, or scan-wide totals leak into the latest batch.

## 24. Rollout and rollback

1. **Observe** — generate the projection and invariant telemetry without changing the UI.
2. **Internal** — enable for internal workspaces, retaining the old card behind a support-only switch.
3. **Canary** — enable for selected customer workspaces and document formats.
4. **Default** — make the panel primary after reliability and accessibility gates pass.
5. **Retire compatibility** — remove the old client derivations only once every supported deployment
   produces the versioned projection.

Rollback disables the presentation, not the remediation jobs. The legacy status endpoint remains
available throughout. **A UI rollback must never cancel, duplicate, or restart server work.**

## 25. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| More detailed progress increases database load | Remediation slows under observation | Maintain a projection, batch writes, bound active-attempt detail, load-test realistic concurrency |
| Event stream looks live while data is stale | False trust | Separate transport heartbeat from business-progress freshness |
| Scan-wide legacy facts contaminate run totals | Contradictory counts | Key every projected fact by run/batch; enforce invariants server-side |
| Estimates become promises | User frustration | Ranges, disclosed evidence, hidden weak estimates, measured calibration |
| Activity exposes sensitive filenames | Privacy leak | Same owner/workspace authorization as the run; suppress names in shared views |
| Frequent announcements overwhelm assistive technology | Inaccessible workflow | Announce only material transitions; coalesce routine progress |
| Retried workers publish duplicate effects | Duplicate corrected copies or counters | Lease fencing and phase-specific idempotency keys |
| New panel masks existing worker defects | Polished but incorrect state | Shadow comparison, Monitor correlation, truth-contract release gates |

## 26. Definition of done

The feature is done only when: the versioned run projection is authoritative and batch-scoped; all
snapshot invariants and state transitions are covered by tests; streaming, reconnect, polling
fallback and stale-response handling pass deterministic tests; the panel covers every state fixture
in §23; keyboard, screen-reader, contrast, focus and reflow verification passes; production shadow
telemetry shows no unexplained source, state or count disagreement for the agreed canary period;
Monitor can open directly to the same run and correlation IDs; retry and cancellation cannot
duplicate successful work; user documentation defines every counter and status; and rollback has
been exercised without interrupting an active remediation run.

## 27. Provenance

Sections 21-26 are absorbed from PR #1379 ("Define the real-time remediation operations panel"),
which added a second copy of this PRD under a near-identical filename —
`docs/prd-remediation-real-time-panel.md`. That PR MERGED before this absorption landed, so both
files were briefly on `main`; this change deletes the duplicate, which is why the diff removes 676
lines it never wrote.

Two documents describing one feature is how a spec stops being one, and the near-identical names
(`real-time-panel` vs `realtime-ops-panel`) make it the expensive kind: a reader who finds one has
no signal that the other exists, and an edit to either leaves the pair disagreeing silently. Its
§21 API contract and §22 component plan are deliberately NOT adopted verbatim — see §21's "On
naming" for why the shipped names stand.

---

## 28. Version 2 decision — one live narrative

Version 2 evolves the existing `RemediationOpsPanel`; it does not add another card. Once the
authoritative panel reaches parity, `RemediationRunProgress` is intentionally unmounted. Keep the
older component and its tests in the repository under the retired-feature policy so restoration is
one commit and the unmounted state is explicit in a test.

This amendment is deliberately additive. Sections 1–27 define the truth model, product decisions,
implementation seams and rollout controls. Sections 28 onward specify the next presentation and
contract increment against the repository as it exists after the SharePoint-parity, durable-event,
resumable-stream and active-attempt work.

Within ten seconds, the card must answer:

1. Is remediation progressing?
2. Which immutable source snapshot is being remediated?
3. How many documents are waiting, processing, completed or blocked?
4. What are the workers doing now, in parallel?
5. Are fixes being independently verified?
6. Are corrected copies reaching their intended destination?
7. Has material progress stopped, or is the service waiting for capacity?
8. What changed since the user last viewed the run?
9. Does the user need to act?
10. Can the user safely leave the tab?

## 29. Version 2 layout

### Desktop

```text
┌────────────────────────────────────────────────────────────────────────────┐
│ REMEDIATION IN PROGRESS                         ● Live · updated 2s ago    │
│ SharePoint › UTSW › Policies › Clinical Docs                              │
│ Snapshot locked at 5:13 PM · Batch rem-7f24                View Live Ops → │
├────────────────────────────────────────────────────────────────────────────┤
│ 36 / 100 documents complete                         Estimated 1–2 min      │
│ [ Completed ][ Processing ][ Waiting ][ Review ][ Failed ]                 │
│ 36 complete   10 processing   49 waiting   3 review   2 failed            │
├────────────────────────────────┬───────────────────────────────────────────┤
│ PROCESSING NOW                 │ RUN HEALTH                                │
│ ● Patient Guide.docx           │ Throughput       22.4 documents/min      │
│   Applying heading structure   │ Queue age        18 seconds               │
│   In flight 12s · progress 1s  │ Active capacity  10 compatible slots      │
│ ● Intake Form.pdf              │ Retries          2 scheduled              │
│   Re-checking WCAG 1.3.1       │ Delivery         34 of 36 to SharePoint  │
│ ● Benefits.xlsx · attempt 2    │ Integrity        Reconciled               │
│   Graph throttle · retry 14s   │                                           │
│              Show 7 more →     │                                           │
├────────────────────────────────┴───────────────────────────────────────────┤
│ PHASES                                                                     │
│ ✓ Prepared 100  ● Applying 10  ● Re-checking 6  ● Saving 3  ○ Finalizing │
├────────────────────────────────────────────────────────────────────────────┤
│ LIVE ACTIVITY                                        Pause visual updates  │
│ 17:32:08  ✓ Patient Guide.docx — 4 fixes verified                         │
│ 17:32:06  ↑ Intake Form.pdf — corrected copy saved to SharePoint          │
│ 17:32:03  ↻ Benefits.xlsx — Graph throttled; retry scheduled              │
│ 17:31:58  ! Handbook.docx — manual review requested                       │
│                                                    View full audit trail → │
├────────────────────────────────────────────────────────────────────────────┤
│ NEEDS ATTENTION                                                            │
│ 3 review requests · 2 failed documents · 2 delivery retries               │
│ [Review decisions] [Inspect failures] [Retry delivery]                    │
└────────────────────────────────────────────────────────────────────────────┘
```

The order is fixed: headline and connection freshness; reconciled progress and deltas; active
documents; throughput and ETA; live activity; then exceptions and actions. Ordinary users should
not need Monitor to determine whether their run is progressing.

### Narrow screens

Keep identity, connection state, numeric progress and ETA visible. Render the six document
outcomes as a vertical list, show two active attempts, and collapse `Phases`, `Live activity`,
`Delivery`, and `Needs attention` behind native disclosures. Filenames wrap rather than overflow.
Preserve the user's disclosure state through live updates.

## 30. Locked source and coverage

The card identifies the immutable workflow snapshot, not merely the connected provider.

For one SharePoint location:

```text
SharePoint › {site name} › {library name} › {optional folder}
Snapshot locked {timestamp}
{N} documents inherited from completed Assessment
```

For multiple locations:

```text
SharePoint · 3 sites · 8 libraries
Snapshot locked {timestamp}
View source coverage →
```

The disclosure reuses the locked Discover coverage projection: site and library names, full or
incremental mode, listed/changed/removed counts, and complete, partial, blocked or skipped status.
It must not issue a new Microsoft Graph inventory request merely to populate Remediate.

If the live source has changed, say **Source changed since snapshot** without silently changing
scope. Never imply that documents added after the lock are in the remediation batch. Partial or
skipped discovery coverage remains visible wherever the batch denominator is presented.

## 31. Reconciled progress and active attempts

The denominator is the latest immutable remediation batch:

```text
completed + processing + waiting + review + failed + skipped = total_documents
```

Do not mix historical batches, prior attempts, scan-wide jobs, findings with documents, fixes with
corrected copies, or stored copies with provider-delivered copies. Unknown values render as `—`,
never `0`.

Initially show at most three active attempts with **Show N more**. Each row includes the authorized
display filename, structured phase, attempt number when greater than one, time since claim, time
since material progress, retry time and reason, and verification or delivery state. Criterion
counts are allowed; document contents are not.

The backend distinguishes:

```text
last_worker_signal_at
last_material_progress_at
phase_started_at
```

A worker signal proves liveness, not progress. The card may therefore say that the stream and
worker are live while the document or run is stalled.

## 32. Durable activity and reconciliation

The SSE hook retains a bounded client-side projection of the lifecycle events it already receives;
events are no longer used only to advance the resume cursor.

| Event | User-facing text |
|---|---|
| `remediate.accepted` | Remediation accepted for 100 documents |
| `remediate.fix_applied` | 4 approved fixes applied to Patient Guide.docx |
| `remediate.verified` | 4 fixes independently verified |
| `remediate.verification_failed` | 1 fix did not pass re-scan |
| `remediate.delivered` | Corrected copy saved to SharePoint |
| `remediate.delivery_failed` | Corrected copy retained in ACP; SharePoint delivery failed |
| `remediate.review_requested` | Manual review requested for WCAG 1.1.1 |
| `remediate.document_completed` | Document remediation finished |

Show newest first, at most ten visible events, and link to the complete audit trail. Deduplicate by
durable sequence ID, retain the visible history through reconnect, and never expose extracted
content, prompts, tokens or model responses. Routine activity is not announced to screen readers;
announce only phase changes, failure, completion and newly required action.

The transport and reconciliation hook owns initial snapshot loading, authenticated SSE, cursor
persistence, replay, bounded activity, polling fallback and freshness. Presentational components
do not open streams or derive terminal state.

- Apply only a snapshot revision newer than the current one.
- Ignore an event at or behind the applied durable cursor.
- On an invalid cursor, retention gap or reconciliation-required frame, fetch and apply a fresh
  snapshot before rendering subsequent lifecycle events.
- A reconnect preserves counters, expanded state, scroll position and activity history.
- The stream closes on `snapshot.terminal`, not `in_flight === 0`; `completing`,
  `needs_attention`, delivery and reconciliation states continue updating.
- On stream loss, retain the last confirmed snapshot and show its age. Polling fallback says
  **Updating by polling**.

Continue using the existing durable `scan_events` sequence. Do not add a second remediation event
table.

## 33. Throughput, delivery and exceptions

Throughput is a server-observed run measurement, not browser arithmetic. The snapshot adds only
fields not already available:

```json
{
  "throughput": {
    "documents_per_minute": 22.4,
    "window_seconds": 300,
    "sample_documents": 31,
    "trend": "stable"
  },
  "estimate": {
    "available": true,
    "lower_seconds": 52,
    "upper_seconds": 88,
    "confidence": "medium",
    "basis_documents": 31
  }
}
```

Do not estimate until five comparable documents complete. Show a range, never a resetting
countdown. Account for format, phase, retry schedule, compatible capacity, provider throttling and
delivery latency. If evidence is insufficient, show **Estimating after the first results**.

Correction generation, safe ACP storage and provider delivery are separate outcomes. Display
stored, delivered, pending, failed, retry count, next retry and destination. A delivery failure
states that the corrected copy is safe in ACP and the original is unchanged. Delivery-only retry
must not reapply or reverify a correction unless the stored artifact is stale.

Replace a flat failure total with actionable groups:

- Manual decisions, grouped by criterion and document count.
- Verification failures, with a link to inspect re-scan evidence.
- Provider delivery failures, with a scoped retry action.
- Terminal document failures.

Classifications distinguish authentication, authorization, throttling, source unavailable,
invalid or unsupported document, verification failure, storage failure, provider delivery failure,
worker loss, lease expiry, exhausted retry, and required manual decision.

The ordinary card may show compatible capacity, active count, queue depth, oldest queue age, worker
availability, capacity shortage and provider throttling. Raw replicas, Azure resource IDs,
hostnames, credentials, exception stacks and fabricated utilization remain in Monitor.

## 34. Motion contract

Motion communicates durable change and never substitutes for status text.

- Show the active document pipeline as `Waiting → Applying → Verifying → Saving → Delivered`,
  with current counts at every stage. Documents use a subtle slide/fade only when their durable
  state changes; the pipeline remains still when a refresh repeats the same state.
- Animate a document only when its durable stage changes. A refresh or repeated event does not
  replay motion.
- Positive deltas may briefly highlight increases in completed, applied, verified or delivered
  counts. Never celebrate waiting, failure or retry increases, and never animate an unknown value
  from zero.
- Progress is one reconciled, segmented partition: `Completed | Processing | Waiting | Review |
  Failed`. When `skipped > 0`, add a labelled `Skipped` segment so the visible partition still
  reconciles to the batch total. Labels and/or patterns supplement color; hover and keyboard focus
  reveal exact counts.
- Throughput bars use a five-minute window and update on a 10–15 second visual cadence rather than
  every SSE event.
- Multiple phases may pulse softly while work is active. Queue-flow dashes move only while
  documents advance and stop while waiting, disconnected or stalled.
- Newly visible activity enters at the top. Older rows age out without fading below readable
  contrast, and relative-time refreshes do not replay entrance motion.
- Show detailed progress trails for at most the three visible active documents.
- Milestone notices are subtle and dismissible and appear only for meaningful thresholds, never
  for every document.
- An optional compact strip may visualize event density over the last 60 seconds. Label it
  **Activity**, not progress or completion, keep it subordinate to the headline, and allow it to be
  hidden without losing any operational information.
- Connection text always says `Live`, `Reconnecting · last update … ago`,
  `Updating by polling`, or `Stalled · no material progress for …`; animation is supplementary.
- Respect `prefers-reduced-motion`; never flash faster than three times per second; never move
  focus, reading order or scroll position because data arrived.
- When the tab is hidden, continue ingesting SSE but pause visual motion. On return, render the
  latest reconciled state once without replaying accumulated transitions.
- **Pause visual updates** freezes animation, not backend work, event ingestion or reconciliation.

## 35. Version 2 delivery and acceptance

### Phase A — use what already exists

- Merge and build on PR #1413.
- Render the existing bounded `active_attempts` list and lifecycle events.
- Show `retry_at`, integrity state and locked source identity.
- Preserve the cursor and visible history through reconnect.
- Stop mounting `RemediationRunProgress` after parity; add an explicit orphan assertion.

### Phase B — SharePoint parity

- Add locked site/library coverage and full/incremental provenance to the snapshot.
- Show delivery destination and delivery-only retry state.
- Categorize SharePoint throttling and permission failures.
- Issue no new Graph inventory request for display.

### Phase C — progress quality

- Separate worker signal from material progress.
- Add structured phase keys and timestamps.
- Add server-observed throughput and evidence-based ETA ranges.
- Continue streaming through completion and delivery reconciliation.

### Phase D — actionable exceptions

- Group review, verification, terminal and delivery exceptions.
- Add scoped retry actions and audit-evidence links.
- Prove that delivery-only retry cannot reapply a successful fix.

Version 2 is accepted when:

1. One card authoritatively describes the latest remediation batch and its six outcomes reconcile.
2. A SharePoint run shows its locked site/library scope and never says OneDrive.
3. Existing durable lifecycle events appear in the activity feed and survive reconnect without
   duplication.
4. Reconciliation occurs before later events render after invalid resume state.
5. Multiple active attempts are represented as parallel work.
6. Worker signal and material progress use different timestamps.
7. **Live** clears within one heartbeat window after stream loss and polling is explicitly labelled.
8. The stream remains active while delivery or reconciliation is incomplete.
9. Stored corrected copies remain distinct from provider-delivered copies.
10. Verification failure cannot increment delivery, and delivery-only retry cannot reapply or
    reverify an unchanged artifact.
11. Unknown capacity and telemetry render as unavailable, never zero.
12. Navigation, refresh, sign-out and sign-in do not imply that backend work stopped.
13. Routine counters and feed rows do not overwhelm screen-reader users.
14. The legacy progress card remains in the tree but is intentionally unmounted after parity.
15. P95 durable-event-to-visible latency is at most two seconds, at least 99.9% of terminal runs
    reconcile, and source-label mismatches and negative/over-total progress values remain zero.
