// Real timing for App.jsx's initial-load chain — every claim so far about this chain being
// "stuck" or "faster now" (the stale-while-revalidate work across Overview/Assess/Discover) has
// come from a screenshot or an inference, never a measured number. This turns it into one:
// performance.mark/measure around the two real network waits (GET /workspace/bootstrap, then
// GET /scans/{id}), logged as a one-line summary the instant the load finishes — open DevTools'
// console (or the Performance panel, where the marks show up on the timeline directly) after any
// reload and read it straight off, no backend or extra infra needed.
//
// Every call is wrapped defensively: the Performance API is universal in real browsers but this
// module is also imported by test files that mount App.jsx under jsdom, where `performance.mark`
// may be absent or throw for an unrelated reason (a duplicate mark name, e.g.) — a perf
// instrument must never be the thing that breaks the load it's measuring.
const PREFIX = 'acp:'
const supported = typeof performance !== 'undefined' && typeof performance.mark === 'function'

export function markLoad(name) {
  if (!supported) return
  try { performance.mark(PREFIX + name) } catch { /* never let instrumentation break the load */ }
}

// Returns the duration in ms, or null if either mark is missing (a path that didn't reach that
// point — e.g. no scan on this workspace, so 'scan-resolved' was never marked) or the
// Performance API rejected the pair for any other reason.
function measureLoad(name, startMark, endMark) {
  if (!supported || typeof performance.measure !== 'function') return null
  try {
    const m = performance.measure(PREFIX + name, PREFIX + startMark, PREFIX + endMark)
    return m ? Math.round(m.duration) : null
  } catch { return null }
}

// Called once, from App.jsx's load effect's `.finally()` — after 'load-start', 'bootstrap-
// resolved' (always, once GET /workspace/bootstrap settles) and 'scan-resolved' (only when a
// scan actually existed to fetch) have had their chance to be marked.
export function logLoadSummary({ hadPreview, hadScan } = {}) {
  const bootstrapMs = measureLoad('bootstrap', 'load-start', 'bootstrap-resolved')
  const scanMs = hadScan ? measureLoad('scan-fetch', 'bootstrap-resolved', 'scan-resolved') : null
  const totalMs = measureLoad('total-load', 'load-start', 'load-complete')
  if (totalMs == null) return   // nothing measurable — don't log a half-blank line
  const parts = [`bootstrap ${bootstrapMs ?? '?'}ms`]
  if (hadScan) parts.push(`scan ${scanMs ?? '?'}ms`)
  parts.push(`total ${totalMs}ms`)
  parts.push(hadPreview ? 'preview shown early' : 'no cached preview')
  // eslint-disable-next-line no-console
  console.info(`[ACP load] ${parts.join(' · ')}`)
}
