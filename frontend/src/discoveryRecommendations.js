// Discovery results — the numbers behind the "Discovery results" screen, as pure functions.
//
// Discovery writes RECOMMENDATIONS. It does not archive, move, trash or delete anything: the
// backend rule pass (`api/handlers._evaluate_discover_lifecycle_rules`) sets a per-file
// `lifecycle_status` of "Archive Candidate" / "Delete Candidate" and records WHICH rule produced
// it and WHY, and the Drive action stays behind a separate approval/execute path. Every label in
// this module is therefore a review label — "tagged for archive review", never "archived".
//
// THREE RULES HOLD THROUGHOUT, and they are why this is a separate React-free module:
//
//   1. A MISSING ANSWER IS NEVER A MEASURED ZERO. Every function that cannot be computed from its
//      input returns `null`, and the caller omits the section. `GET /scans/{id}` does not carry
//      the lifecycle columns today (they live on `scan_inventory`, exposed by
//      `GET /scans/{id}/inventory`), so `hasLifecycleData` is false on a real scan and the whole
//      recommendation surface is ABSENT rather than reporting "0 tagged for archive review" —
//      which is a claim about the estate, made from a field nobody read.
//   2. EVERY COUNT CARRIES ITS POPULATION. Each reconciliation returns `{ buckets, total, sum,
//      balanced, population }`; the caller prints the population and the sum, so a reader can add
//      the rows up and check.
//   3. THE BUCKETS PARTITION. `formatBucketOf` and `recommendationBucketOf` each return exactly
//      one bucket per row, so the counts sum to the population — `balanced` is the assertion, and
//      it is rendered, not merely tested.
//
// Nothing here invents a figure. A rule name that was not recorded reads as "not recorded"; it is
// never guessed from the action.

// ── Absence ───────────────────────────────────────────────────────────────────
// One definition of "assessment eligible", shared with the bucket reconciliation on the same
// screen. Two derivations that drifted apart would put a header number contradicting the partition
// directly beneath it.
import { assessmentEligible } from './estateFunnel.js'

export const NOT_RECORDED = 'not recorded'

// ── File-format buckets ───────────────────────────────────────────────────────
//
// Mirrors api/estate_inventory._format_of so the screen groups files the way the backend's own
// estate summary does. `assessable: false` types are inventoried but carry no WCAG test — they
// stay VISIBLE with that said out loud, because a type that disappears from a compliance screen
// reads as one that passed.

const SUPPORTED_EXT = {
  docx: 'docx', doc: 'other', pdf: 'pdf', pptx: 'pptx', ppt: 'other',
  xlsx: 'xlsx', xls: 'other', html: 'html', htm: 'html',
}
const IMAGE_EXT = new Set(['png', 'jpg', 'jpeg', 'gif', 'bmp', 'tif', 'tiff', 'webp', 'svg', 'heic', 'ico'])
const AV_EXT = new Set(['mp4', 'mov', 'avi', 'mkv', 'webm', 'mp3', 'wav', 'm4a', 'aac', 'flac', 'ogg'])

/** Every format bucket, in the order the screen lists them: [key, label, carries a WCAG test]. */
export const FORMAT_BUCKETS = [
  ['docx', 'Word', true],
  ['pdf', 'PDF', true],
  ['xlsx', 'Excel', true],
  ['pptx', 'PowerPoint', true],
  ['html', 'Web pages', true],
  ['image', 'Images', false],
  ['av', 'Video / audio', false],
  ['other', 'Other', false],
]
const FORMAT_LABEL = new Map(FORMAT_BUCKETS.map(([k, label]) => [k, label]))

export const formatLabel = (key) => FORMAT_LABEL.get(key) || 'Other'

/** The extension of a row's filename, lower-cased and without the dot, or ''. */
const extOf = (row) => {
  const name = String((row && (row.file || row.name || row.path)) || '')
  const i = name.lastIndexOf('.')
  return i > 0 ? name.slice(i + 1).toLowerCase() : ''
}

