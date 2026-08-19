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
  }
}
