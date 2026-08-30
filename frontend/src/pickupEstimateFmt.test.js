import { describe, it, expect } from 'vitest'
import { fmtPickupRange } from './pickupEstimateFmt.js'

describe('fmtPickupRange', () => {
  it('renders a range when earliest and latest differ', () => {
    const now = Date.now()
    expect(fmtPickupRange(
      new Date(now + 2 * 60000).toISOString(),
      new Date(now + 4 * 60000).toISOString(),
    )).toBe('2–4 min')
  })

  it('renders "about N min" when earliest and latest round to the same minute', () => {
    const now = Date.now()
    expect(fmtPickupRange(
      new Date(now + 3 * 60000).toISOString(),
      new Date(now + 3 * 60000 + 5000).toISOString(),
    )).toBe('about 3 min')
  })

  it('renders "under a minute" once the range has collapsed to zero', () => {
    const now = Date.now()
    expect(fmtPickupRange(
      new Date(now + 10000).toISOString(),
      new Date(now + 20000).toISOString(),
    )).toBe('under a minute')
  })

  it('floors a past earliest_at at zero rather than going negative', () => {
    const now = Date.now()
    expect(fmtPickupRange(
      new Date(now - 60000).toISOString(),
      new Date(now + 2 * 60000).toISOString(),
    )).toBe('0–2 min')
  })
})
