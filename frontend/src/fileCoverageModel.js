const finished = new Set(['done', 'completed', 'failed', 'dead', 'review', 'cancelled', 'skipped'])
const outstanding = new Set(['queued', 'waiting', 'pending', 'processing', 'running', 'retrying'])
const count = value => Number.isInteger(value) && value >= 0

// Processing coverage is a job outcome, never an approval or a repaired-finding count.
export function fileCoverage({ files = [], attempts = [], counts, available } = {}) {
  if (available === false || (!counts && !files.length)) return { withFindings:null, processed:null, remaining:null, available:false, unknown:null }
  if (counts && count(counts.withFindings) && count(counts.processed) && count(counts.remaining)
      && counts.processed + counts.remaining === counts.withFindings) return { ...counts, available: true }
  if (counts) return { withFindings: count(counts.withFindings) ? counts.withFindings : null, processed: null, remaining: null, available: false, unknown: count(counts.withFindings) ? counts.withFindings : 0 }
  const population = [...new Set(files.filter(file => file.hasFindings === true).map(file => file.file).filter(Boolean))]
  let processed = 0
  let unknown = 0
  for (const file of population) {
    const evidence = attempts.filter(attempt => attempt.file === file)
    if (evidence.some(attempt => attempt.retryScheduled === true || outstanding.has(attempt.state))) continue
    if (evidence.length && evidence.every(attempt => finished.has(attempt.state) && attempt.attempted !== false)) processed++
    else unknown++
  }
  return { withFindings: population.length, processed: unknown ? null : processed,
    remaining: unknown ? null : population.length - processed, available: !unknown, unknown }
}

export function comparison(value, baseline) {
  return count(value) && count(baseline) ? { before: baseline, delta: value - baseline } : null
}
