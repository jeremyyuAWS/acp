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
    expect(d.detail).toMatch(/will begin automatically/i)
    expect(d.severity).toBe('waiting')
  })

  it('explains degraded capacity instead of the generic queued message', () => {
    const d = deriveDiscoverProcessingState({ busy: true, phase: 'queued', capacityState: 'starting' })
    expect(d.detail).toMatch(/a worker is starting/i)
  })

  it('escalates severity to blocked when capacity is unavailable', () => {
    const d = deriveDiscoverProcessingState({ busy: true, phase: 'queued', capacityState: 'unavailable' })
    expect(d.severity).toBe('blocked')
    expect(d.detail).toMatch(/no compatible worker is online/i)
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
