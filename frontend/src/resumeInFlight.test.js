import { describe, it, expect } from 'vitest'
import { remediationResume, assessResume } from './resumeInFlight.js'

// The decision these make: is there a run to rejoin, and what denominator does the card use?
//
// Sign out is a total wipe of client state (App.jsx: every `acp-` sessionStorage key, then
// sessionStorage.clear() and a hard reload), and the jobs do not stop — the queue is durable and
// server-side. Discovery already reconnects through GET /scans/active; these give Assess and
// Remediate the same thing, from snapshots they already fetch.

describe('remediationResume', () => {
  it('rejoins a running batch, with the batch size as the denominator', () => {
    expect(remediationResume({ in_flight: 132, batch_documents: 142, failed: 0 })).toEqual({
      total: 142, done: 10, failed: 0, latest: null,
    })
  })

  it('does not resume a batch that has finished', () => {
    expect(remediationResume({ in_flight: 0, batch_documents: 142, failed: 3 })).toBeNull()
  })

  it('does not resume a scan that has never been remediated', () => {
    expect(remediationResume({ in_flight: 0, batch_documents: 0 })).toBeNull()
    expect(remediationResume({})).toBeNull()
    expect(remediationResume(null)).toBeNull()
  })

  it('falls back to the in-flight count when the snapshot carries no batch size', () => {
    // A backend that predates batch_documents. A floor for the denominator is honest; inventing
    // a batch size is not, and dividing by zero would render the bar as complete.
    expect(remediationResume({ in_flight: 40 })).toEqual({
      total: 40, done: 0, failed: 0, latest: null,
    })
  })

  it('never reports more failures than the batch holds', () => {
    // The clamp every failure count reaching this UI gets: a batch of N cannot fail more than N
    // times, and the summary line subtracts — that is the -147 shape.
    expect(remediationResume({ in_flight: 10, batch_documents: 147, failed: 294 }).failed).toBe(147)
  })

  it('treats a missing or malformed count as no work rather than NaN', () => {
    expect(remediationResume({ in_flight: null })).toBeNull()
    expect(remediationResume({ in_flight: -5 })).toBeNull()
    const r = remediationResume({ in_flight: 3, batch_documents: 'oops' })
    expect(r.total).toBe(3)
    expect(Number.isNaN(r.done)).toBe(false)
  })

  it('carries the latest fixed file through, so the card is not blank on rejoin', () => {
    expect(remediationResume({ in_flight: 5, batch_documents: 8, latest_file: 'report.docx' })
      .latest).toBe('report.docx')
  })
})

describe('assessResume', () => {
  const snap = (over = {}) => ({
    available: true, active: true, phase: 'assessing',
    totals: { discovered: 300, eligible: 142 }, kpis: { completed: 18 }, ...over,
  })

  it('rejoins an active run at the count the server reports', () => {
    expect(assessResume(snap())).toEqual({ total: 142, done: 18, phase: 'assessing' })
  })

  it('defers to the snapshot on whether the run is active', () => {
    // `available` and `active` are the server's judgement — re-deriving them from state strings
    // here is how a card ends up disagreeing with the run it is describing.
    expect(assessResume(snap({ active: false }))).toBeNull()
    expect(assessResume({ available: false, reason: 'scan_not_found' })).toBeNull()
    expect(assessResume(null)).toBeNull()
  })

  it('does not let completed exceed the eligible denominator', () => {
    expect(assessResume(snap({ kpis: { completed: 999 } })).done).toBe(142)
  })

  it('survives a snapshot whose denominator has not been derived yet', () => {
    // Preparing: eligible is not known. Resuming with 0/0 is right — the run IS active, and the
    // screen shows the phase rather than a fabricated total.
    const r = assessResume(snap({ phase: 'preparing', totals: {}, kpis: {} }))
    expect(r).toEqual({ total: 0, done: 0, phase: 'preparing' })
  })
})
