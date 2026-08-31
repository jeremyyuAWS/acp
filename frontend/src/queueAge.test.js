/**
 * A run's age comes from the server's timestamp, or it is not shown as a number.
 *
 * THE DEFECT, two halves of the same mistake:
 *
 *   1. DiscoverRunProgress anchored its clock to MOUNT —
 *        const [startedAt] = useState(() => Date.now())
 *      — so navigating to another tab and back remounted the component and restarted the age at
 *      zero. A scan five minutes in read as "0s" the moment you looked away and back, which is
 *      exactly when someone is checking whether it is stuck.
 *
 *   2. The queued line already preferred the server instant, but with a SILENT fallback —
 *        const waitedSecs = secsSince(progress.started_at) ?? elapsed
 *      — which substituted that same mount-relative number and rendered it in identical words
 *      ("created 4s ago"). A fabricated age indistinguishable from a real one is worse than no
 *      age: nobody can tell it is wrong.
 */
import { describe, it, expect } from 'vitest'
import { secondsSince, deriveRunAge, ageText } from './queueAge.js'

const fmt = (s) => `${s}s`
const NOW = Date.parse('2026-08-31T06:00:00Z')
const iso = (secsAgo) => new Date(NOW - secsAgo * 1000).toISOString()

describe('secondsSince', () => {
  it('measures from the persisted instant', () => {
    expect(secondsSince(iso(240), NOW)).toBe(240)
  })

  it('is null with no timestamp — there is nothing to measure from', () => {
    expect(secondsSince(null, NOW)).toBeNull()
    expect(secondsSince(undefined, NOW)).toBeNull()
    expect(secondsSince('', NOW)).toBeNull()
  })

  it('is null for an unparseable timestamp rather than NaN seconds', () => {
    expect(secondsSince('not-a-date', NOW)).toBeNull()
  })

  it('clamps at zero, so clock skew never renders a negative age', () => {
    expect(secondsSince(iso(-30), NOW)).toBe(0)
  })
})

describe('deriveRunAge', () => {
  it('reports the source as server when there is a real instant', () => {
    expect(deriveRunAge({ startedAt: iso(90), now: NOW })).toEqual({ seconds: 90, source: 'server' })
  })

  it('reports unavailable with NO number when there is not', () => {
    // The number being null is the safety property: a caller cannot render an unavailable age as
    // a real one, because there is nothing to render.
    expect(deriveRunAge({ startedAt: null, now: NOW }))
      .toEqual({ seconds: null, source: 'unavailable' })
  })

  it('is unavailable when called with nothing at all', () => {
    expect(deriveRunAge().source).toBe('unavailable')
  })

  it('does not change when the reading is repeated from a later mount', () => {
    // THE regression. Two observations of the SAME run at the same instant must agree, however
    // many times the component has been mounted in between.
    const at = iso(300)
    expect(deriveRunAge({ startedAt: at, now: NOW }).seconds)
      .toBe(deriveRunAge({ startedAt: at, now: NOW }).seconds)
  })

  it('keeps counting up across a remount rather than restarting', () => {
    const at = iso(300)
    const before = deriveRunAge({ startedAt: at, now: NOW }).seconds
    const afterRemount = deriveRunAge({ startedAt: at, now: NOW + 60000 }).seconds
    expect(afterRemount).toBe(before + 60)
    expect(afterRemount).toBeGreaterThan(0)     // not reset to zero, which is what mount did
  })
})

describe('ageText', () => {
  it('says the time is unavailable instead of inventing one', () => {
    expect(ageText(deriveRunAge({ startedAt: null }), fmt)).toBe('submission time unavailable')
  })

  it('never emits a bare number for an unavailable age', () => {
    // Belt and braces against the old shape: even a caller that formats it cannot get digits out.
    expect(ageText({ seconds: null, source: 'unavailable' }, fmt)).not.toMatch(/\d/)
  })

  it('formats a real age with the caller\'s formatter', () => {
    expect(ageText(deriveRunAge({ startedAt: iso(45), now: NOW }), fmt)).toBe('45s ago')
  })

  it('refuses a malformed age object rather than trusting its number', () => {
    // `seconds` present but source not 'server' means somebody built it by hand. Distrust it.
    expect(ageText({ seconds: 12, source: 'unavailable' }, fmt)).toBe('submission time unavailable')
    expect(ageText(null, fmt)).toBe('submission time unavailable')
  })
})
