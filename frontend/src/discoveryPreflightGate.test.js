import { describe, it, expect } from 'vitest'
import { preflightVerdict } from './discoveryPreflightGate.js'

describe('preflightVerdict', () => {
  it('blocks on a blocked verdict, surfacing the first blocked reason', () => {
    const r = preflightVerdict({ verdict: 'blocked', blocked_reasons: ['no_workers', 'other'] })
    expect(r.blocked).toBe(true)
    expect(r.reason).toBe('no_workers')
  })

  it('falls back to a generic reason when blocked_reasons is empty', () => {
    const r = preflightVerdict({ verdict: 'blocked', blocked_reasons: [] })
    expect(r.blocked).toBe(true)
    expect(r.reason).toBe('this source is not currently reachable')
  })

  it('does not block on a degraded verdict — a queue backlog must not stop the scan', () => {
    const r = preflightVerdict({ verdict: 'degraded', degraded_reasons: ['queue has 60 jobs waiting'] })
    expect(r.blocked).toBe(false)
    expect(r.reason).toBe(null)
  })

  it('does not block on a ready verdict', () => {
    expect(preflightVerdict({ verdict: 'ready' }).blocked).toBe(false)
  })

  it('does not block when the preflight call itself failed (null response)', () => {
    // A failed CALL (network hiccup, endpoint down) must never itself block a scan — only an
    // actual 'blocked' verdict does. startScanQueued's own worker_tier_alive check is the
    // fallback if this check could not run at all.
    expect(preflightVerdict(null).blocked).toBe(false)
    expect(preflightVerdict(undefined).blocked).toBe(false)
  })
})
