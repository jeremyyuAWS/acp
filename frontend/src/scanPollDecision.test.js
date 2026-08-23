/**
 * The queued-scan poll's exit ladder — including the one that was missing: Stop.
 *
 * Reported live: pressing "Stop scan" on a scan still showing "Queued… · Waiting for a worker to
 * pick up the scan…" did nothing. The server-side cancel SUCCEEDS (the job is marked dead); the
 * poll simply had no way to notice, because a never-claimed scan has no `scan_runs` row and never
 * will once its job is dead — so `getScan` 404s forever and the loop's only settling condition
 * could not fire.
 *
 * These cases are the ladder, in the order it must run. The ordering assertions are the point:
 * `cancelled` has to win over the miss-count branches, or a deliberate stop gets reported ~45s
 * later as "the queue may be stuck" — a wrong diagnosis, aimed at the wrong subsystem.
 */
import { describe, it, expect } from 'vitest'
import { scanPollDecision, LOST_AFTER_MISSES, NEVER_STARTED_AFTER_MISSES } from './scanPollDecision.js'

const running = { run: { status: 'running' } }
const cancelledRun = { run: { status: 'cancelled' } }
const doneRun = { run: { status: 'complete' } }

describe('scanPollDecision — the user pressed Stop', () => {
  it('a cancelled run stops, and stops CLEANLY (not an error)', () => {
    expect(scanPollDecision({ cancelled: true })).toEqual({ action: 'stopped' })
  })

  it('stopping wins over the "never started" branch — the bug that misdiagnosed a deliberate stop', () => {
    // The exact live shape: queued, never claimed, so every poll misses and the counter climbs
    // past the stuck-queue threshold. Without the ordering this reports a stuck queue.
    const d = scanPollDecision({
      cancelled: true, scan: null, foundOnce: false, misses: NEVER_STARTED_AFTER_MISSES + 20,
    })
    expect(d.action).toBe('stopped')
    expect(d.action).not.toBe('never-started')
  })

  it('stopping wins over the session-lost branch too', () => {
    const d = scanPollDecision({
      cancelled: true, scan: running, foundOnce: true, misses: LOST_AFTER_MISSES + 5,
    })
    expect(d.action).toBe('stopped')
  })

  it('stopping wins even when a settled scan arrives on the same tick', () => {
    // Whoever stopped it gets told it stopped. Racing a late result into "settled" would show a
    // completed scan to someone who just cancelled one.
    expect(scanPollDecision({ cancelled: true, scan: doneRun, foundOnce: true }).action).toBe('stopped')
  })
})

describe('scanPollDecision — the pre-existing ladder still holds', () => {
  it('a never-claimed scan 404ing from the first poll is NOT a lost session', () => {
    // A queued scan has no scan_runs row yet; 404 is expected, not a symptom. This is what gates
    // the session-lost branch on foundOnce.
    const d = scanPollDecision({ scan: null, foundOnce: false, misses: LOST_AFTER_MISSES + 3 })
    expect(d.action).toBe('continue')
  })

  it('found, then repeatedly vanished → session lost', () => {
    expect(scanPollDecision({ scan: null, foundOnce: true, misses: LOST_AFTER_MISSES }).action)
      .toBe('session-lost')
  })

  it('never found at all, for long enough → the queue is the suspect', () => {
    expect(scanPollDecision({ scan: null, foundOnce: false, misses: NEVER_STARTED_AFTER_MISSES }).action)
      .toBe('never-started')
  })

  it('a run no longer running has settled, and carries the scan', () => {
    const d = scanPollDecision({ scan: doneRun, foundOnce: true })
    expect(d.action).toBe('settled')
    expect(d.scan).toBe(doneRun)
  })

  it('a server-side cancel (a CLAIMED scan) settles through the same branch', () => {
    // This is the path that always worked: cancel_scan flips scan_runs.status, the poll sees a run
    // that is not 'running', and the loop ends. Kept explicit so the two cancel paths stay visible.
    expect(scanPollDecision({ scan: cancelledRun, foundOnce: true }).action).toBe('settled')
  })

  it('a still-running scan keeps polling', () => {
    expect(scanPollDecision({ scan: running, foundOnce: true, misses: 0 }).action).toBe('continue')
  })

  it('a miss below the thresholds keeps polling', () => {
    expect(scanPollDecision({ scan: null, foundOnce: true, misses: LOST_AFTER_MISSES - 1 }).action)
      .toBe('continue')
  })

  it('defaults to continue when told nothing', () => {
    expect(scanPollDecision().action).toBe('continue')
  })
})
