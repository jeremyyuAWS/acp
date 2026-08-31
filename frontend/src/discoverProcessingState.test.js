import { describe, it, expect } from 'vitest'
import { deriveDiscoverProcessingState } from './discoverProcessingState.js'

describe('deriveDiscoverProcessingState', () => {
  it('is idle when nothing is busy and the run is not one of the states this covers', () => {
    const d = deriveDiscoverProcessingState({ busy: false, runStatus: 'discovered' })
    expect(d.state).toBe('idle')
    expect(d.headline).toBeNull()
  })

  it('reports failed with the recorded failure reason and a rerun action', () => {
    const d = deriveDiscoverProcessingState({
      busy: false, runStatus: 'failed',
      failureReason: "Discovery already active for source 'drive': scan abc123 is still running",
    })
    expect(d.state).toBe('failed')
    expect(d.headline).toMatch(/did not finish/i)
    expect(d.detail).toBe("Discovery already active for source 'drive': scan abc123 is still running")
    expect(d.recommendedAction).toBe('rerun')
    expect(d.severity).toBe('blocked')
  })

  it('falls back to a generic detail when no failure reason was recorded', () => {
    const d = deriveDiscoverProcessingState({ busy: false, runStatus: 'failed', failureReason: null })
    expect(d.detail).toMatch(/the last attempt to list this source failed/i)
  })

  it('distinguishes cancelled from interrupted', () => {
    const cancelled = deriveDiscoverProcessingState({ busy: false, runStatus: 'cancelled' })
    expect(cancelled.state).toBe('cancelled')
    expect(cancelled.headline).toMatch(/was stopped/i)

    const interrupted = deriveDiscoverProcessingState({ busy: false, runStatus: 'interrupted' })
    expect(interrupted.state).toBe('interrupted')
    expect(interrupted.headline).toMatch(/was interrupted/i)
  })

  it('reports a scan that looks running but is not tracked live as possibly stuck', () => {
    const d = deriveDiscoverProcessingState({ busy: false, runStatus: 'running' })
    expect(d.state).toBe('stuck')
    expect(d.recommendedAction).toBe('rerun')
  })

  it('reports a queued scan this tab is not tracking as not-yet-started, with no pickup estimate', () => {
    const d = deriveDiscoverProcessingState({ busy: false, runStatus: 'queued' })
    expect(d.state).toBe('queued')
    expect(d.headline).toMatch(/not started yet/i)
    expect(d.pickupUnavailable).toBe(true)
  })

  it('reports waiting-for-a-worker while this tab is tracking a freshly queued scan', () => {
    const d = deriveDiscoverProcessingState({ busy: true, phase: 'queued', runStatus: 'queued' })
    expect(d.state).toBe('queued')
    expect(d.headline).toMatch(/waiting for a worker/i)
    expect(d.detail).toMatch(/will start automatically/i)
    expect(d.severity).toBe('waiting')
  })

  it('reports "Worker assigned" once the durable-queue job has been claimed, with elapsed time', () => {
    const d = deriveDiscoverProcessingState({
      busy: true, phase: 'queued', jobClaimed: true, assignedSecsAgo: 12.7,
    })
    expect(d.state).toBe('assigned')
    expect(d.headline).toMatch(/worker assigned/i)
    expect(d.detail).toMatch(/claimed this job 13s ago/i)
    expect(d.severity).toBe('active')
    expect(d.pickupUnavailable).toBeFalsy()
  })

  it('falls back to generic assigned copy when no claim timestamp is known', () => {
    const d = deriveDiscoverProcessingState({ busy: true, phase: 'queued', jobClaimed: true })
    expect(d.detail).toMatch(/a worker has claimed this job/i)
  })

  it('prefers "Worker assigned" over a degraded-capacity queued message once claimed', () => {
    const d = deriveDiscoverProcessingState({
      busy: true, phase: 'queued', capacityState: 'unavailable', jobClaimed: true, assignedSecsAgo: 3,
    })
    expect(d.headline).toMatch(/worker assigned/i)
    expect(d.severity).toBe('active')
  })

  it('explains degraded capacity instead of the generic queued message', () => {
    const d = deriveDiscoverProcessingState({ busy: true, phase: 'queued', capacityState: 'starting' })
    expect(d.detail).toMatch(/a worker is starting/i)
  })

  it('builds "compatible jobs ahead" / worker-pool / submitted facts when given, omitting what it lacks', () => {
    const d = deriveDiscoverProcessingState({
      busy: true, phase: 'queued', compatibleJobsAhead: 3, workersTotal: 4, workersOnline: true,
      submittedSecsAgo: 130,
    })
    expect(d.facts).toEqual([
      { label: 'Compatible jobs ahead', value: '3' },
      { label: 'Worker pool', value: '4 online' },
      { label: 'Submitted', value: '2m ago' },
    ])
    expect(d.next).toMatch(/connect to the source/i)
  })

  it('shows the worker pool as offline rather than a fabricated busy fraction', () => {
    const d = deriveDiscoverProcessingState({ busy: true, phase: 'queued', workersTotal: 0, workersOnline: false })
    expect(d.facts).toContainEqual({ label: 'Worker pool', value: 'offline' })
  })

  it('omits queue facts entirely when the caller has none yet, rather than a placeholder', () => {
    const d = deriveDiscoverProcessingState({ busy: true, phase: 'queued' })
    expect(d.facts).toEqual([])
    expect(d.pickupUnavailable).toBe(true)
  })

  it('adds an "Estimated pickup" fact and clears pickupUnavailable from a real queue-estimate', () => {
    const now = Date.now()
    const d = deriveDiscoverProcessingState({
      busy: true, phase: 'queued', compatibleJobsAhead: 2,
      pickupEstimate: {
        available: true, state: 'estimated',
        earliest_at: new Date(now + 2 * 60000).toISOString(),
        latest_at: new Date(now + 4 * 60000).toISOString(),
        confidence: 'medium',
      },
    })
    expect(d.facts).toContainEqual({ label: 'Estimated pickup', value: '2–4 min' })
    expect(d.pickupUnavailable).toBe(false)
  })

  it('stays pickupUnavailable for insufficient_history — no confident-looking guess from thin data', () => {
    const d = deriveDiscoverProcessingState({
      busy: true, phase: 'queued',
      pickupEstimate: { available: true, state: 'insufficient_history', earliest_at: null, latest_at: null },
    })
    expect(d.facts.find((f) => f.label === 'Estimated pickup')).toBeUndefined()
    expect(d.pickupUnavailable).toBe(true)
  })

  it('stays pickupUnavailable when the queue-estimate fetch has not resolved yet', () => {
    const d = deriveDiscoverProcessingState({ busy: true, phase: 'queued', pickupEstimate: null })
    expect(d.pickupUnavailable).toBe(true)
  })

  it('escalates severity to blocked when capacity is unavailable', () => {
    const d = deriveDiscoverProcessingState({ busy: true, phase: 'queued', capacityState: 'unavailable' })
    expect(d.severity).toBe('blocked')
    expect(d.detail).toMatch(/no compatible worker is online/i)
    expect(d.noWorkerAvailable).toBe(true)
  })

  it('also sets noWorkerAvailable from the backend queue-estimate route\'s own capacity check', () => {
    // A capability check independent of capacityState — can catch capacity dropping to zero after
    // capacityState was last read, since it comes from a live poll of its own.
    const d = deriveDiscoverProcessingState({
      busy: true, phase: 'queued',
      pickupEstimate: { available: true, state: 'no_worker_available' },
    })
    expect(d.noWorkerAvailable).toBe(true)
  })

  it('does not set noWorkerAvailable when capacity is merely degraded, not unavailable', () => {
    const d = deriveDiscoverProcessingState({ busy: true, phase: 'queued', capacityState: 'busy' })
    expect(d.noWorkerAvailable).toBeFalsy()
  })

  it('reports the active discovery stage with counts and elapsed time', () => {
    const d = deriveDiscoverProcessingState({
      busy: true, phase: 'discovering', discoveredCount: 42, elapsedSecs: 12.7,
    })
    expect(d.state).toBe('discovering')
    expect(d.headline).toBe('Discovering documents')
    expect(d.detail).toBe('42 found so far · 13s elapsed')
    expect(d.severity).toBe('active')
  })

  it('labels the lifecycle stage distinctly from discovering', () => {
    const d = deriveDiscoverProcessingState({ busy: true, phase: 'lifecycle' })
    expect(d.headline).toBe('Applying lifecycle rules')
  })

  it('adds live-activity facts (found/folders found/recent rate/inventory updated) when given', () => {
    const d = deriveDiscoverProcessingState({
      busy: true, phase: 'discovering', discoveredCount: 951, foldersFound: 14,
      filesPerSec: 23.4, inventoryChangedSecsAgo: 2,
    })
    expect(d.facts).toEqual([
      { label: 'Files found', value: '951' },
      { label: 'Folders found', value: '14' },
      { label: 'Recent discovery rate', value: '23 files/sec' },
      { label: 'Inventory updated', value: '2s ago' },
    ])
  })

  it('adds the worker-heartbeat fact when given — the third of the PRD\'s three freshness timestamps', () => {
    const d = deriveDiscoverProcessingState({
      busy: true, phase: 'discovering', discoveredCount: 951, workerHeartbeatAgeS: 3,
    })
    expect(d.facts).toContainEqual({ label: 'Worker heartbeat', value: '3s ago' })
  })

  it('formats a worker heartbeat over a minute old in minutes, matching fmtAgo elsewhere', () => {
    const d = deriveDiscoverProcessingState({ busy: true, phase: 'discovering', workerHeartbeatAgeS: 125 })
    expect(d.facts).toContainEqual({ label: 'Worker heartbeat', value: '2m ago' })
  })

  it('withholds the worker-heartbeat fact when the caller has no heartbeat data', () => {
    const d = deriveDiscoverProcessingState({ busy: true, phase: 'discovering', discoveredCount: 5 })
    expect(d.facts.find((f) => f.label === 'Worker heartbeat')).toBeUndefined()
  })

  it('withholds the discovery-rate fact when the caller has not smoothed a reading yet', () => {
    const d = deriveDiscoverProcessingState({ busy: true, phase: 'discovering', discoveredCount: 5, filesPerSec: null })
    expect(d.facts.find((f) => f.label === 'Recent discovery rate')).toBeUndefined()
  })

  it('names folder/file-level detail as not-yet-tracked, rather than a fabricated value', () => {
    const d = deriveDiscoverProcessingState({ busy: true, phase: 'discovering', discoveredCount: 5 })
    expect(d.comingSoon).toMatch(/isn't tracked yet/i)
  })

  // Found live 2026-08-29: this "not tracked yet" note kept rendering directly above
  // FolderActivity.jsx (#929/#930, shipped later the same night) actively showing real folder
  // names — a direct on-screen contradiction. hasFolderActivity lets Discover.jsx say "something
  // else on this page already covers that."
  it('withholds comingSoon once FolderActivity has real folder detail to show instead', () => {
    const d = deriveDiscoverProcessingState({ busy: true, phase: 'discovering', discoveredCount: 5,
                                              hasFolderActivity: true })
    expect(d.comingSoon).toBeFalsy()
  })

  it('still names folder detail as not-yet-tracked on a flat scan with no folder activity at all', () => {
    const d = deriveDiscoverProcessingState({ busy: true, phase: 'discovering', discoveredCount: 5,
                                              hasFolderActivity: false })
    expect(d.comingSoon).toMatch(/isn't tracked yet/i)
  })

  it('formats a sub-10 files/sec rate with one decimal, and rounds a faster one', () => {
    const slow = deriveDiscoverProcessingState({ busy: true, phase: 'discovering', filesPerSec: 3.14 })
    expect(slow.facts.find((f) => f.label === 'Recent discovery rate').value).toBe('3.1 files/sec')
    const fast = deriveDiscoverProcessingState({ busy: true, phase: 'discovering', filesPerSec: 87.6 })
    expect(fast.facts.find((f) => f.label === 'Recent discovery rate').value).toBe('88 files/sec')
  })

  it('flags a stale live signal as a warning, not just active progress', () => {
    const d = deriveDiscoverProcessingState({ busy: true, phase: 'discovering', freshness: 'stale' })
    expect(d.severity).toBe('warning')
    expect(d.detail).toMatch(/data may be outdated/i)
  })

  it('mentions reconnecting when the live SSE connection is known dead', () => {
    const d = deriveDiscoverProcessingState({ busy: true, phase: 'discovering', freshness: 'reconnecting' })
    expect(d.detail).toMatch(/reconnecting/i)
  })

  it('sets the live flag when freshness is "live" — the Redis job state updated within 30s', () => {
    const d = deriveDiscoverProcessingState({ busy: true, phase: 'discovering', freshness: 'live' })
    expect(d.live).toBe(true)
  })

  it('does not set the live flag for reconnecting, stale, checkpoint, or unknown freshness', () => {
    for (const freshness of ['reconnecting', 'stale', 'checkpoint', null, undefined]) {
      const d = deriveDiscoverProcessingState({ busy: true, phase: 'discovering', freshness })
      expect(d.live, `freshness=${freshness} should not set live`).toBeFalsy()
    }
  })
})

it('does not call an unaccepted submission queued or assigned', () => {
 for (const phase of ['preparing', 'submitting']) {
  const state = deriveDiscoverProcessingState({busy:true,phase})
  expect(state.state).toBe(phase)
  expect(state.headline).not.toMatch(/worker|queued/i)
 }
})
