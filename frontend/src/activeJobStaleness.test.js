import { describe, it, expect } from 'vitest'
import { isActiveJobStale, ACTIVE_JOB_STALE_MS } from './activeJobStaleness.js'

describe('isActiveJobStale', () => {
  it('is not stale for a job pending well within the window', () => {
    const now = Date.now()
    expect(isActiveJobStale(now - 60000, now)).toBe(false)
  })

  it('is not stale exactly at the threshold', () => {
    const now = Date.now()
    expect(isActiveJobStale(now - ACTIVE_JOB_STALE_MS, now)).toBe(false)
  })

  it('is stale once past the threshold', () => {
    const now = Date.now()
    expect(isActiveJobStale(now - ACTIVE_JOB_STALE_MS - 1, now)).toBe(true)
  })

  it('is not stale for a missing timestamp — a session from before this fix existed', () => {
    expect(isActiveJobStale(null)).toBe(false)
    expect(isActiveJobStale(undefined)).toBe(false)
    expect(isActiveJobStale(0)).toBe(false)
    expect(isActiveJobStale(NaN)).toBe(false)
  })

  it('honours a custom stale window', () => {
    const now = Date.now()
    expect(isActiveJobStale(now - 5000, now, 1000)).toBe(true)
    expect(isActiveJobStale(now - 500, now, 1000)).toBe(false)
  })
})
