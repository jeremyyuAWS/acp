import { describe, it, expect } from 'vitest'
import { recordSample, estimate, etaRangeText } from './throughputEta.js'

// Build a history: n samples, `step` done per `dtMs`, starting at t0.
function series(points) { return points.map(([done, at]) => ({ done, at })) }

describe('recordSample', () => {
  it('appends points and returns a new array (no mutation)', () => {
    const h0 = []
    const h1 = recordSample(h0, 5, 1000)
    expect(h1).toEqual([{ done: 5, at: 1000 }])
    expect(h0).toEqual([])
  })
  it('ignores a repeat poll with the same done within 500ms', () => {
    let h = recordSample([], 5, 1000)
    h = recordSample(h, 5, 1200)                     // same done, +200ms → dropped
    expect(h.length).toBe(1)
    h = recordSample(h, 5, 2000)                     // same done but +1000ms → kept (time moved)
    expect(h.length).toBe(2)
  })
  it('prunes to the rolling window', () => {
    let h = [{ done: 0, at: 0 }, { done: 5, at: 5000 }]
    h = recordSample(h, 40, 70_000, { windowMs: 60_000 })   // now=70s → drop anything before 10s
    expect(h.every((s) => s.at >= 10_000)).toBe(true)
  })
})

describe('estimate', () => {
  it('is calibrating until there are enough samples over enough time', () => {
    expect(estimate(series([[0, 0], [2, 3000]]), 100).calibrating).toBe(true)   // too few
    // 4 samples but only 9s span (< 12s min) → still calibrating
    const short = series([[0, 0], [1, 3000], [2, 6000], [3, 9000]])
    expect(estimate(short, 100).calibrating).toBe(true)
  })

  it('gives a rate and an ETA range once stable (uniform speed → tight range)', () => {
    const h = series([[0, 0], [5, 5000], [10, 10000], [15, 15000], [20, 20000]])  // 1/sec
    const e = estimate(h, 600)
    expect(e.calibrating).toBe(false)
    expect(e.ratePerMin).toBe(60)
    expect(e.eta.lowSec).toBe(600)
    expect(e.eta.highSec).toBe(600)
    expect(etaRangeText(e.eta)).toBe('about 10 min left')
  })

  it('a VARIABLE speed produces a wider range (honest uncertainty), low < high', () => {
    const h = series([[0, 0], [2, 5000], [4, 10000], [12, 15000], [20, 20000]])  // slow then fast
    const e = estimate(h, 600)
    expect(e.calibrating).toBe(false)
    expect(e.eta.lowSec).toBeLessThan(e.eta.highSec)
    expect(etaRangeText(e.eta)).toMatch(/about \d+–\d+ min left/)
  })

  it('a stalled run (no progress across the window) yields NO ETA, not a fake number', () => {
    const h = series([[5, 0], [5, 5000], [5, 10000], [5, 15000]])   // done never moves
    const e = estimate(h, 100)
    expect(e.eta).toBeNull()
    expect(e.calibrating).toBe(true)
  })

  it('remaining 0 reads as almost done', () => {
    const h = series([[0, 0], [5, 5000], [10, 10000], [20, 20000]])
    expect(estimate(h, 0).eta).toEqual({ lowSec: 0, highSec: 0 })
    expect(etaRangeText({ lowSec: 0, highSec: 0 })).toBe('almost done')
  })
})

describe('etaRangeText', () => {
  it('formats short/edge cases honestly', () => {
    expect(etaRangeText(null)).toBeNull()
    expect(etaRangeText({ lowSec: 30, highSec: 60 })).toBe('under a minute left')
    expect(etaRangeText({ lowSec: 300, highSec: 300 })).toBe('about 5 min left')
  })
})
