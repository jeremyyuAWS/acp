// Reading the per-file discover inventory, completely or not at all.
//
// The lifecycle columns the Discovery results screen needs (`lifecycle_status`,
// `lifecycle_rule_id`, `lifecycle_reason`) are not on `GET /scans/{id}` — it selects from
// `file_records`, which has no such columns. They live on `scan_inventory` and come back from
// `GET /scans/{id}/inventory`, which is PAGINATED (limit <= 1000).
//
// That pagination is the whole reason this module exists, and the reason it is pure and
// fetch-injected rather than an effect inlined in a component:
//
//   A PARTIAL READ IS A FAILED READ. Counting recommendations over page one of a 30k-file estate
//   produces a number that is correct about the page and false about the estate — the
//   count-without-its-population defect, arriving as a reassuring small number nobody questions.
//   So `loadDiscoveryInventory` either returns every row the route says exists, or it returns
//   `null`. There is no partial success.
//
//   AND A FAILED READ IS NOT EVIDENCE. `null` means "we do not know which files are tagged",
//   never "no file is tagged". The caller renders NOTHING on `null` — it must not fall back to
//   the un-merged file rows and report zero recommendations, because a 403 and a clean estate
//   would then look identical.
//
// React-free so vitest can exercise the paging and the failure path without a DOM or a mock.

/** Route cap. Matches `limit: int = Query(200, ge=1, le=1000)` on /scans/{id}/inventory. */
export const PAGE_LIMIT = 1000

/** How many pages we will ask for before giving up. 30 pages x 1000 covers the 30k-file estate the
 *  inventory was sized for; beyond that we return null rather than hammer the route, because an
 *  answer we stopped collecting is not an answer. */
export const MAX_PAGES = 30

/**
 * Every inventory row for a scan, or null.
 *
 * `fetchPage(scanId, { offset, limit })` is injected — api.js `getScanInventory` in the app, a
 * plain function in tests. Any rejection, any malformed response, any short read: null.
 */
export async function loadDiscoveryInventory(scanId, fetchPage, { limit = PAGE_LIMIT } = {}) {
  if (!scanId || typeof fetchPage !== 'function') return null
  const rows = []
  let total = null
  try {
    for (let page = 0; page < MAX_PAGES; page++) {
      const res = await fetchPage(scanId, { offset: rows.length, limit })
      if (!res || !Array.isArray(res.rows)) return null
      // `total` is the route's own count of the population. Without it we cannot tell a complete
      // read from a truncated one, so we do not claim one.
      const t = Number(res.total)
      if (!Number.isFinite(t) || t < 0) return null
      if (total == null) total = t
      // The population moved under us (a re-scan mid-read). Neither answer is now whole.
      else if (t !== total) return null
      rows.push(...res.rows)
      if (rows.length >= total) break
      // A page that returned nothing while rows are still owed cannot make progress; looping
      // would spin, and returning what we have would be the partial read this module refuses.
      if (res.rows.length === 0) return null
    }
  } catch {
    return null      // network, auth, 404 for another account's scan — all "we do not know"
  }
  return rows.length === total ? { rows, total } : null
}

/** The lifecycle + classification fields, keyed by the filename they belong to.
 *
 *  `content_type` rides along because it comes from the SAME paginated read — building a second
 *  fetch cycle just to carry one more column would duplicate everything this module exists to get
 *  right (the all-or-nothing read, the page cap, the failure-is-not-evidence rule) for no reason. */
export function lifecycleIndex(rows) {
  const byFile = new Map()
  ;(rows || []).forEach((r) => {
    if (!r || !r.file) return
    byFile.set(String(r.file), {
      lifecycle_status: r.lifecycle_status ?? null,
      lifecycle_rule_id: r.lifecycle_rule_id ?? null,
      lifecycle_reason: r.lifecycle_reason ?? null,
      // A human's reasoned disagreement with the rule above (lifecycle rules #8) — a SEPARATE
      // fact from lifecycle_status/lifecycle_rule_id/lifecycle_reason, merged independently
      // below for the same reason content_type is: it can be present or absent regardless of
      // whether the rule pass matched anything.
      lifecycle_override_reason: r.lifecycle_override_reason ?? null,
      lifecycle_overridden_by: r.lifecycle_overridden_by ?? null,
      lifecycle_overridden_at: r.lifecycle_overridden_at ?? null,
      path: r.path ?? null,
      content_type: r.content_type ?? null,
    })
  })
  return byFile
}

/**
 * The scan's file rows with their lifecycle columns attached.
 *
 * Returns `files` UNCHANGED when there is no inventory to merge — so a caller that forgets to
 * guard still gets the absent-not-zero behaviour rather than a screen full of measured zeros.
 *
 * A file with no inventory row is left WITHOUT a lifecycle field on purpose. It is not "Active":
 * nobody looked it up. `recommendationBucketOf` sorts those into their own `unknown` bucket, so
 * the reconciliation stays a true partition instead of quietly promoting an unread file to
 * "no recommendation".
 */
export function mergeLifecycle(files, inventory) {
  if (!Array.isArray(files) || !inventory || !Array.isArray(inventory.rows)) return files
  const byFile = lifecycleIndex(inventory.rows)
  if (byFile.size === 0) return files
  return files.map((f) => {
    const hit = byFile.get(String(f.file))
    if (!hit) return f
    // TWO INDEPENDENT FIELDS, merged independently. This used to bail out of the WHOLE merge —
    // including content_type — whenever lifecycle_status was null, which is exactly the bug this
    // module's own doc comment warns against one field over: a row with a real content type and no
    // lifecycle rule match would have LOST its content type here, for a reason that has nothing to
    // do with content type. lifecycle_status and content_type come from different sources
    // (a rule pass vs. a Graph read) and must be free to arrive apart.
    const out = { ...f, path: f.path ?? hit.path ?? undefined }
    if (hit.lifecycle_status != null) {
      out.lifecycle_status = hit.lifecycle_status
      out.lifecycle_rule_id = hit.lifecycle_rule_id
      out.lifecycle_reason = hit.lifecycle_reason
    }
    if (hit.lifecycle_overridden_at != null) {
      out.lifecycle_override_reason = hit.lifecycle_override_reason
      out.lifecycle_overridden_by = hit.lifecycle_overridden_by
      out.lifecycle_overridden_at = hit.lifecycle_overridden_at
    }
    if (hit.content_type != null) out.content_type = hit.content_type
    return out
  })
}
