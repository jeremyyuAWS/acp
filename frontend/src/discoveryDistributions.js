// Estate-level distributions for the completed Discovery dashboard.
//
// Three views of the inventory that file-type and recommendation panels do not give:
//   · AGE   — when were files last modified? staleness is the first question archival rules ask.
//   · SIZE  — how big are they? a 100 MB estate with 500 files reads differently from one with 50k.
//   · FOLDER — where do they live? a single department's folder dominating the estate is signal.
//
// These are computed from the raw inventory rows (all discovered files, including inventory-only),
// not from the merged estateFiles array — the size/date/folder columns live on scan_inventory, not
// on file_records, so they arrive via the inventory prop (the paginated read).
//
// RULES carried over from discoveryRecommendations.js:
//   · A missing answer is never a measured zero. When a field is null/missing, the row goes to an
//     explicit "Unknown" bucket rather than being silently dropped or attributed to the wrong bucket.
//   · Every distribution returns { buckets, total, sum, balanced, population } so the caller can
//     print the total and the sum beside each other. A screen that renders a partial distribution
//     without saying so is worse than one that admits it.
//   · React-free so vitest can exercise the logic without a DOM.

const NOW_YEAR = new Date().getFullYear()

// ── Age ───────────────────────────────────────────────────────────────────────

/** Age bucket boundaries in whole years (exclusive upper bound). */
const AGE_BUCKETS = [
  { key: 'lt1',   label: 'Under 1 year',  maxYears: 1 },
  { key: '1to3',  label: '1 – 3 years',   maxYears: 3 },
  { key: '3to5',  label: '3 – 5 years',   maxYears: 5 },
  { key: 'gt5',   label: 'Over 5 years',  maxYears: Infinity },
]

function ageYears(dateStr) {
  if (!dateStr) return null
  const ms = Date.parse(dateStr)
  if (!Number.isFinite(ms)) return null
  const years = (Date.now() - ms) / (365.25 * 24 * 3600 * 1000)
  return years < 0 ? 0 : years
}

/**
 * Bucket inventory rows by last-modified age.
 *
 * Prefers `source_modified` (the file's own timestamp at the source) over `created_at` (the
 * discovery record — a field ACP writes, not the file). Either being present is enough: the caller
 * wants to know how old the CONTENT is, and `source_modified` is the better answer when it exists.
 * Falls back to `created_at` only when `source_modified` is null/missing.
 *
 * Returns null when no rows have any date field (not even one) — that is "we do not know the age
 * distribution" rather than "everything is Unknown".
 */
export function ageBucketDistribution(rows) {
  if (!Array.isArray(rows) || rows.length === 0) return null

  const counts = Object.fromEntries(AGE_BUCKETS.map((b) => [b.key, 0]))
  let unknown = 0
  let anyDate = false

  for (const r of rows) {
    const dateStr = r.source_modified || r.created_at || null
    const years = ageYears(dateStr)
    if (years === null) { unknown++; continue }
    anyDate = true
    const bucket = AGE_BUCKETS.find((b) => years < b.maxYears)
    if (bucket) counts[bucket.key]++
    else unknown++
  }

  if (!anyDate) return null

  const buckets = AGE_BUCKETS.map((b) => ({ key: b.key, label: b.label, count: counts[b.key] }))
  if (unknown > 0) buckets.push({ key: 'unknown', label: 'No date recorded', count: unknown })

  const total = rows.length
  const sum = buckets.reduce((n, b) => n + b.count, 0)
  return {
    buckets: buckets.filter((b) => b.count > 0),
    total,
    sum,
    balanced: sum === total,
    population: `${total.toLocaleString()} discovered files`,
  }
}

// ── Size ──────────────────────────────────────────────────────────────────────

const SIZE_BUCKETS = [
  { key: 'tiny',   label: 'Under 100 KB',   maxKb: 100 },
  { key: 'small',  label: '100 KB – 1 MB',  maxKb: 1_024 },
  { key: 'medium', label: '1 – 10 MB',      maxKb: 10_240 },
  { key: 'large',  label: 'Over 10 MB',     maxKb: Infinity },
]

/**
 * Bucket inventory rows by file size in KB.
 *
 * Returns null when no row carries a size_kb value — for sources or scan versions that did not
 * record file sizes, rendering the panel would falsely imply the estate is empty.
 */
export function sizeBucketDistribution(rows) {
  if (!Array.isArray(rows) || rows.length === 0) return null

  const counts = Object.fromEntries(SIZE_BUCKETS.map((b) => [b.key, 0]))
  let unknown = 0
  let anySize = false

  for (const r of rows) {
    const kb = r.size_kb ?? r._sizeKb ?? null
    if (kb === null || !Number.isFinite(Number(kb))) { unknown++; continue }
    anySize = true
    const n = Number(kb)
    const bucket = SIZE_BUCKETS.find((b) => n < b.maxKb)
    if (bucket) counts[bucket.key]++
    else unknown++
  }

  if (!anySize) return null

  const buckets = SIZE_BUCKETS.map((b) => ({ key: b.key, label: b.label, count: counts[b.key] }))
  if (unknown > 0) buckets.push({ key: 'unknown', label: 'Size not recorded', count: unknown })

  const total = rows.length
  const sum = buckets.reduce((n, b) => n + b.count, 0)
  return {
    buckets: buckets.filter((b) => b.count > 0),
    total,
    sum,
    balanced: sum === total,
    population: `${total.toLocaleString()} discovered files`,
  }
}

// ── Folder ────────────────────────────────────────────────────────────────────

/**
 * Top-N folders by file count, with the remainder collapsed into a single "Other" bucket.
 *
 * Uses `parent_folder` — the immediate parent path the source returned. When `parent_folder` is
 * null/missing the row goes to a "Root / unknown" bucket; that is the source's answer (some files
 * are genuinely at the root, and some sources do not return a parent path), not a gap in the scan.
 *
 * Returns null when no row carries a parent_folder value AND there are no root files (i.e. no
 * useful folder information at all).
 */
export function folderDistribution(rows, topN = 10) {
  if (!Array.isArray(rows) || rows.length === 0) return null

  const tally = new Map()
  let anyFolder = false

  for (const r of rows) {
    const folder = (r.parent_folder && String(r.parent_folder).trim()) || null
    if (folder) anyFolder = true
    const key = folder || '(root / no folder)'
    tally.set(key, (tally.get(key) || 0) + 1)
  }

  if (!anyFolder) return null

  const sorted = [...tally.entries()].sort((a, b) => b[1] - a[1])
  const top = sorted.slice(0, topN)
  const rest = sorted.slice(topN)
  const otherCount = rest.reduce((n, [, c]) => n + c, 0)

  const buckets = top.map(([key, count]) => ({ key, label: key, count }))
  if (otherCount > 0) buckets.push({ key: '__other__', label: `Other (${rest.length} folders)`, count: otherCount })

  const total = rows.length
  const sum = buckets.reduce((n, b) => n + b.count, 0)
  return {
    buckets,
    total,
    sum,
    balanced: sum === total,
    population: `${total.toLocaleString()} discovered files`,
  }
}
