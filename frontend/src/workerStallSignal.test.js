import { describe, it, expect } from 'vitest'
import { queuedAgeSecs, isQueueStalled, STALL_THRESHOLD_S } from './workerStallSignal.js'

const NOW = Date.parse('2026-08-29T02:00:00Z')

describe('queuedAgeSecs', () => {
  it('is null when nothing is queued', () => {
    expect(queuedAgeSecs(null, NOW)).toBeNull()
    expect(queuedAgeSecs(undefined, NOW)).toBeNull()
  })

  it('is the elapsed seconds since createdAt', () => {
    const createdAt = new Date(NOW - 45_000).toISOString()
    expect(queuedAgeSecs(createdAt, NOW)).toBe(45)
  })

  it('never goes negative on a small clock skew (createdAt fractionally in the future)', () => {
    const createdAt = new Date(NOW + 500).toISOString()
    expect(queuedAgeSecs(createdAt, NOW)).toBe(0)
  })

  it('is null for an unparseable timestamp', () => {
    expect(queuedAgeSecs('not-a-date', NOW)).toBeNull()
  })
})

describe('isQueueStalled', () => {
  it('is false when the worker tier is offline — a different, already-visible problem', () => {
    const createdAt = new Date(NOW - (STALL_THRESHOLD_S + 30) * 1000).toISOString()
    expect(isQueueStalled(false, createdAt, NOW)).toBe(false)
  })

  it('is false when alive and nothing is queued', () => {
    expect(isQueueStalled(true, null, NOW)).toBe(false)
  })

  it('is false when alive and the oldest queued job is still within the threshold', () => {
    const createdAt = new Date(NOW - (STALL_THRESHOLD_S - 10) * 1000).toISOString()
    expect(isQueueStalled(true, createdAt, NOW)).toBe(false)
  })

  it('is true once alive and the oldest queued job has crossed the threshold', () => {
    const createdAt = new Date(NOW - (STALL_THRESHOLD_S + 1) * 1000).toISOString()
    expect(isQueueStalled(true, createdAt, NOW)).toBe(true)
  })

  it('is true exactly at the threshold', () => {
    const createdAt = new Date(NOW - STALL_THRESHOLD_S * 1000).toISOString()
    expect(isQueueStalled(true, createdAt, NOW)).toBe(true)
  })
})
