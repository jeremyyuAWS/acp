// Source operations — the facts a "Manage <source>" panel needs, derived from data ACP
// actually holds.
//
// This module exists because the source drawer used to answer the wrong question. It showed a
// compliance donut, a top-flagged-documents list and a paragraph about an "agent" — an Assess
// summary wearing a Sources label — while saying nothing about whether the connection works,
// what ACP is allowed to see, or what the last discovery run did. Worse, it rendered
// `undefined · 0 docs · agent: undefined` in its subtitle for a card the page had just badged
// **Healthy**, because the OneDrive card is a hard-coded CONNECTABLE row with no `dept`/`agent`
// and its file rows live under the `sharepoint` source key, not `sp-root`. A panel that
// contradicts the card next to it is worse than a panel with less on it.
//
// TWO RULES HOLD THROUGHOUT, and they are the reason this is a separate, pure module:
//
//   1. EVERY NUMBER IS DERIVED FROM A PROP. Nothing here invents a plausible figure. The PRD
//      this implements sketches "12,486 files · 3,216 folders · 14 locations · 8.4 GB"; only
//      the ones the file rows can support are computed, and the rest return `null`.
//   2. `null` IS A RENDERABLE ANSWER, `undefined` IS NOT. Callers turn `null` into
//      "Not available" / "Not configured" — see NOT_AVAILABLE / NOT_CONFIGURED. The defect
//      above was not a missing feature, it was a missing value printed anyway.
//
// Pure and React-free so vitest can exercise it without a DOM.

export const NOT_AVAILABLE = 'Not available'
export const NOT_CONFIGURED = 'Not configured'

// ── Which rows belong to a card ───────────────────────────────────────────────
//
// A connector card, its backend `sources` row, its `files` rows and its `scan_runs` rows each
// name the same source differently, and the drawer used to match on the card id alone. The
// OneDrive card's id is `sp-root`; its file rows carry `source: 'sharepoint'` and its runs carry
// `source: 'sharepoint'`. `f.source === 'sp-root'` therefore matched nothing, which is where
// "0 docs" came from — not from an empty estate.
const ALIASES = {
  google_drive: ['google_drive', 'gdrive', 'drive', '_gdrive'],
  onedrive: ['onedrive', 'sharepoint', 'sp-root', 'sp'],
  sharepoint: ['onedrive', 'sharepoint', 'sp-root', 'sp'],
}

/** Every key that names this source, lower-cased — its own id and type plus the aliases. */
export function sourceKeys(source) {
  if (!source) return []
  const seen = new Set()
  const push = (v) => { const s = String(v || '').toLowerCase(); if (s) seen.add(s) }
  push(source.id); push(source.type); push(source.kind)
  ;(ALIASES[source.type] || ALIASES[source.kind] || []).forEach(push)
  return [...seen]
}

/** The file rows belonging to this source. Falls back to every row only when a source carries
 *  no identity at all — never silently, since a wrong subset is what produced "0 docs". */
export function filesForSource(files, source) {
  const keys = new Set(sourceKeys(source))
  if (!keys.size) return []
  return (files || []).filter((f) => keys.has(String(f.source || '').toLowerCase())
    || keys.has(String(f.sourceName || '').toLowerCase().replace(/\s+/g, '_')))
}

/** This source's scan runs, newest completed first. Runs with no `source` are NOT assumed to be
 *  this source's — an all-sources run is `source: 'all'`, which is a different fact. */
export function runsForSource(scans, source) {
  const keys = new Set(sourceKeys(source))
  return (scans || [])
    .filter((s) => keys.has(String(s.source || '').toLowerCase()))
    .slice()
    .sort((a, b) => String(b.completed_at || b.started_at || '').localeCompare(String(a.completed_at || a.started_at || '')))
}

// ── Inventory ─────────────────────────────────────────────────────────────────

const sizeKbOf = (f) => {
  const v = f.sizeKB != null ? f.sizeKB : f.size_kb
  return typeof v === 'number' && isFinite(v) ? v : null
}

/** The folder portion of a row's path, or '' when the source reports flat names.
 *  SIM and several connectors report bare filenames; that is "no folder", not "root". */
export const folderOf = (f) => {
  const p = f.folder || f.path || f.file || ''
  const i = String(p).lastIndexOf('/')
  return i > 0 ? String(p).slice(0, i) : ''
}

