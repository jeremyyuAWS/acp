// How the AI Work Inbox is grouped, and what identifies the document on a card.
//
// TWO groupings, both legitimate, and the DEFAULT must match the unit of delivery:
//
//   by-document (default) — certification is per-document. Clearing a file's 3 items makes it
//     certifiable, so grouping by file gives the reviewer a finish line. Grouped by type, a
//     reviewer can work for an hour and complete no document at all.
//   by-type — the same judgement ("is this alt-text pattern acceptable?") repeated across 40
//     files is 8 decisions by type and 225 by file. Real leverage, so it stays as a toggle.
//
// Both modes produce the SAME section shape, so ReviewCenter renders one thing:
//   { key, kind: 'document'|'type', head: {...}, count, groups: [{ label, items }] }
import { groupLabel } from './hitlMeta.js'
import { baseOf, dirOf, reviewType, REVIEW_TYPES } from './reviewCard.js'
import { riskComparator } from './reviewRisk.js'

export const GROUP_MODES = ['document', 'type']
export const DEFAULT_GROUP_MODE = 'document'
const STORAGE_KEY = 'acp.reviewGroupMode'

// Persisted across reloads: a reviewer who works by document should not be handed a by-type
// inbox every morning. localStorage access is wrapped because it throws outright in a Safari
// private window and under some embedded webviews — a preference must never break the inbox.
export function loadGroupMode() {
  try {
    const v = window.localStorage.getItem(STORAGE_KEY)
    return GROUP_MODES.includes(v) ? v : DEFAULT_GROUP_MODE
  } catch {
    return DEFAULT_GROUP_MODE
  }
}

export function saveGroupMode(mode) {
  if (!GROUP_MODES.includes(mode)) return
  try { window.localStorage.setItem(STORAGE_KEY, mode) } catch { /* preference is best-effort */ }
}

// ── Document identity ───────────────────────────────────────────────────────────
// WHICH document is this? A card reading "HTML — Automatic fix applied — verify the result"
// names no document at all, and an estate holding Clinical-FAQ-39.html beside
// Clinical-FAQ-54.html cannot be reviewed from the rule name alone.
//
// Everything here is derived from data that genuinely exists on the row, or supplied by the
// caller from the scan it already loaded. Nothing is invented: a field with no source comes
// back null and the UI omits it rather than printing a plausible-looking guess.
//
// On the DIRECTORY: `hitl_queue.file` is a bare filename for every Drive- and SharePoint-sourced
// document, because scanner._normalize records only {name, id, checksum} — Drive folder
// membership is never captured at discovery, so there is no per-file directory to show. `dir` is
// therefore populated only when the stored name actually carries one (local-corpus scans, and
// any future source that records a path). It renders the moment the data starts arriving; it
// does not fabricate one in the meantime.
export function docIdentity(item, meta = null) {
  const raw = String(item?.file ?? '').trim()
  const m = meta || {}
  // A caller-supplied path (scan_inventory.path) wins over the queue row's bare name — it is
  // the more complete locator for exactly the same document. baseOf/dirOf are reviewCard's,
  // not a second copy: EvidenceCard splits the same reference the same way, and two answers to
  // "which part is the folder" is how one screen shows a path and another shows a bare name.
  const full = String(m.path || raw)
  const name = baseOf(full)
  const dir = dirOf(full) || null
  const dot = name.lastIndexOf('.')
  return {
    // The key everything groups on: the queue row's own `file`, NOT the display name. Two
    // documents could resolve to the same basename via different paths, and collapsing them
    // would put one document's approvals under another's heading.
    key: raw || '(unattributed)',
    file: raw,
    name: name || raw || 'document',
    dir,
    // The full locator as a reviewer would read it. Equals `name` when nothing richer exists.
    path: dir ? `${dir}/${name}` : name || raw,
    ext: dot > 0 ? name.slice(dot + 1).toLowerCase() : null,
    source: m.sourceName || m.source || null,
    department: m.department || m.dept || null,
    owner: m.owner || null,
  }
}

