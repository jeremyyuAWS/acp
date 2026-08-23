// What the queued-scan poll should do on this tick.
//
// The durable start path (`startScanQueued`) hands back a `scan_id` before any worker has touched
// the work, and App.jsx then polls `getScan(scan_id)` once a second until the run settles. That
// loop grew four exit conditions inline and none of them were reachable by a test, which is how
// the fifth one came to be missing for so long: **the user pressing Stop**.
//
// WHY STOP DID NOTHING ON A QUEUED SCAN. `POST /scans/{sid}/cancel` tries two things in order
// (api/routes/scans.py). For a scan a worker has CLAIMED, `store.cancel_scan` flips
// `scan_runs.status` to 'cancelled', the poll sees a run that is no longer 'running', and the loop
// ends — Stop works. For a scan still QUEUED there is no `scan_runs` row at all yet (the row is
// created when a worker claims the job), so `cancel_scan` returns False and the route falls back to
// `store.cancel_queued_job`, which marks the `jobs` row 'dead' and returns 200.
//
// That 200 is honest — the scan really is cancelled and no worker will ever run it. But it leaves
// the poll with nothing to see: no worker will ever create the `scan_runs` row, so `getScan` 404s
// forever, `scan` stays null, and the loop's only settling condition (`run.status !== 'running'`)
// can never fire. The banner keeps counting, and the button reads as broken while having worked.
//
// ORDER MATTERS, and it is the reason this is a function rather than an extra `if` in the loop.
// After a cancel the miss counter keeps climbing, so the pre-existing "never started" branch fires
// at ~45s and reports *"this scan never started — the queue may be stuck"* over what was actually a
// deliberate stop. A wrong diagnosis that sends someone to inspect the queue is worse than no
// message, so `cancelled` is checked FIRST and every later branch is unreachable once it is set.
//
// Pure and synchronous: the caller owns the fetching, the progress rendering and the timers. This
// only answers "given what the last poll returned, what now?".

/** Misses tolerated after the scan has been seen at least once, before calling it a lost session. */
export const LOST_AFTER_MISSES = 8
/** Misses tolerated before it was EVER seen, before calling the queue stuck. */
export const NEVER_STARTED_AFTER_MISSES = 45

/**
 * @param cancelled  the user pressed Stop for this run. Checked before everything else.
 * @param scan       the last `getScan` result, or null when that poll missed (404 included).
 * @param foundOnce  has this scan EVER been returned? A queued-unclaimed scan has no row yet, so
 *                   404 from the first poll is expected rather than a symptom.
 * @param misses     consecutive failed polls.
 *
 * @returns {{action: 'stopped'|'session-lost'|'never-started'|'settled'|'continue', scan?: object}}
 *   'stopped'       — the user stopped it. A clean end, NOT an error: the caller must not render
 *                     this as "scan failed", which is what a thrown cancellation would become.
 *   'session-lost'  — seen, then repeatedly vanished. The owner-scoped lookup stopped matching.
 *   'never-started' — never seen at all, long enough that the queue is the suspect.
 *   'settled'       — the run reached a terminal status; `scan` carries it.
 *   'continue'      — nothing decided yet; poll again.
 */
export function scanPollDecision({ cancelled = false, scan = null, foundOnce = false, misses = 0 } = {}) {
  // First, and deliberately so — see the note above about the 45s misdiagnosis.
  if (cancelled) return { action: 'stopped' }

  // "Found, then repeatedly vanished" is the only real session-loss signal. Gating on foundOnce is
  // what stops a never-claimed scan (which 404s from the very first poll) reading as a lost session.
  if (foundOnce && misses >= LOST_AFTER_MISSES) return { action: 'session-lost' }

  if (!foundOnce && misses >= NEVER_STARTED_AFTER_MISSES) return { action: 'never-started' }

  // A run that is no longer 'running' has settled — finished, cancelled server-side, or failed.
  // The caller decides what to show; this only reports that polling is over.
  if (scan && scan.run && scan.run.status !== 'running') return { action: 'settled', scan }

  return { action: 'continue' }
}
