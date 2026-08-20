// The run-side facts the estate inventory cannot know, read off a scan run and its file rows.
//
// `estateFunnel.reconcileBuckets` is pure and dependency-free — it partitions an inventory and is
// unit-testable without a scan. This module is the adapter: it turns the two things the Overview
// actually holds (`run` and `files`) into that function's `opts`, and it is kept OUT of
// estateFunnel.js for exactly the reason estateProgress.js is — that module must stay free of the
// file-shape helpers (docStatus / frozenScope) so it can be reasoned about on its own.
//
// EVERY FIELD HERE IS OPTIONAL AND MAY BE ABSENT. `undefined` travels through to a null bucket and
// a stated shortfall; nothing is defaulted to 0 on the way. A scan that never recorded a fact must
// not come out the far end asserting that the fact was zero.

import { statusOf, NOT_ASSESSED } from './docStatus.js'
import { scanDocTypes } from './frozenScope.js'

// A file that was opened and refused. Same verdict the drawer, the donut and the certification PDF
// use (docStatus.statusOf), so this bucket can never disagree with the rest of the screen about
// which files those are.
const isUnreadable = (f) => statusOf(f) === 'unanalysable'

// Opened AND given a verdict. Deliberately NOT `analysedCount`: that counts every row somebody
// looked at, INCLUDING the ones that refused to open, and this partition needs those two separated
// so `assessed` and `unreadable` do not both claim the same file. The relationship is exact —
//
//     assessed + unreadable === analysedCount(files)
//
// — so the bucket still agrees with the coverage funnel's "Assessed" stage, which is that sum. It
// is pinned by test rather than left to be rediscovered.
const isAssessed = (f) => {
  const s = statusOf(f)
  return s !== NOT_ASSESSED && s !== 'unanalysable'
}

/**
 * Build `reconcileBuckets` opts from a scan run and its file rows.
 *
 * `run.scope` is discovery's own record of what it covered (scanner._list's scope_out);
 * `run.scan_scope` is the frozen criterion→formats map (frozenScope.js). Both are read from the
 * RUN, never from the live global setting — an operator who re-scoped after this scan must still
 * see what THIS scan assessed.
 */
export function reconciliationInputs(run, files) {
  const fs = files || []
  const scope = (run && run.scope) || {}
  const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : undefined)

  return {
    assessed: fs.filter(isAssessed).length,
    unreadable: fs.filter(isUnreadable).length,
    // Discovery's own count of files dropped for their document type. Absent on a scan that had no
    // file-type scope in force AND on a scan predating the counter — indistinguishable from here,
    // so it is passed through as absent and the frozen-scope derivation below decides.
    typeNotSelected: num(scope.skipped_out_of_scope),
    // null = "no narrowing was in force" (frozenScope's documented contract for a null scan_scope),
    // an array = the formats this run assessed. Never a guess in either direction.
    selectedFormats: scanDocTypes(run && run.scan_scope),
    // The lifecycle counters, when the run carries them. api/wcag_codeset.lifecycle_exclusion
    // already computes exactly this pair for the Assess scope preview
    // (`lifecycle_eligible_excluded` — the FLAGGED subset whose format had a lane, which is why it
    // can never overlap the no-test bucket). No scan run persists it yet, so on today's data this
    // is `undefined` and the lifecycle row renders "not recorded by this scan" rather than a zero
    // that would claim nothing was held back.
    lifecycleExcluded: num(scope.lifecycle_eligible_excluded),
    lifecycleOverridden: num(scope.lifecycle_overridden),
  }
}
