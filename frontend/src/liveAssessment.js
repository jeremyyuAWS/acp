// Live Assessment running screen — pure normalization of the merged /scans/{sid}/live snapshot into a
// display model. Kept out of the component so it is unit-tested and the component stays a thin render.
//
// The snapshot is composed by the backend (kpis + funnel + the worker/queue block from live_queue.py),
// and merges INDEPENDENTLY: the `queue` block and some KPIs may be absent on an older backend — listed
// in `kpis_pending` — so this normalizer treats a missing block as "pending", never as zero. That is the
// difference between an honest "still computing" and a false "nothing happening".

import { outcomeChips, etaText } from './assessmentProgress.js'

const PHASE_LABEL = {
  preparing: 'Preparing', discovering: 'Discovering', reading: 'Reading', assessing: 'Assessing',
  remediating: 'Remediating', finalizing: 'Finalizing', done: 'Complete',
}

// The running-screen KPI cards: [key, label, provisional], in display order.
// `findings_so_far` is supplied by the snapshot backend once a run has produced findings (it starts in
// `kpis_pending`), so it shows a pending dash until then and resolves automatically.
// `provisional` marks a count that GROWS during the run and must never be read as the final total
// (ADR 0016 / PRD §4.3 — "label 'so far', never presented as final"). The component renders a "so far"
// qualifier on these so a mid-run "Findings 42" can't be mistaken for the finished number.
const KPI_DEFS = [
  ['completed', 'Completed', false],
  ['processing', 'Processing', false],
  ['findings_so_far', 'Findings', true],
  ['need_attention', 'Need attention', true],
  ['unable_to_assess', 'Unable to assess', false],
]

const n = (x) => (typeof x === 'number' && x >= 0 ? Math.round(x) : 0)

// The worker/queue/lane sub-block (from live_queue.py). Returns null when absent (older backend) so the
// UI shows a "queue data pending" affordance rather than a fabricated "0 workers".
function normalizeQueue(q) {
  if (!q || typeof q !== 'object') return null
  const w = q.workers || {}
  const cur = q.current && (q.current.file || q.current.text) ? {
    file: q.current.file || null,
    criterion: q.current.criterion || null,
    criterionName: q.current.criterion_name || null,
    action: q.current.action || null,
    text: q.current.text || null,
  } : null
  const inFlight = n(q.in_flight)
  const queued = n(q.queued)
  // A stale block (worker went quiet) is not live progress — say so plainly rather than showing a
  // frozen "6 in flight" that reads as busy.
  const stale = !!q.stale
  return {
    inFlight, queued,
    workers: { busy: n(w.busy), max: typeof w.max === 'number' ? n(w.max) : null,
               idle: typeof w.idle === 'number' ? n(w.idle) : null,
               capacityScope: w.capacity_scope === 'per_replica' ? 'per_replica' : null },
    current: stale ? null : cur,
    processing: !!q.processing && !stale,
    stale,
    // One human line for the lane strip: the current document, or the honest idle/paused state.
    laneLabel: stale ? 'No worker reporting — paused or between phases'
      : cur ? (cur.text || cur.file)
      : inFlight > 0 ? `${inFlight} in progress` : 'Idle',
  }
}

export function normalizeLive(raw) {
  if (!raw || typeof raw !== 'object' || raw.available === false) {
    return { available: false, active: false, kpiCards: [], queue: null, warnings: [] }
  }
  const pending = new Set(Array.isArray(raw.kpis_pending) ? raw.kpis_pending : [])
  const kpis = raw.kpis || {}
  const kpiCards = KPI_DEFS.map(([key, label, provisional]) => ({
    key, label,
    value: n(kpis[key]),
    // A KPI is "pending" (show a spinner/dash, not 0) when the backend flags it not-yet-computed.
    pending: pending.has(key),
    // A provisional KPI grows during the run and must carry a "so far" qualifier (never read as final).
    provisional: !!provisional,
  }))
  const queue = normalizeQueue(raw.queue)
  const warnings = []
  if (!queue && (pending.has('queue') || pending.has('workers') || pending.has('queued')))
    warnings.push('Worker/queue detail is still coming online for this run.')
  if (queue && queue.stale) warnings.push('No worker has reported progress recently.')

  return {
    available: true,
    active: !!raw.active,
    phase: raw.phase || raw.state || null,
    phaseLabel: PHASE_LABEL[raw.phase] || raw.phase || raw.state || '',
    source: raw.source || null,
    runId: raw.run_id || null,
    totals: { discovered: n((raw.totals || {}).discovered), eligible: n((raw.totals || {}).eligible) },
    kpiCards,
    outcomeChips: outcomeChips(raw.outcomes || null),
    queue,
    warnings,
    // Passed through for reconnect/ordering (the UI drops out-of-order frames by sequence).
    sequence: typeof raw.sequence === 'number' ? raw.sequence : null,
    generatedAt: raw.generated_at || null,
  }
}

// Guard against an out-of-order poll/reconnect frame overwriting newer state — accept only a higher
// sequence (or any frame when either side lacks one). Pure so the component's reconnect logic is tested.
export function isNewerFrame(prevSequence, nextSequence) {
  if (typeof nextSequence !== 'number') return true
  if (typeof prevSequence !== 'number') return true
  return nextSequence > prevSequence
}

export { etaText }
