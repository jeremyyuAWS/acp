// Derive the estate coverage views — funnel, format composition, capability-status breakdown —
// from a scan report's `scope.inventory` (produced by api/estate_inventory.summarize()).
//
// The whole point of this module is the three-denominator honesty: discovered is the widest set,
// assessment-eligible a strict subset, and an unsupported file is NEVER counted as passed. When the
// listing hit its cap, `truncated` is true and discovered is a FLOOR, not a complete count — callers
// must render it as such. Pure and dependency-free so it is node/vitest testable.

export const ASSESSABLE_FORMATS = ['docx', 'pdf', 'pptx', 'xlsx', 'html']

const FORMAT_LABEL = {
  docx: 'Word', pdf: 'PDF', pptx: 'PowerPoint', xlsx: 'Excel', html: 'HTML',
  image: 'Images', av: 'Video / audio', other: 'Other',
}
const STATUS_LABEL = {
  assessable: 'Assessable',
  metadata_only: 'Metadata-only',
  unsupported: 'Unsupported',
  excluded: 'Excluded (ACP output)',
}
const STATUS_ORDER = ['assessable', 'metadata_only', 'unsupported', 'excluded']

/** Is the discovered count a floor (the listing hit its cap) rather than the whole estate? */
export function isTruncated(inv) {
  return !!(inv && inv.truncated)
}

/** assessment-eligible / discovered, as a 0..1 fraction (0 when nothing discovered). */
export function assessablePct(inv) {
  const d = (inv && inv.discovered) || 0
  return d ? ((inv.assessment_eligible || 0) / d) : 0
}

/** Composition rows for the format bars/treemap, largest first. `assessable` flags the green
 *  segments vs the metadata-only/unsupported blind spot. */
export function compositionRows(inv) {
  const by = (inv && inv.by_format) || {}
  return Object.keys(by)
    .map((format) => ({
      format,
      label: FORMAT_LABEL[format] || format,
      count: by[format],
      assessable: ASSESSABLE_FORMATS.includes(format),
    }))
    .sort((a, b) => b.count - a.count || a.format.localeCompare(b.format))
}

// Age bands, in the order a reader scans them — youngest to oldest, then the ones with no date.
// Mirrors AGE_BANDS in api/estate_inventory.py; the keys are the contract between the two.
const AGE_LABEL = {
  lt_1y: 'Under 1 year',
  y1_3: '1–3 years',
  y3_5: '3–5 years',
  gt_5y: 'Over 5 years',
  unknown: 'No date recorded',
}
const AGE_ORDER = ['lt_1y', 'y1_3', 'y3_5', 'gt_5y', 'unknown']

/**
 * How long since each file was last touched — or NULL when this scan does not carry the data.
 *
 * Null, not an empty array and not a row of zeros. `by_age` is absent from every report written
 * before the aggregation shipped, and a missing field is not "no files in any band": rendering
 * zeros there would state, in a bar chart, that an estate nobody measured contains nothing old.
 * The caller shows the panel only when this returns rows.
 *
 * Ordered, never sorted by size: these are ordinal buckets, and re-ordering them by count destroys
 * the only thing a distribution is for. `unknown` is last and is always shown when present, because
 * it is the caveat on every other bar.
 */
export function ageRows(inv) {
  const by = inv && inv.by_age
  if (!by || typeof by !== 'object' || !Object.keys(by).length) return null
  return AGE_ORDER
    .filter((k) => by[k] != null)
    .map((k) => ({ key: k, label: AGE_LABEL[k] || k, value: by[k] }))
}

/**
 * Do the bands account for every discovered file?
 *
 * They are built to (every row lands in exactly one band, including `unknown`), so a mismatch means
 * the two numbers came from different places — a stale report, or a summary written by a version
 * that banded a subset. Worth saying out loud rather than letting a reader add up bars that do not
 * reach the headline count.
 */
export function ageBandsReconcile(inv) {
  const rows = ageRows(inv)
  if (!rows) return true
  const total = rows.reduce((n, r) => n + r.value, 0)
  return total === ((inv && inv.discovered) || 0)
}

/** Capability-status rows in a stable, meaningful order (assessable first, excluded last). */
export function statusRows(inv) {
  const by = (inv && inv.by_status) || {}
  return STATUS_ORDER
    .filter((k) => by[k] != null)
    .map((k) => ({ status: k, label: STATUS_LABEL[k], count: by[k] }))
}

