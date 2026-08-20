// "How big is this?" — answered with a number that was actually measured, or not at all.
//
// The obvious build for this was a pre-scan estimate: walk the chosen folders, count what comes
// back, print it on the review step. It was NOT built, and the reason is the same one this
// codebase keeps re-learning.
//
// 1. Under ADR 0020 a Discover run IS the listing — it enumerates and persists an inventory and
//    stops, without opening a file. So an estimate is not a cheap preview of an expensive
//    operation; it is very nearly the operation, run twice.
// 2. Worse, it would put a SECOND number for the same estate on screen, produced at a different
//    moment under a different cap. Two numbers that can disagree, both correct, is the shape of
//    the 2026-07-30 defect (frontend/src/scanScope.js) — the one where "1 document" and "8
//    documents" six seconds apart read as an estate that shrank.
//
// So instead: report what THIS EXACT SCOPE covered the last time it was run. That number was
// measured, it is stored with its own boundary frozen beside it (scan_runs.scope, ADR 0035), and
// it is the number the user will compare the new run against anyway.
//
// And when there is no such run, say so and stop. A first run of a new scope genuinely has no
// count yet, and inventing one for exactly the case where no evidence exists is the worst of both
// options — the estimate would be least checkable precisely where it was least informed.
import { scopeKey, scopeFamily } from './recentScopes.js'

/**
 * The most recent completed run whose FROZEN scope is identical to `scope`.
 *
 * @param scans  rows from listScans() — each carries `scope` (decoded dict or null) and `files`
 * @param scope  the scope about to be run, in the shape scanner records it:
 *               { folders: [{id,name}], excluded: [...], scan_scope: {sc:[fmts]}|null }
 * @param family 'drive' | 'sharepoint', from scopeFamily()
 * @returns {{at, files, truncated, scanId}} | null
 */
export function lastRunOfScope(scans, scope, family) {
  if (!family || !Array.isArray(scans)) return null
  const want = scopeKey(scope)
  if (!want) return null
  const rows = scans
    .filter((r) => r && r.scope && scopeFamily(r.source) === family)
    // A run with no file count answers nothing. `files` is NULL on a row that never finished
    // listing; rendering it as 0 would say "that scope covered nothing", which is a stronger and
    // more wrong claim than saying nothing at all.
    .filter((r) => typeof r.files === 'number')
    .filter((r) => scopeKey(r.scope) === want)
    .sort((a, b) => String(b.completed_at || '').localeCompare(String(a.completed_at || '')))
  const hit = rows[0]
  if (!hit) return null
  return {
    scanId: hit.id,
    at: hit.completed_at || null,
    files: hit.files,
    // The cap is part of the number. A truncated listing did not see the estate, so its count is
    // a floor, not a total — and a floor printed as a total is the same substitution of a number
    // for a boundary this whole module exists to avoid.
    truncated: !!hit.scope.truncated,
  }
}

// The sentence for the review step. Deliberately one function, so the "we have a number" and the
// "we do not" cases cannot drift into different registers — the second is not a degraded version
// of the first, it is the honest answer to a different situation.
export function coverageSentence(last, whenText = '') {
  if (!last) {
    return 'No earlier run of this exact scope — the document count is determined when the scan starts.'
  }
  const when = whenText ? ` (${whenText})` : ''
  const n = last.files.toLocaleString()
  return last.truncated
    ? `Last run of this exact scope${when} listed ${n} documents and hit its listing cap — the real total is higher.`
    : `Last run of this exact scope${when} covered ${n} document${last.files === 1 ? '' : 's'}.`
}
