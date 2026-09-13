# PRD: Clear automatic remediation and publication

Status: proposed design for user review before UI implementation  
Date: September 13, 2026  
Baseline: deployed 2026.9.13.8, origin/main 75ec711a

## 1. Goal

After approving a remediation plan, users should immediately understand what ACP is doing automatically, which fixes were independently verified, which decisions require their help, and which saved copies reached SharePoint or Google Drive.

Q3 automatic publication must require no additional Publish click for covered copies. Auto-apply must drain eligible suggestions through the real write-and-check process. Remaining items must have an explanation rather than an unexplained active Apply button.

This PRD covers the seven remaining items from the conversation: Deva end-to-end verification, his cropped diagram exception, automatic review draining, understandable unresolved findings, tile definitions and layout, automatic-publication messaging/actions, and consistent progress totals.

## 2. Proposed screen order — Remediate

```text
REMEDIATE

1. AUTOMATION STATUS
   Auto-apply AI fixes: On
   Automatic publishing: On
   ACP is applying eligible suggestions and delivering saved copies after checks.
   Action needed: 11 review items require your judgment. [View items]

2. FILE PROCESSING — compact progress bar
   11 of 19 files with findings have finished an automatic processing attempt.
   8 files have not finished an attempt.
   A finished attempt may still leave unresolved findings.

3. FINDING RESULTS — this run, 801 assessed findings
   [Awaiting outcome ⓘ] → [Applying & checking ⓘ] → [Verified fixes ⓘ]
   Separate outcomes: [Unresolved findings ⓘ] [Excluded ⓘ]
   Select a tile to see the matching findings/documents.

4. NEXT STEPS — explicit ownership
   ACP will handle: scheduled AI retries or automatic checks, when evidenced.
   You need to handle: individual review, manual repair, connection/source blockers.
   Verification problems: fixes that could not be verified, with supported next steps.

5. WORKSPACE TABS
   [Live activity] [Needs your review (N)] [AI activity]
   Scrollable document list with search and filters.

6. DELIVERY SUMMARY — compact; no duplicate publishing form
   Automatic publishing is on. No Publish click is needed.
   8 of 19 approved copies delivered. [Open Release]

7. RUN DETAILS — collapsed evidence and history
```

The illustrative counts show layout, not a claim about a live session. Render real values from one current-run snapshot.

Replace the repeated Document progress tile row in Remediate with the compact file-processing summary and document-list filters. Do not combine verified finding counts with publication eligibility: a document may be publishable with recorded remaining work under the approved plan.

## 3. Proposed screen order — Release

```text
RELEASE

1. AUTOMATIC PUBLICATION STATUS
   Automatic publishing is on. No Publish click is needed.
   Destination: SharePoint / saved release folder
   ACP checks existing copies and resumes delivery automatically when possible.

2. DELIVERY PROGRESS — entire saved automatic plan
   8 of 19 approved copies delivered
   [Waiting for delivery ⓘ] → [Publishing ⓘ] → [Published ⓘ]
   Separate outcomes: [Delivery issues ⓘ] [Skipped ⓘ]

3. DOCUMENTS
   [Search filenames…] [Delivery status] [File format] [Verification status]
   Showing X of Y documents; fixed-height scroll area and sticky table header.
   Document | Repair verification | Delivery status | Remaining work | Action

4. REPORTS / DESTINATION
   Open published folder; download scan summary and per-file checklists.

5. DELIVERY DETAILS — collapsed
   Latest incremental request, receipts, retries, and audit history.
```

Remove the redundant Release Document progress row. Keep the existing component and tests in the tree; retire only its mount and add an explicit retirement/wiring assertion.

Use one primary delivery summary across both tabs and the workflow header. A latest one-file request belongs in collapsed details, not the main progress header.

When automatic publication is off, Release retains a clearly labeled manual publishing flow: select eligible copies, confirm destination, publish. Copies outside the saved automatic plan are shown separately and require fresh authorization; never silently expand Q3 consent.

## 4. Tile labels and definitions

Use a short visible definition and an accessible info icon for details. Tooltips alone are insufficient for essential meaning.

