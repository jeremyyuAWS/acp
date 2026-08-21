// SharePoint's Content Type, surfaced when the source actually returns one.
//
// The one field of "read SharePoint-native metadata as a rule input" (docs/sharepoint-gaps.md)
// this build reads today. Best-effort and UNVERIFIED against a live Graph tenant — see
// scanner._sp_content_type's own header for what "unverified" means here and why the whole
// pipeline is built to be safe either way.
//
// NOT the department/tag classification classificationData.js gates. Content Type is a SharePoint
// column an operator's library may or may not use, named whatever the library's own convention
// calls it ("Policy", "Contract", "HR Record"...) — real when present, but not the same axis as
// "which department owns this" or "is this under legal hold". Conflating the two would be exactly
// the kind of invention this codebase spent tonight removing: a real signal wearing the label of a
// different, unmeasured one.

import { reconcile } from './discoveryRecommendations.js'

const NOT_RETURNED = Symbol('not-returned')

/** Did SharePoint return a content type for ANY row? False (not absent-vs-empty — genuinely
 *  false) means either the source isn't SharePoint, the tenant's Graph response didn't carry it,
 *  or the enrichment circuit-breaker gave up (scanner._sp_enrich_content_types) — this module
 *  cannot and does not distinguish those, because none of them is a claim worth making to a
 *  reader; "we don't have this" covers all three honestly. */
export function hasContentTypeData(files) {
  return Array.isArray(files) && files.some((f) => f && typeof f.content_type === 'string' && f.content_type.trim() !== '')
}

/**
 * Every discovered file, grouped by SharePoint Content Type, summing to the file count.
 *
 * Returns null when NOTHING in this estate carries one — the panel this feeds must not render a
 * chart of one grey "not returned" bar over an estate where the feature never fired at all.
 *
 * Rows with no content type are their OWN bucket rather than dropped, so the reconciliation stays
 * a true partition: some documents WERE classified by the source, some were not, and both counts
 * are real. Grey, and last — it is the gap, not a category the library defined.
 */
export function contentTypeBreakdown(files, population = 'files discovered') {
  if (!hasContentTypeData(files)) return null
  const counts = new Map()
  files.forEach((f) => {
    const ct = f && typeof f.content_type === 'string' && f.content_type.trim() !== '' ? f.content_type.trim() : NOT_RETURNED
    counts.set(ct, (counts.get(ct) || 0) + 1)
  })
  const buckets = [...counts.entries()]
    .sort((a, b) => (a[0] === NOT_RETURNED ? 1 : b[0] === NOT_RETURNED ? -1 : b[1] - a[1]))
    .map(([label, count]) => ({
      key: label === NOT_RETURNED ? '__none__' : label,
      label: label === NOT_RETURNED ? 'Not returned by the source' : label,
      count,
      known: label !== NOT_RETURNED,
    }))
  return reconcile(buckets, files.length, population)
}
