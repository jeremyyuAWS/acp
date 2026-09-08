# Live remediation waterfall

The live RemediationOpsPanel mounts RemediationWaterfallCard above the existing
accounting details. It follows the current scan and explicit remediation batch.
This is a results view; opening it performs read-only requests and does not start
AI work, change accepted permissions, raise a cap, or apply a suggestion.

## What is measured

- Finding outcomes use the existing authoritative reconciliation snapshot. The
  bar appears only when all seven recorded dispositions sum to the assessed
  baseline and the server reports exact reconciliation. Partial snapshots keep
  change counts and review-item counts explicitly in their own units. No document
  processing count is converted to a finding count.
- The two-model rail reads the durable spending ledger through the owner-scoped
  `/scans/{sid}/remediation/waterfall/{batch_id}` endpoint. Operation counts
  deduplicate the stable prompt-operation identity across admission retries.
  Reserved, dispatched, settled, released, uncertain, and breached are attempt
  charge states, not a finding outcome or an assertion that a model helped.
- Settled charges, outstanding reservations, remaining allowance, and the
  immutable run cap are separate. Unknown charges retain their holds. Per-tier
  charges do not include unrecognized operation formats; overall charges do.
- Provider/model identities come from exact saved proposal `model_call_id` links
  to `ai_calls`, joined through this batch's finding and review-item records and
  checked against both scan and file. Repeated references count once. Current
  provider settings and pricing URLs are never used to guess historical models.
  Recorded proposal-call costs are an overlapping subset, not added to the run
  ledger. Legacy cloud calls whose cost defaulted to zero show unavailable.

## Evidence still unavailable

The current records do not support complete first-model versus fallback usable
suggestion attribution. A settled charge or a second-model call does not establish
an additional successful suggestion. The card says the contribution breakdown is
unavailable. Model attribution can also be incomplete when a proposal has no
recorded call link. The optional AI reviewer and automatic AI approval threshold
remain disabled; this card does not implement either execution feature.

## Interaction and motion

The outcome legend and table open the existing right drawer shell. Responses must
match the selected batch and displayed bucket count; changing scope or closing
invalidates pending requests. The provider feed similarly rejects stale account
and batch responses, retains the last successful snapshot on refresh errors, and
shows its timestamp. Hidden or visually paused panels stop its refresh timer.

Signed count/currency changes and one-shot stage sweeps follow changed recorded
values. Initial loading, run changes, missing values, and changed metric units do
not create progress badges. Reduced motion removes movement while keeping the
numeric change readable. Detailed accounting and original document operations
remain available below the card.

Validation uses real React DOM tests in the isolated worktree and backend SQLite
fixtures, with a worktree-rendered layout check at desktop and mobile widths.
