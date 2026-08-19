// Search for the Review queue (Remediate). The inbox can hold dozens of EvidenceCards; a
// reviewer navigating it needs to jump to "the docx link-purpose ones" or "everything in
// contract.pdf" without scrolling the whole queue. This is the one piece with real logic, so it
// lives here as a pure function the tests can exercise directly rather than through a full mount.
//
// The haystack deliberately spans the three things a reviewer searches by — the FILENAME, the
// WCAG criterion (its number AND its name), and the AI's recommendation text — because any of the
// three is a plausible thing to have in mind. Matching is token-AND and substring: every
// whitespace-separated token must appear somewhere, so "docx 2.4.4" narrows to docx items on
// 2.4.4 and order does not matter. Empty query matches everything (the no-filter state).

// Fields carried on the UI item (dbItemToUi) and on its raw hitl_queue row (_raw) that a reviewer
// might search by. Kept explicit rather than "stringify the whole object" so a new internal field
// can't silently start matching — the searchable surface is a decision, not an accident.
const UI_FIELDS = ['file', 'rule', 'title', 'meta', 'before', 'severity', 'ruleId']
const RAW_FIELDS = ['file', 'rule_id', 'rule_name', 'recommendation', 'proposed_value', 'approved_value']

export function reviewHaystack(item) {
  if (!item) return ''
  const parts = []
  for (const k of UI_FIELDS) {
    const v = item[k]
    if (typeof v === 'string' && v) parts.push(v)
  }
  const raw = item._raw
  if (raw && typeof raw === 'object') {
    for (const k of RAW_FIELDS) {
      const v = raw[k]
      if (typeof v === 'string' && v) parts.push(v)
    }
  }
  return parts.join(' ').toLowerCase()
}

export function matchesReviewQuery(item, query) {
  const q = (query || '').trim().toLowerCase()
  if (!q) return true
  const hay = reviewHaystack(item)
  return q.split(/\s+/).every((tok) => hay.includes(tok))
}

// Convenience for the component: filter a queue, preserving order (priority is already baked into
// the queue's order, so search must not reshuffle it).
export function filterReviewQueue(queue, query) {
  const q = (query || '').trim()
  if (!q) return queue
  return (queue || []).filter((item) => matchesReviewQuery(item, q))
}

// ── Faceted filters (severity + WCAG criterion) ──────────────────────────────────────────────
// Search answers "find the thing I have in mind"; facets answer "show me only the critical ones"
// or "just the 1.1.1s" — the two ways a reviewer chunks a queue of a dozen-plus items. Both read
// off fields already on the item, and both preserve queue order like search.

export function itemSeverity(item) {
  return String((item && (item.severity || (item._raw && item._raw.severity))) || '').toUpperCase()
}

// The WCAG number alone (e.g. "1.1.1"), pulled from the rule label ("1.1.1 — Non-text Content"),
// the ruleId, or the raw row — so grouping is by criterion, not by the specific detector.
export function itemCriterion(item) {
  const s = String((item && (item.rule || item.ruleId || (item._raw && (item._raw.rule_name || item._raw.rule_id)))) || '')
  const m = s.match(/\b\d\.\d+\.\d+\b/)
  return m ? m[0] : ''
}

const _SEV_ORDER = ['CRITICAL', 'SERIOUS', 'MODERATE', 'MINOR']
const _sevRank = (s) => { const i = _SEV_ORDER.indexOf(s); return i < 0 ? 99 : i }

// The filter options actually present in this queue, each with its count — so the UI only offers
// facets that exist and can show "Critical 3". Severities ordered worst-first; criteria numerically.
export function reviewFacets(queue) {
  const sev = {}, crit = {}
  for (const it of (queue || [])) {
    const s = itemSeverity(it); if (s) sev[s] = (sev[s] || 0) + 1
    const c = itemCriterion(it); if (c) crit[c] = (crit[c] || 0) + 1
  }
  return {
    severities: Object.entries(sev).sort((a, b) => _sevRank(a[0]) - _sevRank(b[0])).map(([key, count]) => ({ key, count })),
    criteria: Object.entries(crit).sort((a, b) => a[0].localeCompare(b[0], undefined, { numeric: true })).map(([key, count]) => ({ key, count })),
  }
}

// Compose search + severity + criterion. Null/empty facet = no constraint on that axis.
export function applyReviewFilters(queue, { query = '', severity = null, criterion = null } = {}) {
  let q = filterReviewQueue(queue, query)
  if (severity) q = q.filter((it) => itemSeverity(it) === severity)
  if (criterion) q = q.filter((it) => itemCriterion(it) === criterion)
  return q
}

// ── Grouping (by file) ────────────────────────────────────────────────────────────────────────
// A scan across many documents makes the inbox one long flat list. Grouping by file turns it into
// a per-document view — clear one file at a time — which is how a reviewer actually works an
// estate. Order is preserved: files appear in the order their FIRST item does (the queue is
// already priority-sorted), items keep their order within a file. Each group carries its worst
// severity so the file header can lead with the reason to open it.
export function worstSeverity(items) {
  let best = null, bestRank = 99
  for (const it of (items || [])) {
    const s = itemSeverity(it), r = _sevRank(s)
    if (s && r < bestRank) { best = s; bestRank = r }
  }
  return best
}

export function groupReviewByFile(queue) {
  const order = [], by = new Map()
  for (const it of (queue || [])) {
    const f = (it && it.file) || '—'
    if (!by.has(f)) { by.set(f, []); order.push(f) }
    by.get(f).push(it)
  }
  return order.map((file) => {
    const items = by.get(file)
    return { file, items, count: items.length, worst: worstSeverity(items) }
  })
}
