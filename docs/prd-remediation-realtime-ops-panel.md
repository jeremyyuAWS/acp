# PRD — Remediation Real-Time Operations Panel

**Product:** ACP
**Scope:** Remediate workspace, live job status, verification, review handoff, and corrected-copy delivery
**Status:** Proposed
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

Phase 1 ("one truthful snapshot") is implemented. What exists, and where:

| Piece | Where |
|---|---|
| Run state machine, counter partition, phase rail, source identity, invariants | `api/remediation_run.py` (pure — no database, no clock, no HTTP) |
| The rows those functions judge | `store.remediation_run_facts` |
| `GET /scans/{sid}/remediation/snapshot`, and the same snapshot on the SSE frame | `api/routes/scans.py` |
| Client normalization + freshness (never run state) | `frontend/src/remediationSnapshot.js` |
| Regions A, B and C | `frontend/src/RemediationOpsPanel.jsx`, mounted in `Remediate.jsx` |
| Contract tests for every invariant and precedence rule | `tests/test_remediation_run_snapshot.py`, `frontend/src/remediationOpsPanel.test.jsx` |

Deliberately NOT implemented, and why — each of these would be a fabricated answer rather than a
missing feature:

- **`policy_version` and `execution_mode` (§6A)** are carried through as `null`. ACP records no
  version for the remediation lane table and has no per-run execution mode to read, so the panel
  shows nothing for them rather than a version number nothing stamps.
- **Completion estimates and throughput (§10)** are absent. The existing pickup estimate
  (`GET /scans/{id}/queue-estimate`) abstains without recent history, and a per-phase, per-lane
  calibrated range needs evidence that has not been collected. Phase 4.
- **Phase-specific stall thresholds (§18)** collapse to one `STALL_AFTER_S`. Five invented
  thresholds are worse than one honest one until there is per-format evidence to set them from.
- **`paused` (§7)** is declared in `RUN_STATES` and never derived: ACP has no pause control for a
  remediation run, and inferring it from an idle queue is the same class of error as inferring
  "Applying fixes" from a queued one.
- **Regions D and E** (live workstream cards, grouped exception routing) are Phases 2-3. The
  snapshot already carries `active_attempts` for D.
- **Resumable event IDs (§8)** are not implemented; the stream re-pushes a whole snapshot on
  change and the client drops any frame whose `revision` went backwards.
