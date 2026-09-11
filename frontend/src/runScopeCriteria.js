import { DOCUMENTS_20 } from './documents20.js'
import { SCOPE_LABEL } from './activeScope.js'

// The success criteria a SPECIFIC run was frozen to at assessment time — read from
// run.scope.scan_scope, which the backend writes once (scanner.py's scope_out["scan_scope"],
// Phase 3a) and never mutates after. This is deliberately NOT the live global scope from
// activeScope.js: that is today's setting, and a past run's own results must go on describing
// what THAT run actually assessed even after the setting changes later — the same
// Assess/Remediate contradiction Phase 3a already fixed for remediation and scoring, applied
// here to the screens that display a run's results.
//
// Returns null when the run carries no evidence either way (no `run.scope`, or a `scope`
// object that predates the `scan_scope` key) — the caller's own default applies rather than
// this module guessing. A real API response always has the key once a run, per the backend's
// own comment: "Recorded even when None ... absent, a reader cannot distinguish an
// unrestricted scan from one that predates this field." So this null case is test fixtures and
// pre-freeze data, not a normal run.
export function runScopeCriteria(run) {
  if (!run || !run.scope || !('scan_scope' in run.scope)) return null
  const map = run.scope.scan_scope
  if (map && typeof map === 'object' && Object.keys(map).length) {
    return new Set(Object.keys(map))
  }
  // scan_scope present but null/empty: the backend recorded NO RESTRICTION for this run,
  // which get_scan_scope's None means everywhere else — the whole document core, not
  // whatever engagement preset happens to be active today.
  return new Set(DOCUMENTS_20)
}

// Whether runScopeCriteria had real evidence to answer from (see the null case above).
export const runScopeIsKnown = (run) => !!(run && run.scope && 'scan_scope' in run.scope)

export function runScopeIsRestricted(run) {
  const map = run?.scope?.scan_scope
  return !!(map && typeof map === 'object' && Object.keys(map).length)
}

export const runScopeLabel = (run) => (runScopeIsRestricted(run) ? SCOPE_LABEL : 'document core')