| Label | Visible definition | Expanded explanation |
|---|---|---|
| Files with findings | Fixed repair scope | Selected documents with findings in this remediation run; not all selected files and not a count of repaired files. |
| Processing attempts finished | Automatic attempt finished | An attempt ended, including unsuccessful or skipped work. Remaining findings may still need attention. |
| Attempts not finished | No finished attempt recorded | May include waiting and in-progress files. Do not call all of them queued. |
| Awaiting outcome | No saved result yet | Findings without a recorded outcome, including queued work or results still syncing. Show a queued-versus-syncing split only with authoritative evidence. |
| Applying & checking | Changes awaiting verification | Approved work awaiting application or independent checking. Show the precise step on each item. |
| Verified fixes | Saved changes passed checks | Fixes independently verified against corrected bytes and durably recorded. Approval alone never contributes. |
| Unresolved findings | Not yet verified as fixed | Includes review-required, unchanged/no supported fix, failed work, and unexpected/unclassified outcomes. Explain the next owner per item. |
| Excluded | Outside the current result set | Deliberately excluded or superseded records; not successful fixes. |
| Waiting for delivery | Delivery has not started | Authorized copies genuinely waiting for publication; blocked or unclassified copies are identified separately. |
| Publishing | Delivery underway | Upload or existing-copy confirmation in progress. |
| Published | Confirmed at destination | Corrected copy has a confirmed SharePoint/Google Drive receipt. Publication does not certify accessibility. |
| Delivery issues | Delivery needs recovery | Show automatic recovery state or the concrete action required. Never show Complete while a covered copy remains undelivered. |
| Skipped | Not delivered | Show why a copy was skipped. A skipped copy does not count as Published. |

Unresolved counts can rise as ACP finishes attempts and records remaining issues. That increase is not evidence that new issues were introduced. Use neutral/amber activity for increases, retain green flashes for verified gains and successful queue decreases, and respect reduced-motion preferences.

Keep before/change rows only for changing measures with a valid same-run baseline. Hide them for fixed scope. Missing evidence is unavailable, not zero.

## 5. Auto-apply and review queue behavior

Persistent copy:

> Auto-apply is on. ACP automatically applies eligible AI suggestions. Items needing your judgment remain below.

The switch grants consent; the server determines actual eligibility. Current eligibility includes exact proposal identity, authorized run/source, supported writer, criteria scope, saved artifact, and required semantic review. Do not weaken these checks.

| Server-confirmed item state | Primary action |
|---|---|
| Checking automatic eligibility | Disabled: Checking… |
| Automatically queued | Disabled: Queued automatically |
| Applying | Disabled: Applying… |
| Verifying | Disabled: Verifying… |
| Individual review required | Enabled: Review and apply; specific reason visible |
| Manual repair required | View required repair |
| Verified fixed | View verified change |
| Could not verify | View issue; retry only when supported and authorized |
| Source/connection blocked | Concrete recovery action or automatic recovery status |

An eligibility check must resolve to a reason or unavailable state; no indefinitely disabled Checking action. If status cannot be fetched, explain that the automatic state is unavailable and reconcile before allowing a duplicate application.

Add a durable server-owned automation disposition and reason per review item. The current temporary marker disappears when the approval coordinator finishes or defers work, which leaves an unexplained enabled Apply button. Consent alone must never fabricate a queued/applied state.

Automatically admitted items move out of Needs your review into Processing. Record verified results separately from attempted outcomes. Replace ambiguous Completed with Results and show verified, unresolved, and excluded totals within that view. Add visible copy: Results include verified fixes and remaining work. A green completion badge is reserved for verified success, not every recorded outcome.

Remaining review groups: Needs your review, Manual repair, Could not verify, and Blocked. Show AI retry scheduled separately only when a durable retry exists. Each item shows who handles it, why, and the next action. Review-item counts must say items; finding counts must say findings. Never substitute grouped review counts for distinct findings.

Turning auto-apply off stops new automatic admissions. Already authorized work stays visible with its real state. Retain stale-response fences and duplicate-application protection.

## 6. Automatic publication and recovery

After Q3 approval: apply eligible fixes → save corrected bytes → assess those bytes and release checks → deliver covered eligible copies → confirm destination receipts.

This continues in the background without requiring the Release tab to stay open. Release is the monitoring and results screen for automatic plans.

Copies covered by the saved automatic plan have no manual Publish action, including while queued, blocked, or reconnecting. Pending/unavailable plan status says Checking automatic publication and prevents a duplicate publication request. Manual actions remain available only for explicitly separate, authorized copies.

Use the existing amber top banner for automatic connection/delivery recovery. Silent renewal and existing-copy checks run first. Show Sign in only when an interactive connection is actually required. Preserve destination, consent, and saved artifacts across recovery. An uncertain submission must reconcile its existing request before retrying; never blindly upload again.

