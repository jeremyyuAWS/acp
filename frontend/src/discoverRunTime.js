// WHEN the inventory was taken.
//
// An inventory is a snapshot. "18,692 files discovered" is not a fact about the estate, it is a
// fact about the estate at an instant — and a Discover screen that shows the counts without the
// instant invites the reader to treat a week-old listing as today's. Same defect as a file count
// without its boundary (scanScope.js): the number is right and unaccompanied.
//
// ── Where the instant actually lives, and where it does NOT ──────────────────────────────────
//
// It is NOT `Date.now()`. A client-side clock stamped at render says when the page was drawn,
// which is exactly the reading that makes a stale snapshot look fresh.
//
// It is NOT `run.started_at` either, and that one is tempting because it is always populated —
// `init_scan_run` writes it for every run. It is when the listing BEGAN. On a large estate that
// is a long way from when the inventory was complete, and it is populated even for a run that
// died mid-listing, so using it would put a confident timestamp under a partial inventory.
//
// The candidates this module will accept, in order:
//
//   1. `run.discovered_at` / `inventory.discovered_at` — the run-level stamp written when the
//      Discover phase finished persisting the inventory. The right answer, and the one the
//      backend did not have before this change; see the PR body.
//   2. the newest `discovered_at` across the inventory ROWS — `scan_inventory.discovered_at` is
//      per file, written by `add_inventory` at the moment the batch was persisted, and it is NOT
//      overwritten by a re-list. Its maximum is therefore the instant the inventory was last
//      added to. Real persisted data, derived rather than invented — and the only thing available
//      for runs discovered before the run-level stamp existed.
//   3. `run.completed_at` — the SCAN's completion. For a legacy one-pass scan
//      (ACP_DEFER_ANALYSIS_TO_ASSESS=0) discovery and assessment finished together, so it dates
//      the listing well. For an ADR 0020 run it is written at Assess finalize, long after the
//      listing, so it is an upper bound. Accepted last, and labelled differently, so a caller
//      never presents it with more precision than it has.
//
// When none of them is present this returns `recorded: false` and NO time. Not the export time,
// not the render time, not `started_at`. A caller renders the absence — "discovery completion
// time not recorded for this run" — because a fabricated instant on a compliance artifact is
// worse than an admitted gap.

/** How the instant was obtained, in the order it is looked for. */
export const TIME_SOURCES = Object.freeze({
  RUN: 'run.discovered_at',
  ROWS: 'max(scan_inventory.discovered_at)',
  COMPLETED: 'run.completed_at',
})

const LABELS = {
  [TIME_SOURCES.RUN]: 'recorded when discovery finished',
  [TIME_SOURCES.ROWS]: 'derived from the newest per-file discovery stamp',
  [TIME_SOURCES.COMPLETED]: 'the scan’s completion time — an upper bound for the listing',
}

/** An inventory older than this is called out. A day is not a rule about correctness — a snapshot
 *  is only ever true as of its instant — it is the point past which a reader is likely to have
 *  forgotten that. Exported so a caller can tighten it. */
export const STALE_AFTER_MS = 24 * 60 * 60 * 1000

/**
 * Parse a persisted timestamp to a UTC ISO instant, or null.
 *
 * Rejects anything unparseable rather than passing a bad string through to `toLocaleString`,
 * which renders "Invalid Date" into the UI.
 *
 * NORMALISED, deliberately, and this is the one place in the export path that reformats a stored
 * value. Connectors spell the same moment differently — `…T10:00:00Z` and `…T04:00:00-07:00` are
 * equal instants and unequal strings — and the resolution below picks a MAXIMUM across them, so a
 * lexical comparison would pick the wrong row. The per-file `discovered_at` COLUMN in the export
 * still carries whatever the source recorded, untouched; only this derived run-level instant is
 * canonicalised, because it is a value ACP computed rather than one it stored.
 */
export function parseAt(v) {
  if (typeof v !== 'string' || !v.trim()) return null
  const t = Date.parse(v)
  return Number.isFinite(t) ? new Date(t).toISOString() : null
}

/** The newest per-file discovery stamp across inventory rows, or null. */
export function newestRowStamp(rows) {
  let best = null
  ;(rows || []).forEach((r) => {
    const at = parseAt(r && r.discovered_at)
    if (at && (best === null || at > best)) best = at
  })
  return best
}

