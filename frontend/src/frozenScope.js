// What a COMPLETED scan actually covered — read from the run, never from the live setting.
//
// `run.scan_scope` is the criterion→formats map the scan was FROZEN to at scan-start (Phase 3a,
// PR #267; store.get_scan projects it onto the run payload for exactly this chip — see
// api/store.py:1620). Shape: `{ "1.1.1": ["docx","pdf"], … }`, or `null` for NO RESTRICTION.
//
// `null` means the WHOLE document-core set — NOT an empty scope. Those are opposite meanings and
// one of them is the reassuring lie every scope module here refuses to tell: a scope we cannot
// read must collapse to neither "everything" nor "nothing". Same discipline as scanScope.js (the
// file/source boundary) and activeScope.js (the live global criteria scope).
//
// THE WHOLE POINT of R6 is that a scan's scope is frozen: the operator can change the global scope
// after a scan, and this must keep stating what THIS scan covered — read from the run — rather
// than silently re-describing it with the current setting. That drift is the same failure class as
// scanScope.js's "1 file then 8 files" incident: a number that changed for a reason nobody could
// see, because what it was a count OF was never stated.

// The criteria a scan covered, as a Set. A null/absent map means the whole core, so the caller's
// `coreScs` is returned rather than an empty set — the "unrestricted" reading, made explicit.
export function scanCriteria(scanScope, coreScs) {
  if (!scanScope || typeof scanScope !== 'object') return new Set(coreScs || [])
  return new Set(Object.keys(scanScope))
}

// The document formats a scan assessed — the union of the map's format lists. `null` when the
// scope is unrestricted, so a caller says "all types" rather than inventing a list.
export function scanDocTypes(scanScope) {
  if (!scanScope || typeof scanScope !== 'object') return null
  const s = new Set()
  for (const fmts of Object.values(scanScope)) for (const f of (fmts || [])) s.add(f)
  return [...s].sort()
}

// A short chip: what this scan covered, criteria-wise. Always returns a label, including the
// unrestricted case — a label that appears only on narrowed scans is invisible exactly when a
// reader is comparing two scans and needs to spot the odd one (the lesson of scanScope.js).
export function frozenScopeChip(scanScope, coreScs) {
  const core = (coreScs && coreScs.size) || 0
  if (!scanScope || typeof scanScope !== 'object') {
    return { text: core ? `all ${core} criteria` : 'all criteria', restricted: false }
  }
  const n = Object.keys(scanScope).length
  return { text: `${n} of ${core || n} criteria`, restricted: core ? n < core : true }
}

// The full sentence for the panel. Names the criteria count and the doc types, and says NOTHING
// guessy when the scope is unknown — the unrestricted branch is a fact about the run, not a hope.
export function frozenScopeSummary(scanScope, coreScs) {
  const core = (coreScs && coreScs.size) || 0
  if (!scanScope || typeof scanScope !== 'object') {
    return `This scan assessed all ${core ? `${core} ` : ''}document-core criteria — no scope narrowing was in force.`
  }
  const n = Object.keys(scanScope).length
  const types = scanDocTypes(scanScope)
  let s = `This scan was scoped to ${n}${core ? ` of ${core}` : ''} document-core criteria`
  if (types && types.length) s += `, on ${types.join(', ')} files`
  return s + '.'
}

// The impact of re-scanning under a DIFFERENT scope: which criteria the change would add or drop.
//   `scanScope` — this scan's frozen scope (map or null),
//   `nextScs`   — the criteria a re-scan would use (the live global SCOPE_SCS),
//   `coreScs`   — backs the null=whole-core reading of the frozen side.
// The criteria delta is EXACT. File impact is deliberately NOT computed here: there is no per-scan
// dry-run/preview endpoint (a re-scan is the only way the backend produces a real file count), so
// fabricating an added/dropped file number would be precisely the invented figure this codebase
// keeps out. The caller shows the affected file population from the scan's own inventory instead.
export function scopeImpact(scanScope, nextScs, coreScs) {
  const prev = scanCriteria(scanScope, coreScs)
  const next = new Set(nextScs || [])
  const added = [...next].filter((sc) => !prev.has(sc)).sort()
  const dropped = [...prev].filter((sc) => !next.has(sc)).sort()
  return {
    prevCount: prev.size,
    nextCount: next.size,
    added,
    dropped,
    changed: added.length > 0 || dropped.length > 0,
  }
}