// Drill-down sort orders. size (biggest-first) is the default — the largest files are where
// remediation effort and risk concentrate; shared surfaces externally-visible files first, which
// matter most for a PHI estate. Ties break by name so the order is stable.
export const STATUS_SORTS = ['size', 'shared', 'name']
const SORTERS = {
  size: (a, b) => (b.size || 0) - (a.size || 0) || (a.name || '').localeCompare(b.name || ''),
  name: (a, b) => (a.name || '').localeCompare(b.name || ''),
  shared: (a, b) => (b.shared === true) - (a.shared === true) || (b.size || 0) - (a.size || 0),
}

/** Human file size from a byte count (null → an em dash). */
export function formatBytes(n) {
  if (n == null) return '—'
  if (n < 1024) return `${n} B`
  const u = ['KB', 'MB', 'GB', 'TB']
  let v = n / 1024, i = 0
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++ }
  return `${v < 10 ? v.toFixed(1) : Math.round(v)} ${u[i]}`
}

/** Drill-down for one capability status: the capped file sample from `inventory.samples` — each row
 *  carrying triage metadata {size, owner, shared} — plus the TRUE total from `by_status`, so a caller
 *  renders "showing N of <total>" and never mistakes the sample for the whole bucket. `capped` is true
 *  when the bucket has more files than the sample. `sort` orders the returned sample (default 'size'). */
export function statusFiles(inv, status, sort = 'size') {
  const files = ((inv && inv.samples && inv.samples[status]) || []).map((f) => ({
    id: f.id, name: f.name, format: f.format, label: FORMAT_LABEL[f.format] || f.format,
    size: f.size ?? null, owner: f.owner ?? null, shared: !!f.shared, modified: f.modified ?? null,
  }))
  files.sort(SORTERS[sort] || SORTERS.size)
  const total = (inv && inv.by_status && inv.by_status[status]) || 0
  return { status, sort, files, shown: files.length, total, capped: total > files.length }
}

/** The nine funnel stages. Stages 1–3 come from the inventory (real today); 4–9 come from
 *  `progress` (scan/remediation records) when available, and are null — "pending" — until then.
 *  Every stage carries `of` (the discovered denominator) so a caller can render a proportion. */
export function funnelStages(inv, progress = {}) {
  const discovered = (inv && inv.discovered) || 0
  const eligible = (inv && inv.assessment_eligible) || 0
  const p = progress || {}
  const S = (key, label, value) => ({ key, label, value: value == null ? null : value, of: discovered })
  return [
    S('discovered', 'All files discovered', discovered),
    S('inventoried', 'Readable & inventoried', p.inventoried != null ? p.inventoried : discovered),
    S('eligible', 'Assessment eligible', eligible),
    S('assessed', 'Assessed', p.assessed),
    S('issues', 'Issues detected', p.issues),
    S('rem_eligible', 'Remediation eligible', p.remediation_eligible),
    S('remediated', 'Remediated', p.remediated),
    S('review', 'Human review required', p.human_review),
    S('published', 'Published / ready for release', p.published),
  ]
}

/** Everything a coverage view needs, in one call. */
export function estateModel(inv, progress = {}) {
  return {
    discovered: (inv && inv.discovered) || 0,
    assessmentEligible: (inv && inv.assessment_eligible) || 0,
    assessablePct: assessablePct(inv),
    truncated: isTruncated(inv),
    funnel: funnelStages(inv, progress),
    composition: compositionRows(inv),
    status: statusRows(inv),
    // null when the report predates the aggregation — the panel is then not rendered at all,
    // rather than drawn as zeros.
    age: ageRows(inv),
    ageReconciles: ageBandsReconcile(inv),
  }
}

// ── WHAT WAS ASSESSED, AND WHAT WAS NOT ──────────────────────────────────────────────────────
//
// The headline numbers on the Overview ("12,408 discovered", "7,946 assessed") are two counts of
// two populations, and a reader has no way to check the gap between them. This is that gap, drawn
// as a PARTITION: every discovered file lands in exactly one bucket, the buckets are printed with
// their arithmetic, and the arithmetic either reaches the discovered total or the screen says it
// does not. That is what makes the row of numbers auditable rather than merely plausible.
//
// PRECEDENCE. A file can qualify for more than one reason — an .xlsx flagged for archive review in
// a run that did not select Excel qualifies for both `lifecycle` and `type`. It is counted ONCE,
// under the reason that came first:
//
//     lifecycle  >  type  >  no_test  >  unreadable  >  assessed
//
// Lifecycle wins over document type because it is the earlier decision: a file flagged for
// archive/deletion review is skipped by Assess before the type selection is ever consulted.
//
// The buckets are DISJOINT BY CONSTRUCTION except for that one pair: `no_test` covers exactly the
// formats that are not assessment-eligible, `type` covers only assessment-eligible formats, and
// `unreadable`/`assessed` are counted from the file rows of the run itself. Where the aggregates
// cannot prove disjointness (lifecycle vs type — the inventory reports each as a marginal, and a
// marginal cannot be decomposed) the OVERLAP IS REPORTED rather than assumed away: the sum runs
// past `discovered` and the panel says so. See `ageBandsReconcile` above for the same discipline
// applied to the age bands.
//
// A MISSING INPUT IS NEVER A MEASURED ZERO. Each bucket is `null` when this scan does not carry
// what it needs — `null`, not 0, exactly as `ageRows` returns null rather than a row of zeros.
// A null bucket leaves the sum short, and a short sum is stated as a shortfall; it is never
// silently absorbed into a neighbour, which is the failure that makes a partition look complete
// while it is guessing.
//
// One thing this module deliberately does NOT do: derive any bucket as "discovered minus the
// others". A residual bucket makes the reconciliation trivially true, and a check that cannot fail
// is indistinguishable from a check that passed.

