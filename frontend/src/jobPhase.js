// What a running job is doing, and whether it has stopped doing it.
//
// The queue panel used to render REM_STEPS — five hardcoded WCAG criteria that a setInterval
// cycled every 1.6s underneath the running job. It had no connection to that job's work, on
// the one screen a person uses to judge whether the system is healthy. Deleted.
//
// The truth now comes from `jobs.phase`, which the handler writes as it moves between real
// steps (downloading, applying fixes, writing to Drive, re-verifying). A handler that reports
// nothing shows nothing — an absent phase renders no line rather than an invented one.

// A job whose phase has not advanced for this long has stopped making visible progress. Two
// remediate jobs sat at "running · 16m 0s" with 0.0/min throughput and nothing flagged them;
// they read as healthy. This is a *suspicion*, not a verdict: a genuinely slow local-vision
// pass over a large deck can exceed it, which is why the label ends in a question mark.
export const STALLED_AFTER_S = 8 * 60

export function isStalled(job, durationSeconds) {
  return job?.status === 'running' && durationSeconds != null && durationSeconds >= STALLED_AFTER_S
}

// `phase` is written only where a job genuinely changes activity, so it is safe to show
// verbatim. Trimmed defensively — it reaches the DOM.
export function phaseLine(job) {
  if (!job || job.status !== 'running') return null
  const p = (job.phase || '').trim()
  return p.length ? p : null
}
