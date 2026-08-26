import { describe, it, expect } from 'vitest'
import { preflightVerdict } from './discoveryPreflightGate.js'

describe('preflightVerdict', () => {
  it('blocks on worker_tier_never_started — infrastructure never set up', () => {
    const r = preflightVerdict({
      verdict: 'blocked',
      capacity_state: 'unavailable',
      blocked_reasons: ['worker_tier_never_started'],
    })
    expect(r.blocked).toBe(true)
    expect(r.reason).toBe('worker_tier_never_started')
    expect(r.capacityState).toBe('unavailable')
  })

  it('falls back to a generic reason when blocked_reasons is empty', () => {
    const r = preflightVerdict({ verdict: 'blocked', blocked_reasons: [] })
    expect(r.blocked).toBe(true)
    expect(r.reason).toBe('this source is not currently reachable')
  })

  it('does NOT block when no_workers — workers were seen before, queue is durable', () => {
    // no_workers is now a degraded_reason, not a blocked_reason.
    // Scans can be queued and will start when a worker comes up.
    const r = preflightVerdict({
      verdict: 'degraded',
      capacity_state: 'starting',
      degraded_reasons: ['no_workers'],
    })
    expect(r.blocked).toBe(false)
    expect(r.capacityState).toBe('starting')
    expect(r.degradedReasons).toContain('no_workers')
  })

  it('does not block on a degraded verdict — a queue backlog must not stop the scan', () => {
    const r = preflightVerdict({
      verdict: 'degraded',
      capacity_state: 'busy',
      degraded_reasons: ['queue has 60 jobs waiting'],
    })
    expect(r.blocked).toBe(false)
    expect(r.reason).toBe(null)
    expect(r.capacityState).toBe('busy')
  })

  it('carries the degraded reasons through so the run can show why it started degraded', () => {
    const r = preflightVerdict({ verdict: 'degraded', degraded_reasons: ['queue has 60 jobs waiting'] })
    expect(r.degradedReasons).toEqual(['queue has 60 jobs waiting'])
  })

  it('does not block on a ready verdict, and carries no degraded reasons', () => {
    const r = preflightVerdict({ verdict: 'ready', capacity_state: 'ready' })
    expect(r.blocked).toBe(false)
    expect(r.capacityState).toBe('ready')
    expect(r.degradedReasons).toEqual([])
  })

  it('a blocked verdict carries no degraded reasons — the run never starts', () => {
    const r = preflightVerdict({
      verdict: 'blocked',
      capacity_state: 'unavailable',
      blocked_reasons: ['worker_tier_never_started'],
    })
    expect(r.degradedReasons).toEqual([])
  })

  it('fails open (never blocks) on an unrecognized future verdict value', () => {
    const r = preflightVerdict({ verdict: 'some-new-verdict', degraded_reasons: ['x'] })
    expect(r.blocked).toBe(false)
  })

  it('does not block when the preflight call itself failed (null response)', () => {
    expect(preflightVerdict(null).blocked).toBe(false)
    expect(preflightVerdict(undefined).blocked).toBe(false)
    expect(preflightVerdict(null).degradedReasons).toEqual([])
  })

  it('returns unknown capacityState when field absent (older API response)', () => {
    const r = preflightVerdict({ verdict: 'ready' })
    expect(r.capacityState).toBe('unknown')
  })
})