// Display order — the order the design board reads them: the reassuring number first, with the
// exclusions under it, qualifying it.
export const BUCKET_ORDER = ['assessed', 'lifecycle', 'type', 'no_test', 'unreadable']

// Resolution order — which reason wins when a file qualifies for several. Exported so a consumer
// (or a test) can state the rule rather than re-derive it from prose.
export const BUCKET_PRECEDENCE = ['lifecycle', 'type', 'no_test', 'unreadable', 'assessed']

// Wording is load-bearing here. `lifecycle` says RECOMMENDATION, never "archived" or "deleted":
// the system has written a tag proposing a disposition, and nothing has been moved or removed.
// Describing a recommendation as a completed action is the one sentence on this screen that could
// send somebody looking for a file that is still exactly where they left it.
export const BUCKET_META = {
  assessed: {
    label: 'Assessed',
    note: 'a selected document type, no lifecycle flag, and at least one selected criterion applies',
    color: '#3B6D11',
  },
  lifecycle: {
    label: 'Not eligible — lifecycle',
    note: 'carries an archive-or-delete recommendation awaiting a decision — a tag was written, no file was moved or deleted',
    color: '#8a6d1f',
  },
  type: {
    label: 'Not eligible — type',
    note: 'a testable document type this run did not select',
    color: '#6B8FC7',
  },
  no_test: {
    label: 'Not eligible — no test exists',
    note: 'images, audio, video, and formats ACP cannot open for any accessibility criterion',
    color: '#B9B1BD',
  },
  unreadable: {
    label: 'Not eligible — access or error',
    note: 'could not be read when its content was needed',
    color: '#A32D2D',
  },
}

/** A finite, non-negative count, or null. Anything else — undefined, NaN, a string, a negative —
 *  is NOT a measurement and must never be rendered as one. */
function count(v) {
  return typeof v === 'number' && Number.isFinite(v) && v >= 0 ? Math.round(v) : null
}

/**
 * Partition the discovered estate into the five buckets, with the arithmetic exposed.
 *
 * `inv` is the scan's `scope.inventory` (api/estate_inventory.summarize output). `opts` carries the
 * facts the inventory alone cannot know, each optional and each null when unmeasured:
 *
 *   typeNotSelected     — discovery's own count of files dropped for their document type
 *                         (`scope.skipped_out_of_scope`). Wins over the derivation below when
 *                         present: it was counted by the process that did the dropping.
 *   selectedFormats     — the document types this run assessed. An ARRAY of format keys, or `null`
 *                         for "no type narrowing was in force" (frozenScope.scanDocTypes's own
 *                         contract), which is a measured zero rather than a missing answer. Absent
 *                         entirely (undefined) → unknown → the bucket stays null.
 *   lifecycleExcluded   — assessment-eligible files this run skipped because a lifecycle rule
 *                         flagged them (the backend's `lifecycle_eligible_excluded`: the flagged
 *                         subset whose format had a lane, so it never overlaps `no_test`).
 *   lifecycleOverridden — flagged files an authorized override assessed anyway. A FOOTNOTE, never a
 *                         bucket: they were assessed, so they are already inside `assessed`.
 *   unreadable          — files opened and refused (docStatus 'unanalysable').
 *   assessed            — files this run actually opened and scored.
 *
 * Returns null when there is no inventory to partition, so a caller renders nothing at all rather
 * than an empty frame. Otherwise:
 *
 *   { discovered, rows, total, complete, unaccounted, overlap, reconciles, truncated, overridden }
 *
 * `rows` are in BUCKET_ORDER, each {key, label, note, color, value, measured, share}. `total` sums
 * only the MEASURED rows. `unaccounted` is `discovered − total`: positive means files in no bucket,
 * negative means buckets that double-count. `reconciles` is true only when every bucket was
 * measured AND they sum to exactly the discovered total — the one claim the panel may make with a
 * tick.
 */
