// What the estate actually knows about a document's lifecycle, and what it does not.
//
// `retentionOf` decided each row's keep / archive / retain badge from five fields. FOUR OF THEM DO
// NOT EXIST ON A REAL SCAN. Checked against origin/main on 2026-08-21, counting backend references:
//
//     f.locked      0   SIM-only flag; a real unreadable file is status 'error'
//     f.tags        0   file_records has no tags column (see classificationData.js)
//     f.ageDays     0   nothing computes or stores it
//     f.views90d    0   nothing computes or stores it
//     f.superseded  3   REAL — provenance/shadow detection sets this
//
// `undefined >= 540` is false, so every branch fell through to the last line:
//
//     return { label: 'Keep', why: 'Active and in use — keep in the live estate.' }
//
// On a real estate that badge is a CONSTANT, and its rationale asserts the document is active and
// in use — which nobody measured. Worse, it sits beside an "✓ accept" control, so a reviewer is
// invited to sign off, one row at a time or in bulk, on a recommendation that was never made.
//
// MEANWHILE THE REAL SIGNAL EXISTS AND WAS NOT BEING READ. The discovery rule pass writes
// `lifecycle_status` ("Archive Candidate", "Delete Candidate", "Archived", "Deleted") plus the rule
// id and reason that produced it, and `mergeLifecycle` already merges those onto these very rows —
// they just reached DiscoveryResults' recommendations table and never the row badge. Two lifecycle
// systems on one tab, and the one in front of the reviewer was the dead one.
//
// So: real signal first, SIM heuristics second, and NOTHING as its own answer. "Not assessed" is a
// worse-looking badge and a better one — the same rule the rest of this screen already follows
// (hasLifecycleData, classificationData), which is that an absent measurement must not render as a
// measured result.

import { lifecycleStatusOf } from './discoveryRecommendations.js'

/** Buckets a row can land in. `unassessed` is new and is deliberately not last-resort-Keep. */
export const RETENTION_BUCKETS = ['locked', 'retain', 'archive', 'delete', 'keep', 'unassessed']

/** Did ANY lifecycle signal reach this row? The gate for whether a recommendation exists at all. */
export function hasRetentionSignal(f) {
  if (!f) return false
  if (lifecycleStatusOf(f)) return true
  if (f.locked || f.superseded) return true
  if (Array.isArray(f.tags) && f.tags.length > 0) return true
  return Number.isFinite(f.ageDays) || Number.isFinite(f.views90d)
}

/**
 * The badge for one row: `{ bucket, label, bg, fg, why, source }`.
 *
 * `source` names WHERE the answer came from — 'rule' (the discovery rule pass), 'signal' (a SIM /
 * provenance field), or null (nothing did). A reader who can see that a recommendation came from a
 * named rule can check it; one who cannot see its provenance can only trust it.
 */
export function retentionSignal(f) {
  const row = f || {}

  // 1. UNREADABLE first — it outranks any lifecycle answer, because a document nobody could open
  //    has not been assessed for anything, lifecycle included.
  if (row.locked) {
    return { bucket: 'locked', label: 'Could not open', bg: '#EEEDEA', fg: '#5F5E5A', source: 'signal',
             why: `${row.openIssue || 'could not open'} — provide credentials or an accessible export `
                + 'so this document can be classified and assessed.' }
  }

  // 2. THE REAL RULE PASS, and it wins over every heuristic below. `lifecycle_reason` and
  //    `lifecycle_rule_id` come with it, so the badge can name the rule that produced it rather
  //    than paraphrasing what it probably meant.
  const status = lifecycleStatusOf(row)
  if (status) {
    const named = row.lifecycle_reason || row.lifecycleReason || null
    const rule = row.lifecycle_rule_id || row.lifecycleRuleId || null
    const attribution = named || (rule ? `matched lifecycle rule ${rule}` : 'set by the discovery rule pass')
    const s = status.toLowerCase()
    if (s.includes('delete')) {
      return { bucket: 'delete', label: 'Delete', bg: 'var(--info-bg)', fg: 'var(--info-fg)', source: 'rule',
               why: `Tagged for deletion review — ${attribution}. Nothing is trashed; this is a recommendation.` }
    }
    if (s.includes('archive')) {
      return { bucket: 'archive', label: 'Archive', bg: '#EEEDFE', fg: '#3C3489', source: 'rule',
               why: `Tagged for archive review — ${attribution}. Nothing is moved; this is a recommendation.` }
    }
    // A status that ran and matched nothing IS a measurement — "Keep" is earned here, unlike below.
    return { bucket: 'keep', label: 'Keep', bg: 'var(--success-bg)', fg: 'var(--success-fg)', source: 'rule',
             why: `The lifecycle rules ran and matched nothing — ${attribution}.` }
  }

  // 3. Signals that are real when present. `legal-hold` outranks age, as it always did.
  if (Array.isArray(row.tags) && row.tags.includes('legal-hold')) {
    return { bucket: 'retain', label: 'Retain · legal hold', bg: 'var(--warn-bg)', fg: 'var(--warn-fg)', source: 'signal',
             why: 'Under legal hold — must be retained regardless of age or usage.' }
  }
  if (row.superseded) {
    return { bucket: 'archive', label: 'Archive', bg: '#EEEDFE', fg: '#3C3489', source: 'signal',
             why: 'A newer version exists — archive to shrink the audited estate.' }
  }
  if (Number.isFinite(row.ageDays) && Number.isFinite(row.views90d)
      && row.ageDays >= 540 && row.views90d < 60) {
    return { bucket: 'archive', label: 'Archive candidate', bg: '#EEEDFE', fg: '#3C3489', source: 'signal',
             why: `Last edited ${row.modifiedAge} with ${row.views90d} views/90d — low value to keep live.` }
  }
  // Age and usage present but under the threshold: measured, and the answer is Keep.
  if (Number.isFinite(row.ageDays) && Number.isFinite(row.views90d)) {
    return { bucket: 'keep', label: 'Keep', bg: 'var(--success-bg)', fg: 'var(--success-fg)', source: 'signal',
             why: 'Active and in use — keep in the live estate.' }
  }

  // 4. NOTHING MEASURED THIS ROW. Not "Keep": that would state the document is active and in use on
  //    the strength of four fields nobody populated, next to a control inviting sign-off on it.
  return { bucket: 'unassessed', label: 'Not assessed', bg: '#F1EFF3', fg: '#5F5E5A', source: null,
           why: 'No lifecycle rule matched this document and no age or usage signal reached this '
              + 'screen, so no recommendation was produced for it. Discovery lists the file; the '
              + 'lifecycle question has not been answered.' }
}

/** Sugar: the bucket alone, which is what the grouping and the override control key off. */
export const retentionBucket = (f) => retentionSignal(f).bucket

/** Is there a recommendation here that a reviewer could accept or override?
 *
 *  False for `unassessed` (nothing was recommended — accepting it would record a decision over
 *  nothing) and false for `locked` (a document nobody could open has no recommendation to accept
 *  either, only an access problem to fix). True for everything else, including a rule pass that
 *  measured the row and concluded Keep — that IS a recommendation, just a quiet one.
 *
 *  This is also what GATES the estate down to rows a human needs to decide on at all: an estate
 *  with no disposition rules configured produces `unassessed` for every row, and requiring an
 *  individual decision on each one before Assess is reachable would block a normal user with no
 *  rules set up from ever leaving Discover — the same failure this module exists to prevent,
 *  reached from the opposite direction. */
export const isAcceptable = (f) => !['unassessed', 'locked'].includes(retentionSignal(f).bucket)