/**
 * The single format bucket a row lands in. Reads the filename extension first (which every row
 * carries) and falls back to the annotated `type` — never both, so one row can only be counted
 * once.
 */
export function formatBucketOf(row) {
  const ext = extOf(row) || String((row && row.type) || '').toLowerCase()
  if (SUPPORTED_EXT[ext] && SUPPORTED_EXT[ext] !== 'other') return SUPPORTED_EXT[ext]
  if (IMAGE_EXT.has(ext)) return 'image'
  if (AV_EXT.has(ext)) return 'av'
  return 'other'
}

// ── Could not be read ─────────────────────────────────────────────────────────
//
// A real scan does not set SIM's `locked` flag: a file the engine could not open comes back as
// status 'error' with no score. Both are the same fact to a reviewer, and Discover already treats
// them as one bucket.

export const isUnreadable = (row) => !!(row && (row.locked || row.status === 'error'))

/** The recorded reason one row could not be read, or null. Never invented — see
 *  fileErrorReason.js, where guessing "unreadable" once misdirected a whole investigation. */
export const defaultReasonOf = (row) =>
  (row && (row.openIssue || row.error_reason || row.errorReason)) || null

/**
 * Why the unreadable files could not be read, as buckets that sum to the unreadable count.
 *
 * Returns null when `files` is not an array — nothing was read, so nothing is claimed. Returns an
 * empty-bucket result with `total: 0` when the rows ARE present and none failed: that zero is
 * measured.
 *
 * Rows with no recorded reason are their own bucket rather than being dropped, so the sum still
 * equals the total and a gap in the record is visible as a gap.
 */
export function unreadableReasons(files, reasonOf = defaultReasonOf) {
  if (!Array.isArray(files)) return null
  const rows = files.filter(isUnreadable)
  const counts = new Map()
  rows.forEach((r) => {
    const reason = reasonOf(r)
    const key = reason ? String(reason) : NOT_RECORDED
    counts.set(key, (counts.get(key) || 0) + 1)
  })
  const buckets = [...counts.entries()]
    // Recorded reasons first, biggest first; "not recorded" always last — it is the gap, not a cause.
    .sort((a, b) => (a[0] === NOT_RECORDED ? 1 : b[0] === NOT_RECORDED ? -1 : b[1] - a[1]))
    .map(([reason, count]) => ({ reason, count, recorded: reason !== NOT_RECORDED }))
  return reconcile(buckets, rows.length, 'files that could not be read')
}

// ── Lifecycle recommendations ─────────────────────────────────────────────────

const LIFECYCLE_FIELDS = ['lifecycle_status', 'lifecycleStatus']

/** The recorded lifecycle status for a row, or null when the row carries no lifecycle field at
 *  all. `null` and `'Active'` are DIFFERENT: one is a field nobody read, the other is a rule pass
 *  that ran and matched nothing. */
export function lifecycleStatusOf(row) {
  if (!row) return null
  for (const f of LIFECYCLE_FIELDS) {
    const v = row[f]
    if (v != null && String(v).trim() !== '') return String(v).trim()
  }
  return null
}

/**
 * Did the lifecycle rule pass reach this screen at all?
 *
 * False means the recommendation surface must be OMITTED, not zeroed. Today this is false for a
 * real scan: `GET /scans/{id}` selects from `file_records`, which has no lifecycle columns —
 * they are on `scan_inventory`, returned by `GET /scans/{id}/inventory`.
 */
export const hasLifecycleData = (files) =>
  Array.isArray(files) && files.some((f) => lifecycleStatusOf(f) != null)

/** The recommendation buckets, in the order the reconciliation lists them. Every discovered file
 *  lands in exactly one. `tone` is a rendering hint, not a verdict. */
