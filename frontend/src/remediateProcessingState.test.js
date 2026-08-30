import { describe, it, expect } from 'vitest'
import { deriveRemediateProcessingState } from './remediateProcessingState.js'

describe('deriveRemediateProcessingState', () => {
  it('is idle when nothing is enqueued', () => {
    const d = deriveRemediateProcessingState({})
    expect(d.state).toBe('idle')
    expect(d.headline).toBeNull()
  })

  it('is idle once at least one document has completed — the live progress bar takes over', () => {
    const d = deriveRemediateProcessingState({
      remBusy: true, remProg: { total: 10, done: 3, latest: 'a.pdf', failed: 0 },
    })
    expect(d.state).toBe('idle')
  })

  it('reports waiting while enqueued but nothing has completed yet, with no pickup estimate', () => {
    const d = deriveRemediateProcessingState({
      remBusy: true, remProg: { total: 10, done: 0, latest: null, failed: 0 },
    })
    expect(d.state).toBe('waiting')
    expect(d.headline).toMatch(/waiting for a worker/i)
    expect(d.detail).toMatch(/10 documents queued for remediation/)
    expect(d.detail).not.toMatch(/estimated pickup/i)
    expect(d.severity).toBe('waiting')
    expect(d.pickupUnavailable).toBe(true)
  })

  it('reports waiting during the round trip before remProg exists yet (remBusy true, remProg still null)', () => {
    const d = deriveRemediateProcessingState({ remBusy: true, remProg: null })
    expect(d.state).toBe('waiting')
    expect(d.detail).toMatch(/^0 documents queued/)
  })

  it('adds an "Estimated pickup" clause and clears pickupUnavailable from a real queue-estimate', () => {
    const now = Date.now()
    const d = deriveRemediateProcessingState({
      remBusy: true, remProg: { total: 5, done: 0, latest: null, failed: 0 },
      pickupEstimate: {
        available: true, state: 'estimated',
        earliest_at: new Date(now + 2 * 60000).toISOString(),
        latest_at: new Date(now + 5 * 60000).toISOString(),
      },
    })
    expect(d.detail).toMatch(/Estimated pickup: 2–5 min\./)
    expect(d.pickupUnavailable).toBe(false)
  })

  it('stays pickupUnavailable for insufficient_history — no confident-looking guess from thin data', () => {
    const d = deriveRemediateProcessingState({
      remBusy: true, remProg: { total: 5, done: 0, latest: null, failed: 0 },
      pickupEstimate: { available: true, state: 'insufficient_history', earliest_at: null, latest_at: null },
    })
    expect(d.detail).not.toMatch(/estimated pickup/i)
    expect(d.pickupUnavailable).toBe(true)
  })
})
