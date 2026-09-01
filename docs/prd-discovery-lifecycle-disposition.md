# PRD — Discovery Lifecycle Management and Archival Disposition

**Product:** mova.io Accessibility Platform  
**Area:** Discover → Lifecycle rules → Disposition review  
**Status:** Proposed, implementation-ready  
**Primary outcome:** Make archival recommendations trustworthy, explainable, reviewable, and auditable before accessibility assessment begins.

## 1. Problem

Discovery currently reports how many lifecycle rules ran and how many files matched, but it does not
give a compliance officer enough context to answer the next questions:

- Which rules ran, and against which files?
- Why did a file match or not match?
- Which rule won when several rules matched?
- Are recommendations safe, and what will happen after approval?
- Which files are already archived, newly recommended for archive, exempt, or reactivated?
- Can the user prove later who approved a disposition and what source evidence was used?

The result is an engine with useful governance behavior but a thin user surface. “No files matched” can
read as “the rules did not run,” and a candidate count can read as an action already taken. Users must
leave Discovery and reconstruct the decision from inventory rows or a separate settings surface.

## 2. Product outcome

Discovery becomes the lifecycle control plane for the estate. Every discovered file receives one
reconciling lifecycle disposition, every recommendation carries plain-language evidence, and every
source-changing action remains approval-gated.

The user should be able to understand the run at three levels:

1. **Estate:** how the complete inventory divides into active, already archived, archive candidates,
   delete candidates, exempt, unreadable, and unsupported files.
2. **Rule:** what each enabled rule evaluated, matched, skipped, or could not evaluate.
3. **File:** the exact facts, rule version, precedence decision, and proposed action for one document.

## 3. Principles

- **Inventory everything; act on a subset.** Unsupported files stay visible and reconciled to the total.
- **Recommendation is not execution.** Discovery may tag a candidate but does not move or trash it.
- **Explain every decision.** A lifecycle state without a reason, evidence, and rule version is incomplete.
- **Fail closed.** Missing metadata or conflicting rules never produces a destructive recommendation.
- **One engine, multiple views.** Discovery, the file drawer, approval queue, and audit report read the
  same server-owned lifecycle decision; the client does not re-evaluate rules.
- **Human approval is meaningful.** Review is grouped intelligently, but archive and delete approvals
  state their exact scope and effect.
- **Recoverability is visible.** “Delete” means move to source trash, with recovery details and expiry.
- **Counts reconcile.** Every rollup must sum to the discovered estate or identify the unresolved delta.

## 4. Users and jobs

### Compliance officer

- Understand how retention policy changes accessibility scope.
- Review archive recommendations without inspecting thousands of files individually.
- Explain why a document was excluded from assessment.
- Export evidence for governance and audit.

### Records manager

- Define and test retention rules against current inventory.
- Resolve conflicts, exceptions, legal holds, and owner-specific policy.
- Approve an archival batch with a clear blast radius.

### Content owner

- See why their file was flagged.
- Keep, archive, or request an exception with a required rationale.
- Reactivate an archived file when it is modified, moved, or republished.

## 5. Lifecycle model

Every inventory row has exactly one effective lifecycle disposition:

| Disposition | Meaning | Assessment behavior |
|---|---|---|
| Active | In normal accessibility scope | Eligible by format |
| Already archived | Recognized source convention or prior approved disposition | Excluded |
| Archive candidate | Rule recommends recoverable archival | Excluded by default; reviewable override |
| Delete candidate | Rule recommends source trash | Excluded by default; reviewable override |
| Exempt / legal hold | Policy must not disposition the file | Included or excluded by explicit policy |
| Reactivated | Previously archived content changed or moved back into use | Returns to assessment scope |
| Unevaluable | Required metadata was missing or invalid | No destructive recommendation |
| Failed | Approved source action failed | Remains visible with retry/escalation |

The run-level estate total must equal the sum of these mutually exclusive effective dispositions.
Unsupported/unreadable are orthogonal capability facts and may be shown as a second breakdown, but must
not create duplicate estate counts.

## 6. Rule model

### 6.1 Rule anatomy

Each rule stores:

- stable `policy_id` and immutable `version`;
- human name, description, owner, enabled state, priority, and effective dates;
- source and folder scope;
- conditions joined by explicit `ALL` / `ANY` groups;
- proposed action: keep, tag, archive, move, rename, or trash;
- target folder or naming convention where applicable;
- confidence class: deterministic or heuristic;
- approval mode: per-file, grouped batch, or recommendation only;
- exception behavior and legal-hold behavior;
- creation, update, and last-evaluated timestamps.

