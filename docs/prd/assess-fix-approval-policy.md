# Assess fix approval policy

Approved September 13, 2026.

## Objective

Let the scan owner choose automatic or human approval separately from assessment scope. Only supported, valid repairs can run automatically. Approval, writing, verification and publication remain separate facts.

## Assess interface

Place a compact, initially collapsed **Fix approval policy** section below selected success criteria, using Assess cell spacing, typography and colored pills. Its summary reports the effective policy and counts.

Choices:

- **Automatic approval — recommended:** apply supported proposals, save changes and check the corrected copy.
- **Review proposed fixes:** require human approval for supported proposals; repairs without a supported approval writer remain explicitly manual.
- **Customize by criterion:** use automatic approval except for selected SCs requiring review.

Customization includes criterion search, automatic/review controls, all-automatic/all-review actions and review-only filtering. Capability descriptions reflect selected document formats. Do not offer Ignore, Mark passed or Force automatic.

Save `fix_approval_policy = {mode: automatic|review|custom, review_scs: [...]}` with the scan and remediation execution. Selected SC scope and publication authorization are independent. Show a pre-start summary and the separate publication setting.

## Remediate

Default to Live activity. Needs your input shows actionable exceptions: human decisions, missing information and manual document edits. Distinguish missing proposals, blocked AI requests, failed checks and unknown status from approval tasks. Automatically managed proposals belong in processing/results. Disable duplicate application while work is active. Show failed criteria and reasons.

Historical scans remain read-only. Current-scan outstanding decisions remain actionable after Release starts, without restarting earlier workflow stages. A changed corrected copy requires fresh verification and a newly authorized publication version; existing frozen deliveries are never silently amended.

Refresh errors retain recorded data and the last confirmed same-run approval preference. Unknown is not Off. Provide a retry action without replaying uncertain writes.

## Release

Automatic publication requires no additional Publish click for authorized eligible saved copies. Publish exactly the saved bytes that were checked. Reuse successful verification only when identity, bytes, correction timestamp, scope and evaluator fingerprint match; changed or unknown evidence requires a new check. Publication does not certify accessibility.

## Acceptance

- Approval preference does not change assessment scope or capability.
- Automatic/custom protected criteria follow saved policy, including baseline routing.
- No unsupported writer, missing proposal or failed check produces verified credit.
- Review actions save durably before advancing; historical controls are disabled.
- Counts do not double-count categories and distinguish items from findings.
- Keyboard and screen-reader access work without color dependence.
- Full flow covers supported fixes, unsupported PDF tagging, blocked requests, failed checks, changed saved copies and refresh recovery.
