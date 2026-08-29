import { describe, it, expect } from 'vitest'
import { shouldAnimate, deltaFor, ease, interpolate } from './liveCounterAnim.js'

describe('shouldAnimate', () => {
  it('is false for the first value a counter ever receives (nothing to count up from)', () => {
    expect(shouldAnimate(null, 5)).toBe(false)
  })

  it('is true for an ordinary increase', () => {
    expect(shouldAnimate(10, 24)).toBe(true)
  })

  it('is false for a decrease — a correction, not progress', () => {
    expect(shouldAnimate(24, 10)).toBe(false)
  })

  it('is false when the value is unchanged', () => {
    expect(shouldAnimate(10, 10)).toBe(false)
  })

  it('is false when next is null (a caller passing an absent signal)', () => {
    expect(shouldAnimate(10, null)).toBe(false)
  })
})

describe('deltaFor', () => {
  it('is the positive difference on an increase', () => {
    expect(deltaFor(1009, 1033)).toBe(24)
  })

  it('is null on a decrease — never a negative delta badge', () => {
    expect(deltaFor(1033, 1009)).toBeNull()
  })

  it('is null when unchanged', () => {
    expect(deltaFor(10, 10)).toBeNull()
  })

  it('is null on the first value (prev is null)', () => {
    expect(deltaFor(null, 10)).toBeNull()
  })
})

describe('ease', () => {
  it('starts at 0 and ends at 1', () => {
    expect(ease(0)).toBe(0)
    expect(ease(1)).toBe(1)
  })

  it('clamps outside [0,1]', () => {
    expect(ease(-1)).toBe(0)
    expect(ease(2)).toBe(1)
  })

  it('is monotonically increasing', () => {
    expect(ease(0.25)).toBeLessThan(ease(0.5))
    expect(ease(0.5)).toBeLessThan(ease(0.75))
  })
})

describe('interpolate', () => {
  it('is exactly `from` at elapsed 0', () => {
    expect(interpolate(1000, 1100, 0, 400)).toBe(1000)
  })

  it('is exactly `to` once elapsed reaches the duration', () => {
    expect(interpolate(1000, 1100, 400, 400)).toBe(1100)
  })

  it('is exactly `to` once elapsed exceeds the duration (a late tick never overshoots)', () => {
    expect(interpolate(1000, 1100, 900, 400)).toBe(1100)
  })

  it('is `to` immediately for a zero or negative duration — no animation, no divide-by-zero', () => {
    expect(interpolate(1000, 1100, 0, 0)).toBe(1100)
  })

  it('is strictly between from and to partway through', () => {
    const mid = interpolate(1000, 1100, 200, 400)
    expect(mid).toBeGreaterThan(1000)
    expect(mid).toBeLessThan(1100)
  })
})
