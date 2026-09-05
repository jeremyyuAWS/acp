// The persistent run card's model. Pure: no React, no fetch, no clock of its own — the card
// renders what this returns, and this decides nothing the server already decided.
//
// IT DOES NOT DERIVE RUN STATE. `remediation_run.py` owns the state machine and the snapshot
// carries its verdict; this maps that verdict onto the words the card shows and nothing more.
// A second state machine in the browser is the exact defect the whole panel exists to close.

// ── the stacked progress bar ─────────────────────────────────────────────────
//
// FOUR FILLS ON A NEUTRAL TRACK, not five fills. `waiting` is the unfilled remainder, which is
// semantically what it is — nothing has happened to those documents yet — and it is also what
// made the palette pass: a neutral among the fills failed the chroma floor and sat too close to
// the blue.
//
// THE ORDER IS LOAD-BEARING, not cosmetic. The palette was validated with the dataviz checker
// (scripts/validate_palette.js), which tests ADJACENT pairs. Ordered
// completed→active→failed→blocked the worst adjacent pair is ΔE 19.5 protan / 20.7 normal,
// against thresholds of 8 and 15. Swap failed and blocked and blue sits next to violet at
// ΔE 1.4 protan — a protanope cannot tell active from blocked. Red between them is the fix.
//
// Every segment also carries its label and count, so identity never rests on colour (WCAG 1.4.1,
// and the brief's own rule).
export const SEGMENTS = [
  { key: 'completed', label: 'Completed', fill: '#3B6D11' },   // --success-fg
  { key: 'processing', label: 'Active', fill: '#1F5FA8' },     // --info-fg
  { key: 'failed', label: 'Failed', fill: '#B43A2A' },         // --error-fg
  { key: 'blocked', label: 'Blocked', fill: '#7B4EA8' },       // re-stepped: see the note above
]

const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : null)

/**
 * Segments with widths as percentages of the run's document scope, plus the unfilled remainder.
 *
 * Returns null when the scope or any counted segment is unknown — a bar drawn from partial
 * counts would show a shorter run than exists, which reads as progress rather than as a gap.
 */
export function progressBar(snapshot) {
  const documents = snapshot?.documents
  const total = num(snapshot?.total_documents)
  if (!documents || !total || total <= 0) return null
  // `blocked` is review + skipped: both are in scope, neither is moving on its own, and both
  // need a person. The snapshot counts them apart (they route to different queues); the BAR
  // shows one blocked band because a reader asking "how much is stuck" wants one number.
  const review = num(documents.review)
  const skipped = num(documents.skipped)
  const counted = {
    completed: num(documents.completed),
    processing: num(documents.processing),
    failed: num(documents.failed),
    blocked: (review === null || skipped === null) ? null : review + skipped,
  }
  if (Object.values(counted).some((v) => v === null)) return null
  const segments = SEGMENTS.map((s) => ({
    ...s, value: counted[s.key], pct: (counted[s.key] / total) * 100,
  })).filter((s) => s.value > 0)
  const accounted = Object.values(counted).reduce((a, b) => a + b, 0)
  return {
    total,
    segments,
    // The track's unfilled tail. Clamped at zero rather than allowed to go negative: a negative
    // remainder means the counters disagree with the scope, which the snapshot's own integrity
    // check reports — the bar must not render the disagreement as a shape.
    waiting: Math.max(0, total - accounted),
    waitingPct: Math.max(0, ((total - accounted) / total) * 100),
  }
}

// ── the ETA gate ─────────────────────────────────────────────────────────────

/** PRD §22: hide estimates until at least five comparable documents have completed. */
export const MIN_DOCUMENTS_FOR_ETA = 5

/**
 * Whether an ETA may be shown at all, and what to say when it may not.
 *
 * TWO GATES, and they are different questions. `throughputEta.estimate` already withholds a
 * range until it has enough SAMPLES over enough time — that is about measurement stability. This
 * adds the product rule, which is about the run: five completed DOCUMENTS. Four polls of a run
 * that has finished nothing is four samples and no evidence, and the sample gate alone would let
 * that through.
 */
export function etaGate(snapshot, throughput) {
  const completed = num(snapshot?.documents?.completed) ?? 0
  if (completed < MIN_DOCUMENTS_FOR_ETA) {
    return { show: false, note: 'Estimating after the first results' }
  }
  if (!throughput || throughput.calibrating || !throughput.etaText) {
    return { show: false, note: 'Estimating after the first results' }
  }
  return { show: true, text: throughput.etaText, basis: `based on ${completed} completed documents` }
}

// ── what the card says the run is doing ──────────────────────────────────────

// The brief's vocabulary. Several of its entries — Starting workers, Saving corrected copies,
// Re-scanning, Verifying — are PHASE-level facts, not run-level ones, so they are read off the
// phase rail rather than invented as extra run states. The run's own state stays exactly what the
// server said it is.
const STATE_WORDS = {
  draft: 'Not started',
  accepted: 'Queued',
  running: 'Applying fixes',
  waiting: 'Waiting for capacity',
  retry_scheduled: 'Retry scheduled',
  needs_attention: 'Needs your review',
  paused: 'Paused',
  stalled: 'Stalled',
  completing: 'Finalizing',
  completed: 'Complete',
  completed_with_exceptions: 'Complete with exceptions',
  failed: 'Failed',
  cancel_requested: 'Stopping',
  cancelled: 'Cancelled',
}

const ACTIVE_PHASE_WORDS = {
  applying: 'Applying fixes',
  rechecking: 'Re-scanning corrected documents',
  saving: 'Saving corrected copies',
  finalizing: 'Verifying evidence',
}

/**
 * The card's headline and its sub-line.
 *
 * NEVER "Complete" WHILE VALIDATION IS PENDING — the brief's rule, and it is satisfied by the
 * server rather than here: `completing` is a distinct state that exists precisely for a run whose
 * documents are all terminal but whose corrected copies have not been delivered, and it renders
 * as "Finalizing". This function cannot produce "Complete" from it.
 */
export function runHeadline(snapshot) {
  const state = snapshot?.state
  if (!state) return null
  const active = (snapshot.phases || []).filter((p) => p.status === 'active')
  const detail = active.map((p) => ACTIVE_PHASE_WORDS[p.key]).filter(Boolean)
  return {
    state,
    label: STATE_WORDS[state] || state,
    // Several phases run at once on a real batch, so this is a list, not a cursor. Naming one
    // "current" phase would imply the serial processing the panel must not imply.
    doing: detail.length ? detail.join(' · ') : null,
    terminal: !!snapshot.terminal,
  }
}

/** Is there a run worth showing a persistent card for? */
export function shouldShowCard(snapshot) {
  if (!snapshot || !snapshot.state) return false
  if (snapshot.state === 'draft') return false
  return true
}