// The breadcrumb the app already uses for a document's location (FileDrawer's "location ·
// Source › Department › file"). Only the segments that exist are emitted, so a document with
// no known source shows its directory alone rather than "Source › Unfiled ›".
export function locationTrail(id) {
  if (!id) return []
  return [id.source, id.department, id.dir].filter(Boolean)
}

// ── Sections ────────────────────────────────────────────────────────────────────

const bySize = (a, b) => b.items.length - a.items.length

// Group items into the uniform section shape. `docMeta` is an optional
// { [file]: { sourceName, department, owner, path } } map — whatever the caller already knows
// about the documents. Absent, cards still name the file; they just say less about where it lives.
export function buildSections(items, { mode = DEFAULT_GROUP_MODE, sortMode = 'critical', docMeta = null } = {}) {
  const list = Array.isArray(items) ? items : []
  const cmp = riskComparator(sortMode)
  return mode === 'type' ? typeSections(list, cmp) : documentSections(list, cmp, docMeta || {})
}

// BY TYPE — the shape this inbox already had: partition by reviewType, then by issue type
// within each. Order = effort: drafted one-click approvals, applied-fix confirmations, then
// the real authoring work.
function typeSections(items, cmp) {
  const byType = { proposal: [], confirm: [], author: [] }
  for (const it of items) byType[reviewType(it)].push(it)
  return ['proposal', 'confirm', 'author']
    .filter((t) => byType[t].length)
    .map((t) => {
      const groups = collect(byType[t], groupLabel, cmp).sort((a, b) => cmp(a.items[0], b.items[0]))
      return { key: `type:${t}`, kind: 'type', head: REVIEW_TYPES[t], count: byType[t].length, groups }
    })
}

// BY DOCUMENT — one section per file, the review types as its groups. The reviewer sees a
// finish line ("clear these 3 and this document can be certified") and still sees what kind of
// work each row is, because a proposal and an applied-fix confirmation are different jobs even
// inside one document.
//
// Documents are ordered by their most urgent item, so the sort control still means something;
// ties break on size, so the file with the most work outstanding leads.
function documentSections(items, cmp, docMeta) {
  const byDoc = new Map()
  for (const it of items) {
    const id = docIdentity(it, docMeta[it?.file])
    if (!byDoc.has(id.key)) byDoc.set(id.key, { id, items: [] })
    byDoc.get(id.key).items.push(it)
  }
  return [...byDoc.values()]
    .map(({ id, items: docItems }) => {
      const order = { proposal: 0, confirm: 1, author: 2 }
      const groups = collect(docItems, (it) => reviewType(it), cmp)
        .sort((a, b) => order[a.label] - order[b.label])
        .map((g) => ({ ...g, type: REVIEW_TYPES[g.label], label: REVIEW_TYPES[g.label].label }))
      return { key: `doc:${id.key}`, kind: 'document', head: id, count: docItems.length, groups }
    })
    .sort((a, b) => cmp(a.groups[0].items[0], b.groups[0].items[0]) || bySize(a, b))
}

// Bucket by a key function, sorting each bucket's items with the active comparator.
function collect(items, keyOf, cmp) {
  const m = new Map()
  for (const it of items) {
    const k = keyOf(it)
    if (!m.has(k)) m.set(k, [])
    m.get(k).push(it)
  }
  return [...m.entries()].map(([label, its]) => ({ label, items: [...its].sort(cmp) }))
}

// The items in a section that are safe to rubber-stamp in bulk: ONLY the deterministic
// applied-fix tier, which ACP already applied and re-validated.
//
// This is why a document section cannot reuse the by-type "Confirm all". A type section IS one
// tier, so sweeping it is the tier's own promise; a document section holds every tier at once,
// and sweeping it would bulk-approve AI proposals and unwritten authoring work that the by-type
// view deliberately refuses to offer a bulk action for. Same button, same document, silently
// different meaning — so the confirmable items are named explicitly here instead.
export function confirmableIn(section) {
  if (!section) return []
  return section.groups.flatMap((g) => g.items).filter((it) => reviewType(it) === 'confirm')
}