/**
 * How many discovered files carry ANY applicable accessibility test.
 *
 * Exported so the headline KPI and the bucket reconciliation read one definition rather than two.
 * They sit on the same screen; two derivations of "assessable" that drifted apart would put a
 * number in the header contradicting the partition directly beneath it — the four-denominator
 * defect in a new place.
 *
 * A DIRECT COUNT WINS: discovery records `assessment_eligible` itself. `by_status.assessable` is
 * the older shape and is accepted as a fallback. Null when neither was measured — never 0, which
 * would assert that nothing in the estate can be tested.
 */
export function assessmentEligible(inv) {
  const direct = count(inv && inv.assessment_eligible)
  if (direct != null) return direct
  const byStatus = (inv && inv.by_status) || null
  return byStatus ? count(byStatus.assessable) : null
}

export function reconcileBuckets(inv, opts = {}) {
  const discovered = (inv && inv.discovered) || 0
  if (!discovered) return null
  const o = opts || {}

  // Files with no applicable accessibility test at all. Counted as `discovered − assessment
  // eligible` — the same subtraction api/estate_inventory.funnel_facts makes for the conformance
  // report — and clamped so it can never read negative on a stale or partial summary.
  const byStatus = (inv && inv.by_status) || null
  const eligible = assessmentEligible(inv)
  const noTest = eligible == null ? null : Math.max(0, discovered - eligible)

  // Assessment-eligible files in a document type this run did not select.
  //
  // A DIRECT COUNT WINS over a derivation. Discovery already counts the files its file-type scope
  // dropped (`scope.skipped_out_of_scope`, scanner._list) — that is this bucket, counted by the
  // process that did the dropping. The by_format derivation below is the fallback for scans that
  // carry a frozen criterion scope but no such counter.
  const byFormat = (inv && inv.by_format) || null
  const sel = o.selectedFormats
  let type = count(o.typeNotSelected)
  if (type != null) {
    // nothing further — a measured drop needs no derivation
  } else if (sel === null) {
    // "No narrowing was in force" is a fact about the run, not an absent one: nothing was dropped
    // for its type. Distinct from `undefined`, which is a scan that never recorded its scope.
    type = 0
  } else if (Array.isArray(sel) && byFormat) {
    const keep = new Set(sel)
    type = ASSESSABLE_FORMATS.reduce((n, f) => n + (keep.has(f) ? 0 : (byFormat[f] || 0)), 0)
    // by_format counts ACP's own excluded output under its real format, so this can overshoot the
    // eligible population by the excluded files of a deselected type. Clamped, never negative.
    if (eligible != null) type = Math.min(type, eligible)
  }

  const values = {
    assessed: count(o.assessed),
    lifecycle: count(o.lifecycleExcluded),
    type,
    no_test: noTest,
    unreadable: count(o.unreadable),
  }

  const rows = BUCKET_ORDER.map((key) => {
    const v = values[key]
    return {
      key,
      label: BUCKET_META[key].label,
      note: BUCKET_META[key].note,
      color: BUCKET_META[key].color,
      value: v,
      measured: v != null,
      // A percentage never travels without its denominator — the panel renders this as
      // "x% of <discovered>". An unmeasured bucket has NO share; it does not have a share of zero.
      share: v == null ? null : v / discovered,
    }
  })

  const measured = rows.filter((r) => r.measured)
  const total = measured.reduce((n, r) => n + r.value, 0)
  const complete = measured.length === rows.length
  const unaccounted = discovered - total
  return {
    discovered,
    rows,
    total,
    complete,
    unaccounted,
    overlap: unaccounted < 0,
    reconciles: complete && unaccounted === 0,
    truncated: isTruncated(inv),
    // Flagged files assessed anyway under an authorized override. Reported beside the lifecycle
    // row so the pair reads "343 held back, 9 let through", never as a sixth bucket.
    overridden: count(o.lifecycleOverridden),
  }
}

/** Do the buckets account for every discovered file? Mirrors `ageBandsReconcile`: true when there
 *  is nothing to check, so a caller's warning fires on a real mismatch and not on absence. */
export function bucketsReconcile(inv, opts = {}) {
  const rec = reconcileBuckets(inv, opts)
  return rec ? rec.reconciles : true
}

/** The sum, written out: "7,946 + 343 + 3,092 + 980 + 47". Only the measured buckets appear —
 *  printing a `0` for an unmeasured one is the lie this module is arranged against. Null when
 *  there is nothing measured to add up. */
export function bucketEquation(rec) {
  if (!rec) return null
  const measured = rec.rows.filter((r) => r.measured)
  if (!measured.length) return null
  return measured.map((r) => r.value.toLocaleString()).join(' + ')
}