### 6.2 Initial condition catalog

Ship conditions whose evidence is already available first:

- filename ends with a configurable archive suffix such as `_ARCHIVED`;
- an ancestor folder matches an archive convention;
- extension/file type;
- created or last-modified date before/after a cutoff;
- age in days;
- size threshold;
- owner, department, source, folder, or path;
- readable SharePoint metadata/retention tag;
- locked, unreadable, or legal-hold state;
- exact duplicate content hash when available.

Label conditions requiring additional Graph permissions—usage analytics, permissions expansion, version
history—as **Unavailable until connected**, never as false.

### 6.3 Precedence and conflict resolution

Use deterministic server-side precedence:

1. Legal hold / explicit exemption wins over every destructive action.
2. Explicit human override wins until its expiry or revocation.
3. Reactivation wins over an earlier archived state when its trigger is newer.
4. Higher-priority enabled rule wins.
5. Equal-priority conflicting destructive actions become `Conflict — review required`; neither executes.
6. Tag-only actions may coexist with one effective disposition action.

The effective decision stores all matching rules, the winning rule, overridden rules, and the precedence
reason. Reordering rules creates a new version and triggers a preview before activation.

### 6.4 Evaluation states

Every rule/file evaluation produces one of:

- matched;
- did not match;
- skipped by scope;
- exempted;
- unevaluable because required evidence was missing;
- conflicted with another rule.

Zero-match summaries must say: “Evaluated N files; 0 matched; M skipped by scope; U could not be
evaluated.” They must never show only “No files matched.”

## 7. Discovery experience

### 7.1 Component: Lifecycle Estate Summary

Place below Discovery completion and above the inventory table.

Show:

- a horizontal reconciled disposition bar;
- counts for Active, Already archived, Archive candidate, Delete candidate, Exempt, Reactivated, and
  Unevaluable;
- the assessment-scope impact: “684 disposition candidates excluded from Assess by default”;
- safety text: “Recommendations only — no source files were moved or deleted”;
- **Review disposition queue** and **View rule results** actions.

Selecting a segment filters the inventory without navigating away.

### 7.2 Component: Rule Results Ledger

An expandable table with one row per enabled rule:

| Rule | Priority | Evaluated | Matched | Skipped | Unevaluable | Proposed action | Status |
|---|---:|---:|---:|---:|---:|---|---|

Each row expands to show:

- plain-language condition expression;
- scope and exclusions;
- rule version and evaluation timestamp;
- three representative matches;
- most common non-match reason;
- missing-evidence breakdown;
- conflicts and the rule that won;
- **Preview matches**, **Edit rule**, **Disable**, and **Export results** actions.

### 7.3 Component: Lifecycle Activity Feed

During Discovery, show durable live updates:

- rules loaded;
- files evaluated;
- current rule or evaluation phase;
- matched, skipped, conflicted, and unevaluable counters;
- checkpoint timestamp and processing rate;
- worker state, retry state, and a Monitor link.

Fast runs retain a short completed timeline for at least 10 seconds so users can perceive the work. Honor
`prefers-reduced-motion`; animation supplements state text and never replaces it.

### 7.4 Component: Disposition Review Queue

Use an Outlook-style two-panel workspace.

**Left panel — queue**

- grouped by rule/action, with group size and risk;
- filters for status, rule, owner, department, source, age, and file type;
- default sort: conflicts, legal/hold exceptions, delete candidates, archive candidates;
- bulk selection only within one rule version and one proposed action;
- clear reviewed/remaining progress.

**Right panel — decision**

- file identity, owner, path, source link, dates, size, and current lifecycle state;
- “Why this was recommended” evidence chips with actual values and thresholds;
- matched rules, winning rule, and precedence explanation;
- source effect preview: rename/move target or trash behavior;
- impact on Assess and remediation scope;
- timeline of prior scans, recommendations, overrides, approvals, and source actions;
- actions: Approve archive, Keep active, Exempt, Edit target, Reject rule result;
- mandatory reason for Keep/Exempt/Reject and for every delete approval.

### 7.5 Component: Rule Builder and Test Bench

Embed a compact entry point in Discovery and retain advanced management in Settings.

The builder provides:

- natural-language sentence preview: “When ALL of … recommend Archive”;
- condition validation and unavailable-signal warnings;
- live estimated match count against the latest complete inventory;
- representative matches and non-matches;
- conflict preview against enabled rules;
- scope-impact preview, including how many Assess candidates would be excluded;
- save as draft, test, activate, clone, and version history.

