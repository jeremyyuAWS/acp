// Live 2026-08-30: a job nobody ever claims (no compatible worker ever picks it up) has no
// resolution to reach — App.jsx's pollScanJob EventSource just sits open, `state.done` never
// true, and the .finally() that clears sessionStorage's ACTIVE_JOB_KEY never runs. Every later
// reload found the same stale job_id waiting there and reconnected to it again, so the load
// effect stayed on reconnectJob forever — a real, already-completed scan sitting one query away
// became permanently unreachable, because nothing ever timed this out.
//
// Generous on purpose — a real large-estate crawl can run this long, and reconnecting a
// genuinely still-running scan is the whole point of the mechanism this guards. This only exists
// to eventually stop retrying a job that evidently never will resolve, not to rush one that will.
export const ACTIVE_JOB_STALE_MS = 30 * 60 * 1000

/** Whether a pending reconnect job should be abandoned rather than retried.
 *
 *  `pendingAt` is the wall-clock ms timestamp ACTIVE_JOB_AT_KEY was written with, or null/NaN
 *  for a session that predates this fix (no timestamp was ever stored). That case reads as NOT
 *  stale, deliberately — one wrong direction (a genuinely short-lived reconnect goes briefly
 *  untimed) is far cheaper than the other (discarding a genuinely still-running reconnect on
 *  every session that lacks a timestamp, which would be every session at once on first deploy). */
export function isActiveJobStale(pendingAt, nowMs = Date.now(), staleMs = ACTIVE_JOB_STALE_MS) {
  if (!pendingAt || !Number.isFinite(pendingAt)) return false
  return nowMs - pendingAt > staleMs
}
