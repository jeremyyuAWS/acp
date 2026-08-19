// Outcome-oriented view-model for a running scan/assessment (Track A of the progress redesign).
//
// Pure: it turns the live progress payload (phase, files_found, files_done, elapsed, and — once the
// backend streams them — per-file outcome tallies) into what a user actually wants to know: how much
// is DONE, how fast, how long is left — rather than what one worker is doing to one filename.
//
// TWO honesty rules baked in:
//   * The percentage is COMPLETED files with saved results, never files merely downloaded. `files_done`
//     is bumped only as each per-file result LANDS (see App.jsx queuedProgress note), so it cannot run
//     ahead of real progress the way a download counter would.
//   * Rate and ETA appear ONLY once there is a real signal (>=1 completed file AND measured elapsed
//     time). Before that they are null — a made-up "2 minutes remaining" is worse than none.

const PHASE_LABEL = {
  queued: 'Queued', connecting: 'Connecting to source', discovering: 'Discovering files',
  reading: 'Retrieving files', tagging: 'Classifying documents', analysing: 'Evaluating checks',
  scoring: 'Saving results', done: 'Complete', error: 'Error',
}

// Phases where the outcome-oriented "N of M files" line is the right primary message. The earlier
// phases (connecting/discovering) have no per-file count yet, so they keep their plain status label.
const COUNTED_PHASES = new Set(['reading', 'tagging', 'analysing', 'scoring'])

export function etaText(seconds) {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return null
  if (seconds === 0) return null
  if (seconds < 45) return 'less than a minute'
  const mins = Math.round(seconds / 60)
  if (mins < 60) return `about ${mins} minute${mins === 1 ? '' : 's'}`
  const h = Math.floor(mins / 60)
  const m = mins % 60
  return `about ${h}h${m ? ` ${m}m` : ''}`
}

function normalizeOutcomes(o) {
  if (!o || typeof o !== 'object') return null
  const n = (x) => (typeof x === 'number' && x >= 0 ? Math.round(x) : 0)
  const out = { passed: n(o.passed), review: n(o.review), skipped: n(o.skipped), processing: n(o.processing) }
  // Only meaningful once the backend has actually populated at least one bucket; otherwise the panel
  // should show nothing rather than a row of zeros that reads as "everything skipped".
  return (out.passed || out.review || out.skipped || out.processing) ? out : null
}

export function assessmentProgress(p) {
  if (!p) return null
  const total = p.files_found > 0 ? p.files_found : 0
  const doneRaw = p.files_done > 0 ? p.files_done : 0
  const completed = total ? Math.min(doneRaw, total) : doneRaw
  const remaining = Math.max(0, total - completed)
  const percent = total ? Math.round((completed / total) * 100) : 0
  const elapsed = typeof p.elapsed === 'number' && p.elapsed > 0 ? p.elapsed : null

  const ratePerMin = (elapsed && completed > 0) ? (completed / elapsed) * 60 : null
  const etaSeconds = remaining === 0
    ? (total ? 0 : null)                                   // total known and all done → 0; unknown → null
    : (ratePerMin ? Math.round((remaining / ratePerMin) * 60) : null)

  return {
    phase: p.phase || null,
    phaseLabel: PHASE_LABEL[p.phase] || p.phase || '',
    counted: COUNTED_PHASES.has(p.phase) && total > 0,
    total,
    completed,
    remaining,
    percent,
    ratePerMin: ratePerMin ? Math.round(ratePerMin) : null,
    etaSeconds,
    etaText: etaText(etaSeconds),
    outcomes: normalizeOutcomes(p.outcomes),
  }
}

// The single primary progress line — outcome-oriented where there is a file count, the plain phase
// label otherwise. Kept here (not in the component) so it is unit-tested and the component stays a
// thin render. e.g. "Assessing 145 of 250 files · 58% · about 6 minutes left · 18/min".
export function assessmentLine(p) {
  const vm = assessmentProgress(p)
  if (!vm) return ''
  if (!vm.counted) {
    let s = vm.phaseLabel
    if (typeof p.elapsed === 'number') s += ` · still working (${p.elapsed}s)`
    return s
  }
  const verb = vm.phase === 'reading' ? 'Retrieving' : vm.phase === 'scoring' ? 'Saving' : 'Assessing'
  let s = `${verb} ${vm.completed} of ${vm.total} files · ${vm.percent}%`
  if (vm.etaText) s += ` · ${vm.etaText} left`
  if (vm.ratePerMin) s += ` · ${vm.ratePerMin}/min`
  return s
}
