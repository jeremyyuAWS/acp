import { describe, it, expect } from 'vitest'
import { nextFallbackInterval, FALLBACK_BACKOFF_CAP_TICKS } from './fallbackPollBackoff.js'

describe('nextFallbackInterval', () => {
  it('resets to 1 (poll every tick) the instant the job state changes', () => {
    expect(nextFallbackInterval(true, 5)).toBe(1)
    expect(nextFallbackInterval(true, 1)).toBe(1)
  })

  it('grows by one tick at a time when unchanged', () => {
    expect(nextFallbackInterval(false, 1)).toBe(2)
    expect(nextFallbackInterval(false, 2)).toBe(3)
    expect(nextFallbackInterval(false, 3)).toBe(4)
  })

  it('caps at FALLBACK_BACKOFF_CAP_TICKS rather than growing forever', () => {
    expect(nextFallbackInterval(false, FALLBACK_BACKOFF_CAP_TICKS)).toBe(FALLBACK_BACKOFF_CAP_TICKS)
    expect(nextFallbackInterval(false, FALLBACK_BACKOFF_CAP_TICKS + 10)).toBe(FALLBACK_BACKOFF_CAP_TICKS)
  })

  it('a full unchanged run climbs monotonically from 1 to the cap and stays there', () => {
    let interval = 1
    const seen = [interval]
    for (let i = 0; i < 10; i++) { interval = nextFallbackInterval(false, interval); seen.push(interval) }
    expect(seen).toEqual([1, 2, 3, 4, 5, 5, 5, 5, 5, 5, 5])
  })
})
