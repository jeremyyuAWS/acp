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

  it('carries the degraded reasons through so the run can show why it started degraded', () => {
    const r = preflightVerdict({ verdict: 'degraded', degraded_reasons: ['queue has 60 jobs waiting'] })
    expect(r.degradedReasons).toEqual(['queue has 60 jobs waiting'])
  })

  it('does not block on a ready verdict, and carries no degraded reasons', () => {
    const r = preflightVerdict({ verdict: 'ready' })
    expect(r.blocked).toBe(false)
    expect(r.degradedReasons).toEqual([])
  })

  it('a blocked verdict carries no degraded reasons — the run never starts, so nothing to show', () => {
    const r = preflightVerdict({ verdict: 'blocked', blocked_reasons: ['no_workers'] })
    expect(r.degradedReasons).toEqual([])
  })

  it('fails open (never blocks) on an unrecognized future verdict value', () => {
    const r = preflightVerdict({ verdict: 'some-new-verdict', degraded_reasons: ['x'] })
    expect(r.blocked).toBe(false)
  })

  it('does not block when the preflight call itself failed (null response)', () => {
    // A failed CALL (network hiccup, endpoint down) must never itself block a scan — only an
    // actual 'blocked' verdict does. startScanQueued's own worker_tier_alive check is the
    // fallback if this check could not run at all.
    expect(preflightVerdict(null).blocked).toBe(false)
    expect(preflightVerdict(undefined).blocked).toBe(false)
    expect(preflightVerdict(null).degradedReasons).toEqual([])
  })
})
