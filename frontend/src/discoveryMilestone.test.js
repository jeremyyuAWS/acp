import { describe, it, expect } from 'vitest'
import { nextMilestone } from './discoveryMilestone.js'

describe('nextMilestone', () => {
  it('is null below the first threshold', () => {
    expect(nextMilestone(999, 0)).toBeNull()
  })

  it('announces the first thousand once crossed', () => {
    expect(nextMilestone(1000, 0)).toBe(1000)
  })

  it('is null again once that threshold has been announced', () => {
    expect(nextMilestone(1450, 1000)).toBeNull()
  })

  it('announces the next thousand once crossed', () => {
    expect(nextMilestone(2003, 1000)).toBe(2000)
  })

  it('jumps straight to the highest threshold crossed, not one per thousand skipped', () => {
    // A poll tick can land after several thousand were found between ticks — one announcement,
    // not a queue of five, matches "announce only meaningful milestones" rather than replaying
    // every one that was technically crossed.
    expect(nextMilestone(5200, 1000)).toBe(5000)
  })

  it('is null for a null or undefined count', () => {
    expect(nextMilestone(null, 0)).toBeNull()
    expect(nextMilestone(undefined, 0)).toBeNull()
  })

  it('is null on a decrease relative to what was already announced', () => {
    expect(nextMilestone(1800, 2000)).toBeNull()
  })
})
