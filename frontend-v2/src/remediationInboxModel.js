// The pure model behind the master/detail Remediation inbox.
//
// Remediation is queue work: select an item, understand it, act, move to the next. This module
// turns a raw finding (from Remediate.buildHumanQueue / dbItemToUi) into the small set of facts a
// queue row and the detail pane need — the remediation LANE, the effort estimate, the resolved
// status, and the "what did ACP do / what must the reviewer do" phrasing — plus the one behaviour
// that makes the queue feel fast: pick the next unresolved item after an action.
//
// Kept pure and free of React so it is unit-testable and the component stays declarative. The lane
// taxonomy is the centre of the design, so it lives here as data, not scattered in JSX.

// ── Remediation lanes ─────────────────────────────────────────────────────────────────────────
// A finding sits in exactly one lane; the lane drives the row's colour rail, the primary action
// label, and the "what ACP did" line. Colours are the six-state remediation vocabulary.
export const LANES = {
  review: {
    key: 'review', rail: 'green', color: '#1f9d6b',
    label: 'Review automatic fix', action: 'Approve fix',
    didLine: 'ACP fixed it — review the change',
  },
  apply: {
    key: 'apply', rail: 'blue', color: '#2f6fed',
    label: 'Apply suggested fix', action: 'Apply fix',
    didLine: 'ACP drafted a fix — apply or reject',
  },
  manual: {
    key: 'manual', rail: 'amber', color: '#c2871a',
    label: 'Manual edit required', action: 'Open in Word',
    didLine: 'Needs a manual edit — guided steps provided',
  },
  recheck: {
    key: 'recheck', rail: 'gray', color: '#8a8f98',
    label: 'Recheck needed', action: 'Recheck',
    didLine: 'Edited — re-scan to confirm it passes',
  },
  blocked: {
    key: 'blocked', rail: 'red', color: '#c0553f',
    label: 'Blocked', action: 'Review block',
    didLine: 'Blocked — cannot be remediated as-is',
  },
}

export const LANE_ORDER = ['review', 'apply', 'manual', 'recheck', 'blocked']

const RESOLVED_STATUSES = new Set(['approved', 'applied', 'accepted', 'rejected', 'resolved', 'verified'])

/** The lane for a finding, from its status first (blocked/recheck win) then its remediation shape. */
export function laneOf(f) {
  const st = String(f?.status || '').toLowerCase()
  if (st === 'blocked' || st === 'rejected') return LANES.blocked
  if (st === 'recheck' || st === 'rechecking' || st === 'scanning') return LANES.recheck
  // A deterministic fix ACP already wrote: the reviewer confirms it (the green lane).
  if (f?.autoApplied || f?.applied || f?.rec?.action === 'auto') return LANES.review
  // ACP drafted a value for a person to approve (the blue lane).
  if (f?.hasProposal || (f?.after != null && f?.after !== '') || f?.aiDraftable) return LANES.apply
  // Nothing ACP can safely write: a person re-authors it in the source app (the amber lane).
  return LANES.manual
}

/** Estimated reviewer effort, in seconds, for a finding — driven by its lane. A review of a
 *  deterministic fix is quick; a manual re-author is the slow one. `f.effortSec` overrides. */
export function effortSecOf(f) {
  if (Number.isFinite(f?.effortSec)) return f.effortSec
  switch (laneOf(f).key) {
    case 'review': return 5
    case 'apply': return 15
    case 'recheck': return 10
    case 'blocked': return 0
    default: return 120 // manual
  }
}

/** A short human effort label, e.g. "~5 sec" or "~2 min". */
export function effortLabel(f) {
  const s = effortSecOf(f)
  if (s <= 0) return '—'
  if (s < 90) return `~${s} sec`
  return `~${Math.round(s / 60)} min`
}

/** Has this finding been acted on? Resolved rows lose their unread emphasis and drop out of the
 *  "next unresolved" walk. A finding is resolved by an explicit status or a recorded decision. */
export function isResolved(f, decisions = {}) {
  if (RESOLVED_STATUSES.has(String(f?.status || '').toLowerCase())) return true
  const d = decisions[f?.id] ?? decisions[f?.file]
  return !!(d && (d.state === 'accepted' || d.state === 'approved' || d.state === 'rejected'))
}

/** The plain-language issue — the dominant text in a row. Strips the "DOCX · " format prefix that
 *  buildHumanQueue puts on the title, and falls back to the criterion name. */
export function issueLabel(f) {
  if (f?.plainIssue) return f.plainIssue
  const t = String(f?.title || '')
  const dot = t.indexOf(' · ')
  const tail = dot >= 0 ? t.slice(dot + 3) : t
  return tail || f?.rule || f?.rule_id || 'Accessibility finding'
}

/** The location line for a row: "Page N" when known, else any provided location, else "". */
export function locationLabel(f) {
  if (f?.page != null && f?.page !== '') return `Page ${f.page}`
  return f?.location || ''
}

/** The compact fact set a queue row renders. Deliberately small — the row communicates only these. */
export function rowModel(f, decisions = {}) {
  const lane = laneOf(f)
  const resolved = isResolved(f, decisions)
  return {
    id: f?.id,
    issue: issueLabel(f),
    file: f?.file || '',
    location: locationLabel(f),
    did: lane.didLine,
    action: lane.action,
    severity: f?.severity || null,
    confidence: f?.confidence ?? null,
    effort: effortLabel(f),
    lane,
    resolved,
    unread: !resolved, // unread-style emphasis for not-yet-reviewed findings
  }
}