A rule cannot activate until preview completes successfully. Destructive rules default to approval
required and cannot disable approval without an administrator capability and an explicit confirmation.

### 7.6 Component: Lifecycle Inventory Columns

Add optional columns and filters to the existing inventory table:

- effective disposition;
- proposed action;
- winning rule;
- lifecycle reason;
- evaluation status;
- approval status;
- last evaluated;
- archive/retention date;
- exception or legal-hold state.

CSV export includes these fields plus policy id/version and evidence values.

## 8. Human approval and execution

Discovery only creates recommendations. Execution uses the existing disposition approval path.

- Archive/move/rename: group approval permitted when every selected row has the same policy version,
  action, destination, and confidence class.
- Trash: always approval-gated; present the number of files and recovery behavior twice—selection and
  final confirmation.
- Legal hold/exempt: never included in bulk destructive approval.
- Source action executes asynchronously with per-file success/failure and retry.
- A partial batch is never summarized as successful; counts reconcile applied, failed, canceled, and
  pending.
- Source mutations are idempotent using `(document_id, policy_version, action)`.
- A user may undo a recoverable move/rename/archive action where the connector supports it. Trash recovery
  links to the source recovery flow and states its retention window when known.

## 9. Reactivation

An archived document returns to Active/Reactivated review when:

- `source_modified` is newer than the approved archive timestamp;
- it moves out of an archived folder;
- its archive metadata/tag is removed;
- a permission/sharing trigger fires when that optional signal is connected;
- a human explicitly reactivates it.

Reactivation does not silently erase history. It appends an audit event, records the trigger evidence,
and queues the document for assessment according to format eligibility.

## 10. Data and API requirements

### 10.1 Persisted evaluation snapshot

Add a durable, immutable evaluation record:

```text
lifecycle_evaluation
  evaluation_id
  scan_id
  document_id
  policy_id
  policy_version
  result                 matched | not_matched | skipped | exempt | unevaluable | conflict
  evidence_json
  proposed_action
  priority
  evaluated_at
```

Persist the effective decision separately or on the inventory/document lifecycle record:

```text
effective_disposition
  document_id
  scan_id
  winning_evaluation_id
  lifecycle_status
  precedence_reason
  approval_status
  override_reason
  updated_at
```

Evidence stores only the facts used by the rule, not file content. Existing disposition audit remains the
append-only record of approval and execution.

### 10.2 Endpoints

- `GET /scans/{scan_id}/lifecycle/summary`
- `GET /scans/{scan_id}/lifecycle/rules`
- `GET /scans/{scan_id}/lifecycle/files` with filters and pagination
- `GET /scans/{scan_id}/lifecycle/files/{document_id}`
- `POST /disposition/policies/{policy_id}/preview`
- `POST /disposition/approvals` with explicit row ids and policy version
- `GET /disposition/batches/{batch_id}`
- `POST /documents/{document_id}/lifecycle/override`
- `GET /documents/{document_id}/lifecycle/history`

All endpoints are tenant/owner scoped. Summary responses contain a reconciliation total and data version so
the UI can reject mixed snapshots.

### 10.3 Live events

Extend the durable scan progress payload with:

- `rules_total`, `rules_completed`, `current_rule_id`;
- `files_evaluated`, `files_matched`, `files_skipped`;
- `files_unevaluable`, `conflicts`;
- `rate_per_second`, `checkpoint_at`.

Persist run-level milestones in the existing scan event log. Per-file evidence belongs in
`lifecycle_evaluation`, not the high-frequency scan event stream.

## 11. Safety and governance requirements

- Discovery never mutates source files.
- Every destructive recommendation identifies its evidence and policy version.
- Missing evidence never counts as a non-match for a destructive rule; it is Unevaluable.
- Rule changes do not retroactively rewrite past evaluations.
- Policy activation, disablement, priority changes, overrides, approvals, execution, retries, and failures
  are audited with actor and timestamp.
- Legal hold is fail-closed and checked again immediately before execution.
- Connector permissions are revalidated immediately before source mutation.
- Bulk approval displays and submits explicit document ids; it never means “all current matches” at execute
  time.
- A changed document invalidates its pending approval and requires re-evaluation.

## 12. Accessibility requirements

- All disposition colors have text/icon labels and meet WCAG 2.1 AA contrast.
- Queue and detail panels are independently keyboard navigable with a visible focus indicator.
- Status updates use a polite live region and do not announce every file.
- Charts have equivalent tables and screen-reader summaries.
- Rule expressions are readable as text, not only visual chips.
- Motion honors `prefers-reduced-motion`.