/** Headline inventory facts. Each is `null` when the rows cannot support it — a source that
 *  reports no folders yields `folders: null`, never `0`, because "we don't know" and "there are
 *  none" are different claims and only one of them is about the estate. */
export function inventoryFacts(files) {
  const rows = files || []
  const sized = rows.map(sizeKbOf).filter((v) => v != null)
  const folders = new Set(rows.map(folderOf).filter(Boolean))
  const owners = new Set(rows.map((f) => f.owner).filter(Boolean))
  const depts = new Set(rows.map((f) => f.department || f.dept).filter(Boolean))
  return {
    documents: rows.length,
    // Partial size data would understate the estate silently, so the total is reported only
    // when every row carries a size.
    bytesKb: sized.length && sized.length === rows.length ? sized.reduce((a, b) => a + b, 0) : null,
    folders: folders.size || null,
    owners: owners.size || null,
    departments: depts.size || null,
  }
}

// ── Discovery outcome ─────────────────────────────────────────────────────────
//
// A PARTITION, not a set of overlapping tallies. Every discovered row lands in exactly one
// bucket and the buckets sum to the total, so a reader can add them up and be right. Precedence
// runs top-down and mirrors the backend: an archive/delete candidate is NOT "available for
// assessment", because Discover's lifecycle pass (#320) excludes lifecycle-flagged rows from
// Assess by default. Ordering these the other way would advertise assessment coverage over
// files Assess will skip.

export const ASSESSABLE_TYPES = ['docx', 'pdf', 'pptx', 'xlsx', 'html']

export const DISPOSITIONS = [
  ['assessable', 'Available for assessment', 'ok'],
  ['unsupported', 'Unsupported, inventoried only', 'muted'],
  ['archive', 'Tagged for archive', 'review'],
  ['delete', 'Tagged for deletion review', 'review'],
  ['excluded', 'Excluded by rule', 'muted'],
  ['unreadable', 'Could not be read', 'fail'],
]

/** Default lifecycle label for a row, in the vocabulary FileDrawer's `retentionOf` uses.
 *  Callers pass their own so this module never has to import a React component. */
const defaultLabelOf = (f) => f.lifecycle_status || f.lifecycleStatus || ''

/** Which single bucket a row lands in. `labelOf` returns a retention/lifecycle label. */
export function dispositionOf(f, labelOf = defaultLabelOf) {
  if (f.locked) return 'unreadable'
  if (f.excluded || (f.tags || []).includes('excluded-by-rule')) return 'excluded'
  const label = String(labelOf(f) || '').toLowerCase()
  if (label.includes('delete')) return 'delete'
  if (label.includes('archive')) return 'archive'
  const type = String(f.type || '').toLowerCase()
  return ASSESSABLE_TYPES.includes(type) ? 'assessable' : 'unsupported'
}

/** The full outcome table — every bucket, in a stable order, counts summing to files.length. */
export function dispositionRows(files, labelOf = defaultLabelOf) {
  const count = Object.fromEntries(DISPOSITIONS.map(([k]) => [k, 0]))
  ;(files || []).forEach((f) => { count[dispositionOf(f, labelOf)] += 1 })
  return DISPOSITIONS.map(([key, label, tone]) => ({ key, label, tone, count: count[key] }))
}

// ── Runs ──────────────────────────────────────────────────────────────────────

/** How a run ended, in words a reader can act on. `error` is files the engine could not open —
 *  a completed run that could not read part of its scope is NOT a clean run, and saying so is
 *  the difference between "Healthy" and a support ticket a month later. */
export function runOutcome(run) {
  if (!run) return null
  if (run.status && !['done', 'complete', 'completed', 'finalized'].includes(String(run.status).toLowerCase()) && !run.completed_at) {
    return { key: 'running', label: 'In progress' }
  }
  if (!run.completed_at) return { key: 'unknown', label: 'Did not complete' }
  if ((run.error || 0) > 0) return { key: 'warn', label: 'Completed with warnings' }
  return { key: 'ok', label: 'Completed' }
}

/** Elapsed run time in ms, or null when either end is missing/unparseable. */
export function runDurationMs(run) {
  if (!run || !run.started_at || !run.completed_at) return null
  const a = Date.parse(run.started_at); const b = Date.parse(run.completed_at)
  if (!isFinite(a) || !isFinite(b) || b < a) return null
  return b - a
}