export const RECOMMENDATION_BUCKETS = [
  ['unreadable', 'Could not be read — no recommendation was produced', 'fail'],
  ['delete', 'Tagged for deletion review', 'del'],
  ['archive', 'Tagged for archive review', 'arch'],
  ['actioned', 'Already actioned by an approved rule', 'muted'],
  ['exempt', 'Exempt from lifecycle rules', 'muted'],
  // Not "no recommendation": no lifecycle row came back for this file, so nobody looked. Its own
  // bucket rather than a silent promotion into `none`, which would report an unread file as a
  // checked one and still add up.
  ['unknown', 'No lifecycle record was read for these', 'muted'],
  ['none', 'No recommendation — stays in the estate', 'ok'],
]
const RECOMMENDATION_LABEL = new Map(RECOMMENDATION_BUCKETS.map(([k, label]) => [k, label]))
export const recommendationLabel = (key) => RECOMMENDATION_LABEL.get(key) || key

/** The short review label a tag carries on screen. "review", always — discovery recommends. */
export const REVIEW_TAG = { archive: 'archive review', delete: 'deletion review' }

/**
 * The single recommendation bucket a row lands in. Precedence is top-down and deliberate:
 * a file that could not be read has no recommendation to show, whatever else is on the row.
 *
 * "Archived" / "Deleted" are states an APPROVED execution reached, not recommendations, so they
 * get their own bucket instead of being reported as "tagged for review" (which would understate
 * what already happened to the file).
 */
export function recommendationBucketOf(row) {
  if (isUnreadable(row)) return 'unreadable'
  const recorded = lifecycleStatusOf(row)
  // No status on the row at all — the inventory read did not cover this file. 'none' would claim
  // a rule pass looked at it and found nothing, which is a different fact and the reassuring one.
  if (recorded == null) return 'unknown'
  const status = recorded.toLowerCase()
  if (status === 'exempted') return 'exempt'
  if (status === 'archived' || status === 'deleted') return 'actioned'
  if (status.includes('delete')) return 'delete'
  if (status.includes('archive')) return 'archive'
  // Every other recorded status ('Active', and 'Failed' — a rule action that did not complete)
  // leaves no recommendation standing against the file.
  return 'none'
}

/** The rule that produced a recommendation, or null when the record does not name one.
 *
 *  Three reads, all of RECORDED data, never a guess: an explicit name field, the policy list
 *  joined on `lifecycle_rule_id`, then the name the backend quoted into its own reason string
 *  ("matched archive rule 'Legacy clinical policies'"). */
export function ruleNameOf(row, policies = null) {
  if (!row) return null
  const explicit = row.lifecycle_rule_name || row.lifecycleRuleName
  if (explicit) return String(explicit)
  const id = row.lifecycle_rule_id || row.lifecycleRuleId
  if (id && Array.isArray(policies)) {
    const hit = policies.find((p) => p && (p.policy_id === id || p.id === id))
    if (hit && hit.name) return String(hit.name)
  }
  const reason = lifecycleReasonOf(row)
  const quoted = reason && reason.match(/rule '([^']+)'/)
  return quoted ? quoted[1] : null
}

/** The reason the rule pass recorded for this row, verbatim, or null. */
export function lifecycleReasonOf(row) {
  const v = row && (row.lifecycle_reason || row.lifecycleReason)
  return v != null && String(v).trim() !== '' ? String(v).trim() : null
}

/** True when the recorded reason says a second rule also matched — the case the backend resolves
 *  by KEEPING the safer recommendation and leaving the decision to a human. */
export const isConflicted = (row) => /also matched/i.test(lifecycleReasonOf(row) || '')

/** A human's recorded override of THIS row's recommendation (lifecycle rules #8), or null when
 *  none was recorded. Requires a reason — an override record with no reason is not a recorded
 *  override, the same rule W4's disposition.js normalizeDisposition applies. */
export function overrideOf(row) {
  if (!row) return null
  const reason = (row.lifecycle_override_reason || '').toString().trim()
  if (!reason) return null
  return {
    reason,
    actor: row.lifecycle_overridden_by || null,
    at: row.lifecycle_overridden_at || null,
  }
}

