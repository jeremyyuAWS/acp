import { describe, it, expect } from 'vitest'
import { acceptLiveJobState } from './liveJobStateGuard.js'

describe('acceptLiveJobState', () => {
  it('accepts the first state when there is nothing to compare against', () => {
    expect(acceptLiveJobState(null, { seq: 0, attempt: 1 })).toBe(true)
    expect(acceptLiveJobState(undefined, { seq: 5, attempt: 2 })).toBe(true)
  })

  it('rejects a null/undefined next state', () => {
    expect(acceptLiveJobState({ seq: 3 }, null)).toBe(false)
    expect(acceptLiveJobState({ seq: 3 }, undefined)).toBe(false)
  })

  it('accepts a higher seq within the same attempt', () => {
    expect(acceptLiveJobState({ seq: 3, attempt: 1 }, { seq: 4, attempt: 1 })).toBe(true)
  })

  it('rejects a lower seq within the same attempt — the fallback-poll-vs-SSE race', () => {
    expect(acceptLiveJobState({ seq: 10, attempt: 1 }, { seq: 4, attempt: 1 })).toBe(false)
  })

  it('accepts an equal seq (idempotent — same snapshot arriving twice)', () => {
    expect(acceptLiveJobState({ seq: 7, attempt: 1 }, { seq: 7, attempt: 1 })).toBe(true)
  })

  it('a higher attempt always wins, even with a lower seq', () => {
    // seq is scoped to one attempt — a fresh attempt's seq starting low must not be mistaken
    // for stale data from a higher-seq PRIOR attempt.
    expect(acceptLiveJobState({ seq: 40, attempt: 1 }, { seq: 1, attempt: 2 })).toBe(true)
  })

  it('a lower attempt always loses, even with a higher seq', () => {
    // A straggling frame from a superseded attempt must never regress the card back to it.
    expect(acceptLiveJobState({ seq: 2, attempt: 2 }, { seq: 99, attempt: 1 })).toBe(false)
  })

  it('falls back to seq comparison when attempt is missing on either side', () => {
    expect(acceptLiveJobState({ seq: 5 }, { seq: 6, attempt: 2 })).toBe(true)
    expect(acceptLiveJobState({ seq: 5, attempt: 1 }, { seq: 3 })).toBe(false)
    expect(acceptLiveJobState({}, { seq: 1 })).toBe(true)
  })

  it('accepts when seq is missing on either side — nothing to compare, do not block progress', () => {
    expect(acceptLiveJobState({ attempt: 1 }, { attempt: 1, phase: 'discovering' })).toBe(true)
    expect(acceptLiveJobState({ seq: 5, attempt: 1 }, { attempt: 1, phase: 'done' })).toBe(true)
  })
})