Published copies may contain documented remaining work if the approved plan permits it. Approved but unwritten changes remain blocked. Verification uncertainty and provider spending uncertainty are not bypassed to force progress.

## 7. Consistent scope and counters

File-processing scope is the selected population with findings, not necessarily every selected document. Show the overall selected population separately when different. Finding scope is assessed findings in the current remediation run. Primary publication scope: distinct copies in the immutable saved authorization, across all its incremental requests. Publish the scope ID and snapshot revision with counters and file membership.

The workflow header, Remediate delivery summary, Release tiles, and document list consume the same saved-plan snapshot. Requests and retries must not reset the denominator or double-count already delivered copies.

Show partitions only when authoritative membership balances. If a complete partition is unavailable, show confirmed published count plus remaining/unclassified state; do not synthesize queued or failed counts by subtracting unrelated totals.

Complete requires the saved plan to finish and every covered copy to have confirmed destination delivery. Skipped, failed, unavailable, or outstanding copies require an accurate incomplete/action-needed state, even if a child request ended. Remediation attempt completion is separate from release completion.

## 8. Accessibility and document navigation

Reuse InfoTip behavior: keyboard focus, hover, tap, Escape, and accessible names. Info controls are siblings of tile buttons, never nested buttons. Keep essential definitions visible and preserve tile filtering.

Both tabs expose searchable, filterable document lists with vertical scrolling, horizontal overflow on narrow screens, sticky headers, clear result counts, empty states, and reset filters. Retain destination links and per-file repair/delivery evidence. Do not mount duplicated tables solely to make navigation work.

Earlier workflow tabs remain current-scan results-only. Starting a new scan intentionally resets the workflow scope; browsing history does not restart remediation.

## 9. Deva verification workstream

Keep Deva’s report open. No data deletion is required. Use the original source and a new authorized run when replaying the full process.

Verify his exact file, not just synthetic fixtures: usable visible-crop alt text, sensory rewrite actually written, independent corrected-file reassessment, and confirmed destination delivery. Retain per-step evidence.

His 19.861% top-cropped Word diagram can now be read as the visible crop. Automatic removal is still unsupported without proof that useful diagram content survives. Surface the exception and safe authoring/review next step. Adding a transcript beside the raster does not by itself clear the image-of-text criterion.

No new provider-spending reservation should repeat an attempt with unresolved billed usage. Missing provider evidence or authorization is a reported blocker, not permission to guess.

## 10. Acceptance checks

1. Q3-on flow delivers eligible copies without a second Publish click or an open Release tab.
2. Auto-apply-on eligible items drain without manual Apply; every remaining item has a specific owner/reason.
3. No duplicate writer or upload is created by tab changes, refreshes, repeated clicks, or uncertain responses.
4. File/finding/review/delivery scopes remain explicit and consistent; cumulative delivery does not become 1 of 1 after an incremental request.
5. Missing or reconciling results are never shown as zero, verified, or Complete.
6. Publication with remaining work is clearly explained and does not bypass approved-unwritten checks.
7. Provider/source connection recovery remains automatic when possible and actionable when sign-in is necessary.
8. Tooltips and document filters work by keyboard, touch, and reduced-motion settings.
9. Actual DOM fixtures cover each automation disposition, the two publication modes, conflicting scopes, and blocked recovery.
10. Backend fixtures reproduce admission/defer reasons, request idempotency, receipt confirmation, and unavailable classifications. Run the full backend job, frontend tests/build, and actual CI before merge.
11. Deva’s report closes only after exact-file repairs, reassessment, and delivery are confirmed; his cropped diagram is never silently deleted.

## 11. Parallel implementation plan after design review

| Workstream | Ownership and deliverable |
|---|---|
| A — Automatic approval | Server-owned item dispositions/reasons, automatic drain lifecycle, action labels and review outcome separation. |
| B — Layout and definitions | Tile order/definitions/info controls, compact file-processing summary, document navigation, deliberate retirement of duplicate mounts. |
| C — Publication consistency | Saved-plan snapshot/counter scope, automatic/manual action separation, shared status copy, existing recovery behavior preserved. |
| Integration owner | Coordinate shared Remediate/Publish mounts, reconcile API contracts, combine branches, run integrated validation, merge/deploy, and verify Deva separately. |

Use isolated worktrees and announce exact file ownership. Recheck recent commits/open PRs before edits and pushes; integrate shared screen changes through one owner instead of competing branches.

Implementation does not expand supported document-repair capabilities or promise that every finding can be repaired automatically. The design makes actual automation and remaining work understandable.
