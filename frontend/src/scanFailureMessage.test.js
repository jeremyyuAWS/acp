import { describe, it, expect } from 'vitest'
import { scanFailureDetail, hasFallbackInventory } from './scanFailureMessage.js'

describe('scanFailureDetail', () => {
  it('replaces a bare HTTP status with a plain-language explanation, keeping the code', () => {
    expect(scanFailureDetail('500')).toMatch(/HTTP 500/)
    expect(scanFailureDetail('500')).not.toMatch(/^500$/)
  })

  it('handles the exact shape api.js throws for an empty statusText (a trailing space)', () => {
    // `${r.status} ${r.statusText}` with statusText === '' — the real shape found live 2026-08-29.
    expect(scanFailureDetail('500 ')).toMatch(/HTTP 500/)
  })

  it('says the problem is usually temporary, not just restating the code', () => {
    expect(scanFailureDetail('502')).toMatch(/temporary/i)
  })

  it('leaves a purpose-written message untouched', () => {
    const msg = 'no workers available — the worker service looks down; check Monitor'
    expect(scanFailureDetail(msg)).toBe(msg)
  })

  it('leaves other purpose-written messages untouched, including ones with a numeric scan id', () => {
    const msg = "can't start this scan — source token expired"
    expect(scanFailureDetail(msg)).toBe(msg)
  })

  it('does not false-positive on a message that merely contains digits later in the string', () => {
    const msg = 'this scan never started — the queue may be stuck. Try again, or check Monitor.'
    expect(scanFailureDetail(msg)).toBe(msg)
  })

  it('handles null/undefined without throwing', () => {
    expect(scanFailureDetail(null)).toBe('')
    expect(scanFailureDetail(undefined)).toBe('')
  })
})

describe('hasFallbackInventory', () => {
  it('is true when a previous scan has a real completion timestamp', () => {
    expect(hasFallbackInventory(null, '2026-08-28T16:07:00+00:00')).toBe(true)
  })

  it('is true from discovered_at alone — a Discover-only run under ADR 0020 has no completed_at yet', () => {
    // Found live 2026-08-30: a run that finished Discovery but hasn't been Assessed shows a real
    // "Discovery complete" card (Discover.jsx gates that on discovered_at/status, never
    // completed_at) while completed_at itself stays null until the whole pipeline finishes.
    expect(hasFallbackInventory('2026-08-30T14:44:00+00:00', null)).toBe(true)
  })

  it('is true when both timestamps are present', () => {
    expect(hasFallbackInventory('2026-08-28T14:00:00+00:00', '2026-08-28T16:07:00+00:00')).toBe(true)
  })

  it('is false when there is nothing to fall back on', () => {
    expect(hasFallbackInventory(null, null)).toBe(false)
    expect(hasFallbackInventory(undefined, undefined)).toBe(false)
  })
})
