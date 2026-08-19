// "Run what I ran last time" — reusable scopes, derived from the runs that actually happened.
//
// WHY THIS IS NOT A NEW STORE. Every scan already freezes its own boundary into
// `scan_runs.scope` at scan start (ADR 0035) and the scans list hands it back decoded, per user.
// That is a better source than a "saved scopes" table would be, for the reason this codebase
// keeps re-learning: a saved scope is a claim about what WILL be covered, while a run's frozen
// scope is a record of what WAS. Only the second can be checked. Reusing one also means the two
// runs are comparable — getScanDiff needs both boundaries to agree before it can tell a document
// that got worse from a document measured against fewer criteria.
//
// THE RULE THAT MATTERS: a run whose scope is NULL is NOT offered. NULL means "no scope recorded"
// — a scan predating the column, or one whose scope JSON would not decode (store.py:
// "unreadable is unknown, not 'whole Drive'"). Offering it would apply as an empty selection,
// and an empty selection means EVERYTHING. That is silent widening: the direction nobody
// re-checks, arrived at by clicking something labelled as a narrowing.
//
// `scope` shapes come from scanner._list's scope_out:
//   folders     [{id, name}]     — the chosen roots, named server-side
//   excluded    [id, …]          — bare ids (sorted(excl)); names are NOT recorded on the run
//   scan_scope  {sc: [fmts]}|null — the criteria the run was frozen to; null = no restriction

// Which stored-location family a run's source belongs to. Drive folder ids and Graph
// `<driveId>/<itemId>` pairs are not interchangeable, so a Drive scope must never be offered for
// a OneDrive scan: the ids would be accepted, resolve to nothing, and the run would come back
// empty with a boundary that looks deliberate.
export function scopeFamily(source) {
  if (source === 'drive' || source === 'all') return 'drive'
  if (source === 'sharepoint' || source === 'onedrive') return 'sharepoint'
  return null
}

const ids = (rows) => (Array.isArray(rows) ? rows : [])
  .map((f) => (typeof f === 'string' ? f : f && f.id))
  .filter(Boolean)

// Normalise the two exclusion shapes to one. A run records bare ids; the wizard holds {id,name}.
// `name: null` is kept as null rather than filled with the id: an opaque Drive id rendered where
// a folder name belongs is not a boundary a reader can check anything against, and a caller that
// cannot tell the difference will print it.
const asRows = (rows) => (Array.isArray(rows) ? rows : [])
  .map((f) => (typeof f === 'string' ? { id: f, name: null } : (f && f.id ? { id: f.id, name: f.name || null } : null)))
  .filter(Boolean)

// A stable identity for one scope, so the same boundary run five times is offered once.
// Sorted, because "HR then Finance" and "Finance then HR" are the same estate — treating them as
// two would fill the list with duplicates and push the genuinely different one off the end.
export function scopeKey(scope) {
  if (!scope) return null
  const inc = ids(scope.folders).slice().sort()
  const exc = ids(scope.excluded).slice().sort()
  const crit = scope.scan_scope && typeof scope.scan_scope === 'object'
    ? JSON.stringify(Object.keys(scope.scan_scope).sort()
        .map((sc) => [sc, [...(scope.scan_scope[sc] || [])].slice().sort()]))
    : ''
  return `${inc.join('|')}::${exc.join('|')}::${crit}`
}

// Is this scope worth offering as a shortcut at all? "Entire source, everything supported" is
// the wizard's own default — listing it as a recent scope adds a control that does nothing, and
// a list where some entries are no-ops is one nobody reads carefully.
export const isDefaultScope = (scope) => !!scope
  && ids(scope.folders).length === 0
  && !(scope.scan_scope && Object.keys(scope.scan_scope).length)

/**
 * The distinct scopes this user has actually run for `family`, newest first.
 *
 * @param scans  the rows from listScans() — each carries `scope` (decoded dict or null)
 * @param family 'drive' | 'sharepoint' — from scopeFamily(); null returns []
 */
export function reusableScopes(scans, family, limit = 3) {
  if (!family || !Array.isArray(scans)) return []
  const out = []
  const seen = new Set()
  // listScans() is already ORDER BY completed_at DESC, but sorting here rather than trusting that
  // keeps this function honest against a caller that filtered or concatenated first.
  const rows = scans.slice().sort((a, b) => String(b.completed_at || '').localeCompare(String(a.completed_at || '')))
  for (const run of rows) {
    const scope = run && run.scope
    if (!scope) continue                                   // unknown ≠ everything — see the header
    if (scopeFamily(run.source) !== family) continue
    if (isDefaultScope(scope)) continue
    const key = scopeKey(scope)
    if (!key || seen.has(key)) continue
    seen.add(key)
    const excluded = asRows(scope.excluded)
    out.push({
      key,
      scanId: run.id,
      at: run.completed_at || null,
      source: run.source,
      folders: asRows(scope.folders),
      excluded,
      // The run recorded exclusion IDS only. A caller must say so rather than printing an id or,
      // worse, dropping the carve-out — dropping it widens the scan while the label still reads
      // as a narrowing.
      unnamedExclusions: excluded.some((f) => !f.name),
      scanScope: scope.scan_scope && Object.keys(scope.scan_scope).length ? scope.scan_scope : null,
    })
    if (out.length >= limit) break
  }
  return out
}

// One line naming the whole boundary — locations AND criteria. Both halves always, because a
// reader given one without the other cannot reconstruct what was measured, which is the same
// reason the run records them together.
export function describeScope(entry) {
  if (!entry) return ''
  const named = entry.folders.map((f) => f.name).filter(Boolean)
  const where = named.length
    ? named.join(', ')
    : (entry.folders.length ? `${entry.folders.length} folder${entry.folders.length === 1 ? '' : 's'}` : 'Entire source')
  const parts = [where]
  if (entry.excluded.length) {
    const excNames = entry.excluded.map((f) => f.name).filter(Boolean)
    parts.push(excNames.length === entry.excluded.length
      ? `except ${excNames.join(', ')}`
      // Said plainly rather than dressed up. The carve-out is real and is being carried over;
      // what is missing is only its name, and a reader who is told that can go and look.
      : `except ${entry.excluded.length} folder${entry.excluded.length === 1 ? '' : 's'} (not named on that run)`)
  }
  parts.push(entry.scanScope
    ? `${Object.keys(entry.scanScope).length} criteria`
    : 'Everything supported')
  return parts.join(' · ')
}

// "18 Aug" / "today" — enough to tell two entries apart without pretending to a precision the
// list does not need. `now` is injected so this is testable without freezing the clock.
export function whenLabel(iso, now = new Date()) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const days = Math.floor((now - d) / 86400000)
  if (days <= 0) return 'today'
  if (days === 1) return 'yesterday'
  return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' })
}
