// Which documents "Remediate all" would act on — and, when that set is empty, WHY.
//
// The button used to enqueue an empty scope and the server would answer `enqueued: 0`, which
// the UI reported as the unhelpful "Nothing to remediate — no eligible files with issues."
// A user staring at three failing documents cannot act on that: the real answer is almost
// always "they already have a fixed copy", or "you marked them deferred", and each of those
// has a different next step.
//
// The eligibility test lives here so the reason and the set can never disagree: `remediable`
// is `files.filter(f => !ineligibleReason(f, opts))`, and the explanation counts exactly the
// files that test rejected, bucketed by the FIRST rule that rejected them (so a document that
// is both already-remediated and deferred is counted once, under the rule that actually
// excluded it — no double-counting, no total that exceeds the document count).

// Buckets, in the order the filter applies them. Phrases are noun-ish so they compose into a
// list without verb agreement: "2 already remediated, 1 outside your in-scope selection".
export const SCOPE_REASONS = {
  remediated: 'already remediated',
  noAutoFix: 'with no automatic fix for their findings',
  triaged: 'marked not-applicable or deferred',
  outOfScope: 'outside your in-scope selection',
}

// The first rule that excludes this file, or null when it is eligible. Mirrors Remediate.jsx's
// `remediable` filter exactly — that filter is defined in terms of this function.
export function ineligibleReason(f, { triage = {}, hasInscopeSelections = false, remActions = [] } = {}) {
  if (!f) return 'noAutoFix'
  if (f.remediated_at || f.drive_write_url) return 'remediated'
  if (!f.rec || !remActions.includes(f.rec.action)) return 'noAutoFix'
  if (triage[f.file] === 'na' || triage[f.file] === 'defer') return 'triaged'
  if (hasInscopeSelections && triage[f.file] !== 'inscope') return 'outOfScope'
  return null
}

export const remediableFiles = (files, opts) => (files || []).filter((f) => !ineligibleReason(f, opts))

// Said out loud when the user presses the button and nothing would happen. Names the counts and
// the next step. Never guesses: every number here is a document this scan actually holds.
export function emptyScopeReason(files, opts) {
  if (!files || files.length === 0) return 'Nothing to remediate — this scan has no documents.'

  const counts = {}
  for (const f of files) {
    const r = ineligibleReason(f, opts)
    if (r) counts[r] = (counts[r] || 0) + 1
  }
  const parts = Object.keys(SCOPE_REASONS)
    .filter((k) => counts[k])
    .map((k) => `${counts[k]} ${SCOPE_REASONS[k]}`)

  if (!parts.length) return 'Nothing to remediate — no eligible documents.'

  const next = counts.remediated && !counts.triaged && !counts.outOfScope
    ? 'Re-scan to pick up new findings, or open a document and re-validate it.'
    : counts.triaged || counts.outOfScope
      ? 'Clear a triage flag, or mark a document in-scope, to make it eligible.'
      : 'Re-scan to pick up new findings.'

  const n = files.length
  return `Nothing to remediate — of ${n} document${n === 1 ? '' : 's'}: ${parts.join(', ')}. ${next}`
}
