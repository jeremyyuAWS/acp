import { describe, it, expect } from 'vitest'
import { deriveProcessingState } from './processingState.js'

describe('deriveProcessingState', () => {
  it('is idle when the assessment is not running', () => {
    const d = deriveProcessingState({ phase: 'idle' })
    expect(d.state).toBe('idle')
    expect(d.headline).toBeNull()
  })

  it('reports no_capacity with a recommended start-workers action', () => {
    const d = deriveProcessingState({
      phase: 'running', noCapacity: true, completedCount: 0, totalCount: 12,
    })
    expect(d.state).toBe('no_capacity')
    expect(d.headline).toMatch(/waiting for a worker/i)
    expect(d.detail).toMatch(/12 documents queued/)
    expect(d.recommendedAction).toBe('start_workers')
    expect(d.severity).toBe('blocked')
    expect(d.pickupUnavailable).toBe(true)
  })

  it('reports stalled distinctly from no_capacity, even when noCapacity would also be checked', () => {
    // noCapacity is checked first in the ladder — a truly stalled run (workers > 0 but no
    // recent activity) never sets noCapacity true in the first place, so this pins the ladder
    // order rather than the (impossible) case of both being true.
    const d = deriveProcessingState({
      phase: 'running', noCapacity: false, stalled: true, completedCount: 4, totalCount: 12,
    })
    expect(d.state).toBe('stalled')
    expect(d.headline).toMatch(/may be stalled/i)
    expect(d.detail).toMatch(/8 remaining/)
    expect(d.recommendedAction).toBe('check_worker_service')
    expect(d.severity).toBe('warning')
  })

  it('reports completed once every document is accounted for', () => {
    const d = deriveProcessingState({
      phase: 'running', completedCount: 12, totalCount: 12, processingCount: 0, waitingCount: 0,
    })
    expect(d.state).toBe('completed')
    expect(d.recommendedAction).toBeNull()
  })

  it('reports assessing with the current document in the headline when known', () => {
    const d = deriveProcessingState({
      phase: 'running', completedCount: 4, totalCount: 12, processingCount: 1, waitingCount: 7,
      currentFile: 'policy.pdf', currentPhase: 'extracting text',
    })
    expect(d.state).toBe('assessing')
    expect(d.headline).toBe('Assessing policy.pdf')
    expect(d.detail).toBe('4 of 12 completed · 1 processing · 7 waiting · extracting text')
  })

  it('falls back to a generic assessing headline with no current file', () => {
    const d = deriveProcessingState({
      phase: 'running', completedCount: 4, totalCount: 12, processingCount: 1, waitingCount: 7,
    })
    expect(d.headline).toBe('Assessing documents')
  })

  it('reports waiting when nothing is processing yet but capacity exists', () => {
    const d = deriveProcessingState({
      phase: 'running', completedCount: 0, totalCount: 12, processingCount: 0, waitingCount: 12,
      lastActivityMins: 2,
    })
    expect(d.state).toBe('waiting')
    expect(d.detail).toMatch(/12 documents ahead/)
    expect(d.detail).toMatch(/Last activity 2 min ago/)
    expect(d.pickupUnavailable).toBe(true)
  })

  it('omits the "last activity" clause when none is known yet', () => {
    const d = deriveProcessingState({
      phase: 'running', completedCount: 0, totalCount: 12, processingCount: 0, waitingCount: 12,
      lastActivityMins: null,
    })
    expect(d.detail).not.toMatch(/last activity/i)
  })
})
