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

// ── the per-document scope, as a thing other screens can ask about ────────────────────────────
//
// Marking ONE document in scope excludes every unmarked one — that is what `ineligibleReason`'s
// `hasInscopeSelections` branch does. It is the second filter in this product, alongside the
// criterion × format `scan_scope`, and until now it lived entirely inside Remediate: the
// predicate was written out by hand in three places there, and Publish — the screen that
// produces the compliance record — had no idea it existed.
//
// So an operator could mark 2 of 258 documents, remediate those two, and read a conformance
// report whose every number is about 258. "Certified" against an unstated document scope is the
// same unverifiable claim as certified against an unstated criterion scope, which is what
// ScopeBanner was built for.
//
// One definition here, used by both screens, for the reason `_rule_outcome` is one gate: two
// copies of a filter are two chances for the screen and the button to disagree.

// Is a per-document restriction in force at all? Deliberately over ALL triage values rather than
// over the current file list — that is exactly what the eligibility gate tests, and a statement
// derived from a narrower question could report "no restriction" while the gate excludes
// everything.
export const hasDocumentSelection = (triage) =>
  Object.values(triage || {}).some((v) => v === 'inscope')

// null when nothing is restricted, so callers can render nothing without a special case.
export function documentSelection(files, triage = {}) {
  if (!hasDocumentSelection(triage)) return null
  const list = files || []
  const marked = list.filter((f) => triage[f.file] === 'inscope').length
  return { marked, total: list.length, excluded: list.length - marked }
}

// The sentence, so Remediate and Publish cannot word the same fact differently.
export function documentScopeSentence(sel) {
  if (!sel) return null
  if (sel.marked === 0) {
    // The restriction is in force and nothing in THIS scan satisfies it — marks left over from a
    // different set of documents. Worth its own wording: "0 of 258 in scope" reads like a
    // starting state rather than a filter that will remediate nothing.
    return `A document selection is active but none of these ${sel.total.toLocaleString()} `
      + 'documents are marked in scope, so nothing here will be remediated.'
  }
  return `${sel.marked.toLocaleString()} of ${sel.total.toLocaleString()} documents marked in `
    + `scope — the other ${sel.excluded.toLocaleString()} are not remediated.`
}

// What the scope panel must SAY, derived from the same eligibility test the button acts on.
//
// The panel used to show three chips — "N in scope · N N/A · N deferred" — each counting only
// EXPLICIT per-row decisions. On a 258-document scan that read "2 in scope · 0 N/A · 0 deferred"
// with all 258 rows listed, which invites exactly one reading: two documents have been triaged
// so far and the rest default in. The opposite was true. `ineligibleReason` excludes every
// unmarked file the moment ANY file is marked in-scope, so 256 documents were dropped from the
// run with nothing on screen saying so — while the help text "Only in-scope files are
// remediated" stayed technically true and completely uninformative.
//
// The missing number is `excluded.outOfScope`: documents this run will NOT touch, that the
// reader believes it will. emptyScopeReason() already named it honestly, but only fires when
// NOTHING is remediable — the all-or-nothing case. This reports the same buckets at every
// scope size, so a partial selection is as legible as an empty one.
export function scopeSummary(files, opts) {
  const list = files || []
  const excluded = {}
  let eligible = 0
  for (const f of list) {
    const r = ineligibleReason(f, opts)
    if (r) excluded[r] = (excluded[r] || 0) + 1
    else eligible += 1
  }
  return {
    total: list.length,
    eligible,
    excluded,
    // True when the in-scope selection itself is what is holding documents back — the case
    // that needs saying out loud, because it is the one the user created by accident.
    restrictedBySelection: (excluded.outOfScope || 0) > 0,
  }
}

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