// ── Needs attention ───────────────────────────────────────────────────────────

/** Only actionable items, never a reassurance. An empty array means the caller shows a single
 *  green "No discovery issues" line — not "All clear in this sample", which is a claim about a
 *  sample the reader never chose and cannot see. */
export function needsAttention({ files = [], runs = [], labelOf = defaultLabelOf } = {}) {
  const out = []
  const latest = runs[0] || null
  const unreadable = files.filter((f) => dispositionOf(f, labelOf) === 'unreadable').length
  const runErrors = latest && (latest.error || 0) > 0 ? latest.error : 0
  const inaccessible = Math.max(unreadable, runErrors)
  if (inaccessible > 0) {
    out.push({ key: 'inaccessible', tone: 'fail',
      title: `${inaccessible.toLocaleString()} file${inaccessible === 1 ? '' : 's'} could not be read`,
      detail: 'The source refused access or the file could not be opened.' })
  }
  const del = files.filter((f) => dispositionOf(f, labelOf) === 'delete').length
  if (del > 0) {
    out.push({ key: 'delete', tone: 'review',
      title: `${del.toLocaleString()} file${del === 1 ? '' : 's'} match a deletion rule`,
      detail: 'Approval is required before any action.' })
  }
  const arch = files.filter((f) => dispositionOf(f, labelOf) === 'archive').length
  if (arch > 0) {
    out.push({ key: 'archive', tone: 'review',
      title: `${arch.toLocaleString()} file${arch === 1 ? '' : 's'} are archive candidates`,
      detail: 'Review before anything is moved.' })
  }
  if (!latest) {
    out.push({ key: 'never', tone: 'review',
      title: 'No discovery has completed',
      detail: 'ACP has access, but the source has not yet been inventoried.' })
  }
  return out
}

// ── Connection identity ───────────────────────────────────────────────────────

/** The authorised boundary of the connection, as label/value pairs. A `null` value is the
 *  caller's cue to print NOT_CONFIGURED — the field is never dropped, because "we did not ask
 *  for write access" and "we forgot to show it" look identical once the row is missing. */
export function scopeFacts(source) {
  const s = source || {}
  const monitoring = s.agent === 'continuous' ? 'Continuous'
    : s.agent === 'daily' ? 'Every 24 hours'
      : s.agent ? String(s.agent) : null
  return [
    { label: 'Account', value: s.user || s.account || null },
    { label: 'Root', value: s.folder || s.root || s.site || null },
    { label: 'Access', value: s.access === 'read-only' ? 'Read files · read metadata' : s.access || null },
    // Stated, not inferred. ACP holds read-only scopes on both connectors today; if that ever
    // changes the source row is what has to say so, not this default.
    { label: 'Write-back', value: s.write_back ? 'Enabled' : 'Not enabled' },
    { label: 'Monitoring', value: monitoring },
  ]
}

// ── Formatting ────────────────────────────────────────────────────────────────

export function fmtSize(kb) {
  if (kb == null) return NOT_AVAILABLE
  if (kb < 1024) return `${Math.round(kb)} KB`
  const mb = kb / 1024
  if (mb < 1024) return `${mb.toFixed(mb < 10 ? 1 : 0)} MB`
  return `${(mb / 1024).toFixed(1)} GB`
}

export function fmtDuration(ms) {
  if (ms == null) return NOT_AVAILABLE
  const s = Math.round(ms / 1000)
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ${String(s % 60).padStart(2, '0')}s`
  return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, '0')}m`
}

export function fmtWhen(iso) {
  if (!iso) return NOT_AVAILABLE
  const d = new Date(iso)
  if (isNaN(d.getTime())) return NOT_AVAILABLE
  return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
}

/** Render guard. Anything nullish or the literal string "undefined" (which is how the old
 *  subtitle's template literal stringified a missing field) becomes a stated absence. */
export function orAbsent(v, absent = NOT_AVAILABLE) {
  if (v == null) return absent
  const s = String(v)
  return s === '' || s === 'undefined' || s === 'null' ? absent : s
}

export const fmtCount = (n) => (n == null ? NOT_AVAILABLE : Number(n).toLocaleString())