## 13. Success measures

- 100% of discovered files reconcile to an effective lifecycle disposition.
- 100% of candidates expose a policy id/version and plain-language evidence.
- Zero source changes initiated from Discovery without approval.
- At least 90% of reviewers can explain why a sampled file was flagged without opening settings.
- Median time to approve a homogeneous archive batch under 2 minutes.
- Less than 1% of evaluations are Unevaluable for signals marked available.
- Zero stale approvals executed after document content or metadata changes.
- Completion and live counters differ by zero at terminal state.

## 14. Delivery plan

### Phase 1 — Transparent lifecycle results

- Lifecycle Estate Summary.
- Rule Results Ledger.
- Persist evaluated/matched/skipped/unevaluable/conflict counts.
- Exact format and scope explanations.
- Inventory lifecycle columns and CSV export.

### Phase 2 — Explainable per-file review

- Durable `lifecycle_evaluation` snapshots.
- Outlook-style Disposition Review Queue.
- Match evidence, precedence, conflicts, overrides, and history.
- Grouped archival approval with explicit row scope.

### Phase 3 — Rule test bench and execution hardening

- Preview-before-activate rule builder.
- Conflict and assessment-impact simulation.
- Idempotent batch execution, legal-hold recheck, retries, and reconciliation.
- Recovery/undo presentation.

### Phase 4 — Archive recognition and reactivation

- Configurable suffix/folder/metadata recognition.
- Modified-after-archive and moved-out-of-archive detection.
- Reactivation queue and continuous-monitoring integration.

### Phase 5 — Advanced ROT signals

- Exact duplicate groups.
- Version/supersession evidence.
- Optional usage, permission, and sharing signals after tenant permission approval.
- Master inventory reconciliation import/export.

## 15. Acceptance criteria for the first implementation increment

1. A completed Discovery run shows a reconciled lifecycle estate summary.
2. Each enabled rule reports evaluated, matched, skipped, unevaluable, and conflict counts.
3. Selecting a count filters the inventory to the exact contributing files.
4. A user can open a file and see the matched conditions with actual values and thresholds.
5. Conflicting rules show all contenders, the winner or review-required state, and the precedence reason.
6. Missing required metadata produces Unevaluable and cannot create archive/delete candidates.
7. Recommendations clearly state that no source file has changed.
8. Refreshing the page reproduces the same run snapshot from durable storage.
9. CSV export reconciles to the on-screen totals and includes policy id/version and evidence.
10. Existing lifecycle exclusions continue to feed Assess without changing their default behavior.
11. Keyboard and screen-reader tests cover the summary, ledger, filters, and two-panel review.
12. Backend fixtures cover precedence, legal hold, overrides, missing evidence, stale approval, idempotency,
    and terminal batch reconciliation.

## 16. Non-goals

- Permanent deletion from the source.
- AI-generated disposition decisions without deterministic source evidence.
- Hiding unsupported or unreadable files from the estate inventory.
- Replacing the existing disposition engine with client-side rule evaluation.
- Adding Graph permissions for analytics, versions, or sharing without tenant approval.
- Automatically acting on historical matches when a new rule is enabled.

## 17. Implementation map to the current repository

- Extend `api/disposition.py` for evaluation result detail and precedence evidence.
- Extend `api/handlers.py::_evaluate_discover_lifecycle_rules` to persist immutable evaluations.
- Extend `api/routes/disposition.py` and `api/routes/scans.py` with summary, ledger, file-detail, preview,
  and batch endpoints.
- Extend the store schema/migrations for evaluation snapshots and effective decisions.
- Build `LifecycleEstateSummary.jsx`, `LifecycleRuleLedger.jsx`, `DispositionReviewWorkspace.jsx`, and
  `LifecycleEvidencePanel.jsx`.
- Wire them through `Discover.jsx`, `DiscoverCompleteSummary.jsx`, the existing inventory, and File Drawer.
- Reuse `DiscoverRunProgress.jsx` for live lifecycle counters and `DispositionRules.jsx` for rule editing.
- Reuse the existing disposition audit/approval path; do not create a parallel execution system.

## 18. Product decisions required before Phase 3

- Whether grouped archive approval is available to Compliance Officer or Records Manager only.
- Default archive destination convention by source.
- Whether a Keep override expires automatically and, if so, after how long.
- Whether already-archived recognition is enabled by default or introduced as a draft rule.
- Trash recovery language and retention-window source for Google Drive and SharePoint.