/**
 * The recommendation table rows, newest concern first: deletion before archive (the less
 * reversible recommendation is the one to read first), then by filename.
 *
 * Returns null when no row carries lifecycle data — an empty table and an unread field must not
 * look the same.
 */
export function recommendationRows(files, policies = null) {
  if (!hasLifecycleData(files)) return null
  return files
    .map((f) => ({ row: f, bucket: recommendationBucketOf(f) }))
    .filter(({ bucket }) => bucket === 'archive' || bucket === 'delete')
    .map(({ row, bucket }) => ({
      file: row.file,
      path: row.path || row.folder || row.file,
      bucket,
      tag: REVIEW_TAG[bucket],
      rule: ruleNameOf(row, policies),
      reason: lifecycleReasonOf(row),
      conflicted: isConflicted(row),
      override: overrideOf(row),
    }))
    .sort((a, b) => (a.bucket === b.bucket
      ? String(a.file).localeCompare(String(b.file))
      : a.bucket === 'delete' ? -1 : 1))
}

// ── Reconciliations ───────────────────────────────────────────────────────────

/** Wrap buckets with their population, their sum, and whether the two agree. `balanced` is what
 *  the screen prints; a false there is a defect a reader can see rather than one they inherit. */
export function reconcile(buckets, total, population) {
  const sum = buckets.reduce((a, b) => a + b.count, 0)
  return { buckets, total, sum, balanced: sum === total, population }
}

/**
 * Every discovered file, grouped by format, summing to the number of files discovered.
 * Null when `files` is not an array.
 *
 * SCOPED TO THE ROWS ON SCREEN — `files` is the scanned population (only assessable formats are
 * ever opened and scored), so an image, a video, or a legacy type discovery merely LISTED never
 * appears here with a real count. `estateTypeReconciliation` below is the whole-estate version;
 * prefer it when an inventory is available and fall back to this only when it is not (a local
 * scan, or one predating the inventory field).
 */
export function typeReconciliation(files, population = 'files discovered') {
  if (!Array.isArray(files)) return null
  const counts = new Map(FORMAT_BUCKETS.map(([k]) => [k, 0]))
  files.forEach((f) => { const k = formatBucketOf(f); counts.set(k, (counts.get(k) || 0) + 1) })
  const buckets = FORMAT_BUCKETS
    .map(([key, label, assessable]) => ({ key, label, assessable, count: counts.get(key) || 0 }))
    // A format with no files in this estate is dropped: it is not a bucket of this population.
    .filter((b) => b.count > 0)
  return reconcile(buckets, files.length, population)
}

/**
 * The same by-type partition as `typeReconciliation`, but over the WHOLE estate listing
 * (`estate_inventory.summarize()`'s `by_format`/`discovered`, computed server-side from every
 * file Drive/SharePoint returned — image, video and unsupported types included, none of them
 * ever opened or scored). This is what the "grey types are inventoried but carry no WCAG test"
 * caption below the bars actually promises; `typeReconciliation(files)` cannot deliver on that
 * promise because the scanned-rows population it counts over structurally excludes almost every
 * non-assessable file (found 2026-08-21: an estate of mostly images/video rendered this panel as
 * if the estate were document-only, with no error and no wrong number — the grey buckets were
 * just always empty, because the files that belonged in them were never in `files` to begin with).
 *
 * Null when there is no inventory to read (a local scan, or one predating this field) — the
 * caller falls back to `typeReconciliation(files)`, which is honest about a narrower population
 * rather than wrong about the whole one.
 *
 * The bucket vocabulary (docx/pdf/pptx/xlsx/html/image/av/other) is shared verbatim with
 * `api/estate_inventory.py`'s `_format_of` — same taxonomy, so no re-derivation can drift from it.
 */
