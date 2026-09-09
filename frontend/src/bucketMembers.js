// Which rows landed in a breakdown bucket, for the drill-down under the bars.
//
// THE POINT OF THIS FILE is that a drill-down list and the bar above it must never disagree. The
// tempting shape — let the panel re-derive membership with its own copy of the rule — is how a bar
// reading 412 comes to sit above a list of 400: two implementations of one rule, drifting. So every
// function here returns COUNT AND MEMBERS FROM THE SAME PASS, and the panel renders the count it
// was handed rather than one it computed.
//
// The one place that guarantee cannot hold is BY FILE TYPE when the estate inventory is present:
// those counts are computed SERVER-side over the whole listing (`estate_inventory.summarize()`),
// and the browser only holds the rows the inventory route returned. `formatMembers` therefore
// reports how many it could match, and the panel SAYS when that is fewer than the bar — see
// DiscoveryResults.jsx. An unexplained short list is the failure this whole file exists to avoid.
//
// React-free, so vitest can exercise it without a DOM.

import { formatBucketOf } from './discoveryRecommendations.js'

/** The display name for a row, from whichever field the source populated. */
export function rowName(row) {
  if (!row || typeof row !== 'object') return 'Name not recorded'
  return row.file || row.name || row.filename || row.path || 'Name not recorded'
}

/** The path/folder for a row, or '' — shown under the name and searched alongside it. */
export function rowPath(row) {
  if (!row || typeof row !== 'object') return ''
  const p = row.path || row.folder || row.parent || row.location || ''
  return typeof p === 'string' ? p : ''
}

/**
 * Rows whose name or path contains `query`, case-insensitively.
 *
 * An empty or whitespace-only query returns the rows unchanged rather than none: an empty search
 * box means "no filter", and returning [] there reads to a user as "this bucket is empty".
 */
export function searchRows(rows, query) {
  if (!Array.isArray(rows)) return []
  const q = String(query || '').trim().toLowerCase()
  if (!q) return rows
  return rows.filter((r) => `${rowName(r)} ${rowPath(r)}`.toLowerCase().includes(q))
}

/**
 * Group `rows` by `keyOf`, returning a Map of bucket key -> rows in input order.
 *
 * Used by the distributions to attach members during the pass that counts them, so a bucket's
 * `count` and its member list are two readings of one traversal.
 */
export function groupBy(rows, keyOf) {
  const out = new Map()
  if (!Array.isArray(rows)) return out
  for (const r of rows) {
    const k = keyOf(r)
    if (k == null) continue
    if (!out.has(k)) out.set(k, [])
    out.get(k).push(r)
  }
  return out
}

/**
 * Rows matching each FILE TYPE bucket, keyed by bucket key.
 *
 * Prefers the inventory rows (the whole listing) over the scanned `files`, because the grey
 * buckets — images, video, other — are exactly the ones `files` structurally cannot contain: only
 * assessable formats are ever opened and scored. Passing `files` here would make "Other" open to
 * an empty list on precisely the estates where it is largest.
 */
export function formatMembers(invRows, files) {
  const source = Array.isArray(invRows) && invRows.length ? invRows
    : (Array.isArray(files) ? files : [])
  return groupBy(source, formatBucketOf)
}
