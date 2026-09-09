# Measured remediation contribution

The `remediation-contribution.v1` object in run insights counts immutable selected
baseline findings, not review cards, model calls, retries, or proposal versions.
The baseline is frozen in the job admission transaction. A run whose selected
files lack recorded assessment traces has no measurable denominator; older runs
are not backfilled from current mutable traces.

`outcomes` partitions the baseline into fixed, awaiting_review, approved,
unresolved, processing, and unavailable. `contributions` counts unique findings
first covered by rules, first_ai, or fallback_ai. Explicit fallback lineage must
record an unusable/empty earlier draft in the same operation. The earliest usable
origin retains credit across revisions. Reviews count proposals separately and
never increase the finding denominator. The UI provides bars, equivalent tables,
and matching right drawers; refreshing retains the last good scope-bound result.

## Durable proof

Existing proposal snapshots and human approval audit records remain authoritative.
The contribution mapping adds the exact input-byte SHA, assessment revision, and
explicit baseline finding membership. One proposal can cover several IDs. A lone
finding for a file/rule is unambiguous; multi-instance aggregate ordinals are never
zipped with generated proposal positions. Producers may supply
`baseline_finding_ids` only from an authoritative finding binding.

The controlled writer freezes the approved queue digest and audit event, compares
its actual locator/value inputs, then records actual source/value proof in the
existing `ai_validation_outcomes`. Credit requires the exact unchanged draft value,
source SHA, approval event, assessment revision, no unknown regressions, actual
applied locator/value, and final-artifact verification. A later lane regression
cannot credit an earlier lane. New attempts can supersede failures; redelivery of
the same writer attempt is deduplicated.

## Limits and prerequisites

- Live Drive input must match retained assessed bytes before attribution is recorded. Changed Drive content or a missing assessment cache can still follow the existing remediation path, with contribution unavailable; reassessment is needed to establish a new attributable baseline. Local corpus fallback without retained assessed bytes is likewise unattributed.
- Missing multi-instance mappings remain unavailable; the implementation does not
  manufacture per-element identities from aggregate assessment counts.
- An edited human value does not inherit exact-version proof for the old AI draft.
- Generic reviewer text hashes do not prove structured proposal review. Unmatched
  reviews remain unavailable in the separate reviewer count.
- Automatic policy application requires a registered authoritative writer/reviewer
  adapter and calibrated evidence; no production family is enabled by this feed.
- Deterministic inline writes without this exact joined proof remain outside the
  fixed contribution count. Existing delivery and rule-based execution continue.
- No live calibration, predicted benefit, or customer result is synthesized.

Fixtures cover five fallback findings across retries/revisions, a proposal covering
multiple findings, mismatched versions/values, stale source, owner isolation,
partial reconciliation, failed and recovered verification, actual writer input
mismatch, erasure, and a later lane regressing an earlier fix.