/**
 * Resolve the instant the inventory describes, from records the API already returns.
 *
 * `run` is `GET /scans/{id}`; `inventory` is `GET /scans/{id}/inventory` (either the envelope or
 * anything carrying `discovered_at`); `rows` is the per-file inventory rows. Any of them may be
 * absent — this reads whatever it was given.
 *
 * Returns `{ at, source, label }` or `null`. Never invents a time.
 */
export function resolveInventoryTime({ run = null, inventory = null, rows = null } = {}) {
  const list = rows || (inventory && Array.isArray(inventory.rows) ? inventory.rows : null)
  const runLevel = parseAt(run && run.discovered_at) || parseAt(inventory && inventory.discovered_at)
  if (runLevel) return { at: runLevel, source: TIME_SOURCES.RUN, label: LABELS[TIME_SOURCES.RUN] }
  const derived = newestRowStamp(list)
  if (derived) return { at: derived, source: TIME_SOURCES.ROWS, label: LABELS[TIME_SOURCES.ROWS] }
  const completed = parseAt(run && run.completed_at)
  if (completed) return { at: completed, source: TIME_SOURCES.COMPLETED, label: LABELS[TIME_SOURCES.COMPLETED] }
  return null
}

/** What a caller shows when nothing was persisted. Kept here, beside the reason, so the wording
 *  cannot drift away from what the absence actually means. */
export const NOT_RECORDED_NOTE =
  'This run did not record when its discovery finished, so the counts below cannot be dated. '
  + 'They are true as of whenever the run listed the estate.'

const JUST_NOW = 'just now'
const rel = (ms) => {
  const abs = Math.abs(ms)
  // Under a minute is "just now" by ELAPSED time, not by a rounded minute count — Math.round on
  // 30s gives 1, so a rounding-first ladder never reaches this branch at all.
  if (abs < 60000) return JUST_NOW
  const min = Math.round(abs / 60000)
  if (min < 60) return `${min} minute${min === 1 ? '' : 's'}`
  const hr = Math.round(min / 60)
  if (hr < 48) return `${hr} hour${hr === 1 ? '' : 's'}`
  const day = Math.round(hr / 24)
  if (day < 60) return `${day} day${day === 1 ? '' : 's'}`
  const mon = Math.round(day / 30)
  return `${mon} month${mon === 1 ? '' : 's'}`
}

/**
 * Human forms of one instant.
 *
 * The absolute form always names its time zone. An inventory timestamp is read by people in other
 * offices than the one that ran the scan, and "Aug 19, 3:40 PM" with no zone is two different
 * claims depending on who is reading it. Same choice scanReport.js makes for the PDF header.
 *
 * `now` is injected so this is deterministic under test — it is the clock for the AGE only, never
 * for the instant itself.
 */
export function formatInventoryTime(at, { now = Date.now(), locale = 'en-US', staleAfterMs = STALE_AFTER_MS } = {}) {
  const iso = parseAt(at)
  if (!iso) return null
  const d = new Date(iso)
  const ageMs = now - d.getTime()
  return {
    iso,
    absolute: d.toLocaleString(locale, {
      year: 'numeric', month: 'short', day: 'numeric',
      hour: 'numeric', minute: '2-digit', timeZoneName: 'short',
    }),
    // `ageMs < 0` is a run stamped in the future — a clock skew between the API host and the
    // browser. Saying "in 3 minutes" is at least honest about the disagreement; silently
    // clamping it to "just now" would hide a real problem with the record. Under a minute in
    // either direction is "just now" and takes NEITHER affix — "just now ago" is not English.
    relative: rel(ageMs) === JUST_NOW ? JUST_NOW
      : ageMs < 0 ? `in ${rel(ageMs)}` : `${rel(ageMs)} ago`,
    ageMs,
    stale: ageMs > staleAfterMs,
  }
}

/**
 * Everything a Discover surface needs to state when its inventory was taken, in one call.
 *
 * `recorded: false` is a real answer and the caller must render it as one — it means nobody
 * persisted the instant, never that the inventory is current.
 */
export function inventorySnapshot({ run = null, inventory = null, rows = null,
  now = Date.now(), locale = 'en-US', staleAfterMs = STALE_AFTER_MS } = {}) {
  const hit = resolveInventoryTime({ run, inventory, rows })
  if (!hit) return { recorded: false, at: null, source: null, label: null, note: NOT_RECORDED_NOTE }
  const fmt = formatInventoryTime(hit.at, { now, locale, staleAfterMs })
  return { recorded: true, at: hit.at, source: hit.source, label: hit.label, note: null, ...fmt }
}