// ── Inbox top-bar tabs ──────────────────────────────────────────────────────────────────────────
// Status buckets the toolbar offers. A finding belongs to exactly one, derived from its lane +
// resolved state, so the tab counts always sum to the queue length.
export const TABS = ['all', 'auto-fixed', 'manual', 'blocked', 'resolved']

export function tabOf(f, decisions = {}) {
  if (isResolved(f, decisions)) return 'resolved'
  const k = laneOf(f).key
  if (k === 'blocked') return 'blocked'
  if (k === 'manual') return 'manual'
  return 'auto-fixed' // review + apply + recheck are all "ACP did something" work
}

export function matchesTab(f, tab, decisions = {}) {
  if (tab === 'all') return true
  return tabOf(f, decisions) === tab
}

export function tabCounts(list, decisions = {}) {
  const counts = { all: list.length, 'auto-fixed': 0, manual: 0, blocked: 0, resolved: 0 }
  for (const f of list) counts[tabOf(f, decisions)] += 1
  return counts
}

// ── Sorting ─────────────────────────────────────────────────────────────────────────────────────
const SEV_RANK = { CRITICAL: 0, SERIOUS: 1, MODERATE: 2, MINOR: 3 }

export const SORTS = ['priority', 'document', 'newest', 'fastest']

export function sortQueue(list, sort) {
  const a = [...list]
  switch (sort) {
    case 'document':
      return a.sort((x, y) => String(x.file).localeCompare(String(y.file)) || (x.id - y.id))
    case 'newest':
      return a.sort((x, y) => (y.discoveredAt || y.id || 0) - (x.discoveredAt || x.id || 0))
    case 'fastest':
      return a.sort((x, y) => effortSecOf(x) - effortSecOf(y) || (x.id - y.id))
    case 'priority':
    default:
      return a.sort((x, y) =>
        (SEV_RANK[x.severity] ?? 4) - (SEV_RANK[y.severity] ?? 4) ||
        LANE_ORDER.indexOf(laneOf(x).key) - LANE_ORDER.indexOf(laneOf(y).key) ||
        (x.id - y.id))
  }
}

/** Group findings under their document, preserving the incoming (already-sorted) order of first
 *  appearance. Returns [{ file, items }]. Group-by-document is the default view. */
export function groupByDocument(list) {
  const order = []
  const map = new Map()
  for (const f of list) {
    const key = f.file || '—'
    if (!map.has(key)) { map.set(key, []); order.push(key) }
    map.get(key).push(f)
  }
  return order.map((file) => ({ file, items: map.get(file) }))
}

// ── The behaviour that makes it feel fast: auto-advance ──────────────────────────────────────────
/** The next unresolved finding to select after acting on `currentId`. Walks the given (display)
 *  order from just after the current item, wraps once to the start, and returns the first
 *  unresolved id — or null when nothing is left, which is the "inbox zero" signal. */
export function nextUnresolvedId(orderedList, currentId, decisions = {}) {
  const ids = orderedList.map((f) => f.id)
  const start = ids.indexOf(currentId)
  const n = ids.length
  for (let step = 1; step <= n; step++) {
    const f = orderedList[(start + step) % n] // wraps; when start<0, begins at index 0
    if (f && f.id !== currentId && !isResolved(f, decisions)) return f.id
  }
  return null
}

/** Overall progress for the "0 of 6 resolved" header. */
export function progress(list, decisions = {}) {
  const resolved = list.filter((f) => isResolved(f, decisions)).length
  return { resolved, total: list.length }
}

// ── The auto-applied fixes, as green review-lane rows ────────────────────────────────────────────
/** Normalize a WCAG id ("SC_1_1_1", "WCAG_1.1.1", "1.1.1") to a bare "1.1.1". */
export function normSc(v) {
  return String(v || '').replace(/^(WCAG_?|SC_)/i, '').replace(/_/g, '.')
}

/** Turn ACP's auto-applied fixes (applied_fixes / remediation diffs) into green REVIEW-lane inbox
 *  rows, so review-of-auto-fixes shares the master/detail flow instead of living in a separate
 *  section. Each row is `autoApplied`, so laneOf() puts it in the green lane ("ACP fixed it — review
 *  the change" · Approve fix · ~5 sec). before/after come from the diff, falling back to the applied
 *  value. `nameOf(sc)` supplies the plain criterion name — injected so this file stays dependency-free
 *  (Remediate passes its ITEM_NAME lookup; a test passes a stub). Ids are namespaced `af:…` so they
 *  never collide with the human-queue's numeric/db ids. */
export function autoFixRows(fixes = [], nameOf = (sc) => sc) {
  return fixes.map((a, i) => {
    const sc = normSc(a.sc ?? a.rule_id ?? a.wcag)
    const fmt = (String(a.file || '').split('.').pop() || 'DOC').toUpperCase()
    return {
      id: `af:${a.file || ''}:${sc}:${i}`,
      file: a.file || '',
      page: a.page ?? null,
      ruleId: sc,
      rule_id: sc,
      plainIssue: nameOf(sc),
      title: `${fmt} · ${nameOf(sc)}`,
      before: a.before ?? null,
      after: a.after ?? a.value ?? a.approved_value ?? null,
      autoApplied: true,
      severity: null,
      effortSec: 5,
    }
  })
}