export function estateTypeReconciliation(inventory, population = 'the whole estate listing') {
  if (!inventory || typeof inventory !== 'object') return null
  const total = Number(inventory.discovered)
  const by = inventory.by_format
  if (!Number.isFinite(total) || !by || typeof by !== 'object') return null
  const buckets = FORMAT_BUCKETS
    .map(([key, label, assessable]) => ({ key, label, assessable, count: Number(by[key]) || 0 }))
    .filter((b) => b.count > 0)
  return reconcile(buckets, total, population)
}

/**
 * Every discovered file in exactly one recommendation bucket, summing to the number of files
 * discovered. Null when the lifecycle pass did not reach this screen.
 */
export function recommendationReconciliation(files, population = 'files discovered') {
  if (!hasLifecycleData(files)) return null
  const counts = new Map(RECOMMENDATION_BUCKETS.map(([k]) => [k, 0]))
  files.forEach((f) => { const k = recommendationBucketOf(f); counts.set(k, counts.get(k) + 1) })
  const buckets = RECOMMENDATION_BUCKETS
    .map(([key, label, tone]) => ({ key, label, tone, count: counts.get(key) }))
    // Archive / deletion / no-recommendation are the partition a reader came for and are always
    // shown, zero or not — those zeros are measured. The rarer states appear only when they occur.
    .filter((b) => b.count > 0 || ['archive', 'delete', 'none'].includes(b.key))
  return reconcile(buckets, files.length, population)
}

// ── Headline ──────────────────────────────────────────────────────────────────

/**
 * The four headline numbers, each `null` when it cannot be measured from what was passed in.
 *
 * `discovered` counts the file rows on this screen — the same population every reconciliation
 * below it counts over, so the numbers add up to each other. `estateListed` is the separate,
 * whole-estate listing total from the scan's stored inventory summary; it is carried so the
 * caller can SAY when the two differ instead of letting a filtered view read as the estate.
 */
export function estateSummary(files, inventory = null) {
  if (!Array.isArray(files)) return null
  const lifecycle = hasLifecycleData(files)
  const count = (bucket) => files.filter((f) => recommendationBucketOf(f) === bucket).length
  const listed = inventory && Number.isFinite(Number(inventory.discovered))
    ? Number(inventory.discovered) : null
  return {
    discovered: files.length,
    // Absent, not zero, until the lifecycle columns reach this screen.
    archive: lifecycle ? count('archive') : null,
    delete: lifecycle ? count('delete') : null,
    unreadable: files.filter(isUnreadable).length,
    // HOW MUCH OF THIS ESTATE CAN BE ASSESSED AT ALL. Discovery lists everything; only some of it
    // carries an accessibility test. On an estate of 12,408 files where 22 are Office or PDF, that
    // one number reframes the engagement — and it was previously visible only inside a funnel and
    // a bar chart, never as a headline.
    //
    // Metadata-derived, so discovery is entitled to it (ADR 0020: no file is opened). Read from
    // the SAME helper the bucket reconciliation uses, so the header cannot contradict the
    // partition below it. Null when nothing measured it — never 0, which would claim the estate
    // contains nothing testable.
    assessable: assessmentEligible(inventory),
    estateListed: listed,
    // The listing hit its cap, so the counts are a FLOOR. Silent truncation is the one failure
    // an inventory exists to prevent.
    truncated: !!(inventory && inventory.truncated),
    hasLifecycle: lifecycle,
  }
}

/**
 * What the acknowledgement covers, in words. Null when there is nothing to acknowledge — the
 * lifecycle pass did not reach this screen, or it produced no recommendations.
 */
export function acknowledgementSummary(files, overrides = []) {
  if (!hasLifecycleData(files)) return null
  const archive = files.filter((f) => recommendationBucketOf(f) === 'archive').length
  const del = files.filter((f) => recommendationBucketOf(f) === 'delete').length
  const total = archive + del
  if (!total) return null
  const overridden = new Set(overrides).size
  return { total, archive, delete: del, overridden }
}

export const plural = (n, one, many) => (n === 1 ? one : many)
