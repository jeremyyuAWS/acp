import { describe, it, expect } from 'vitest'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import RemediationRunCard from './RemediationRunCard.jsx'
import RemediationOpsPanel from './RemediationOpsPanel.jsx'
import { etaGate } from './remediationRunCard.js'

// WHAT THE BIG NUMBER IS ALLOWED TO CLAIM.
//
// `total - processing - waiting` counts documents that are neither in flight nor queued:
// completed, review, failed, skipped. Exactly one of those four is a document that came out
// fixed. The headline called it "processed", and on a real run — 70 documents, 18 active, 12
// blocked, 40 waiting — it rendered "12 of 70 documents processed" with `completed` at ZERO.
// Every one of the twelve had been routed to review or skipped and nothing was remediated.
//
// The numerator is right and stays: counting `completed` alone would freeze a legitimately
// Skipped-heavy batch at 0 (RemediationOpsPanel says so where it derives this). What changed is
// the claim attached to it.

const zeroCompleted = {
  run_id: 'scan-1', scan_id: 'scan-1', revision: 1, generated_at: '2026-09-06T12:00:00.000Z',
  state: 'needs_attention', message: 'Review required', terminal: false,
  source: { provider: 'drive', provider_label: 'Google Drive', breadcrumb: 'Google Drive' },
  total_documents: 70,
  // The screenshot's run, exactly: nothing completed, twelve blocked, eighteen in flight.
  documents: { completed: 0, processing: 18, waiting: 40, review: 11, failed: 0, skipped: 1 },
  fixes: { applied: 73, verified: 73, verification_failures: 0, documents_verified: 23 },
  delivery: { stored: 60, delivered: 60, pending: 10, awaiting_release: 0, eligible: 60,
              latest_at: null },
  review: { documents: 11, items: 14 }, phases: [],
  thresholds: { stall_after_s: 900, heartbeat_s: 15, delayed_after_s: 60 },
  integrity: { ok: true, violations: [], affected: [] },
}

const card = (snapshot) => renderToStaticMarkup(
  createElement(RemediationRunCard, { snapshot, connected: true }))
const panel = (snapshot) => renderToStaticMarkup(
  createElement(RemediationOpsPanel, { snapshot, connected: true, receivedAt: Date.now() }))
const text = (html) => html.replace(/<[^>]*>/g, '')


describe('the run headline does not claim work it has not done', () => {
  it('does not say "documents processed" on a run that completed nothing', () => {
    // The exact string that overstated it. Asserted as an absence, because the number beside it
    // is correct — it was only ever the noun that was wrong.
    expect(text(card(zeroCompleted))).not.toMatch(/\d+ of \d+ documents processed/)
    expect(text(panel(zeroCompleted))).not.toMatch(/\d+ of \d+ documents processed/)
  })

  it('says what the count actually means, on both surfaces', () => {
    expect(text(card(zeroCompleted))).toContain('12 of 70 documents through automatic processing')
    expect(text(panel(zeroCompleted))).toContain('12 of 70 documents through automatic processing')
  })

  it('KEEPS the number — this is a wording fix, not a change of numerator', () => {
    // The guard against a later "fix" that swaps in `completed`: that would report 0 of 70 on a
    // run with eighteen documents actively being worked, and freeze a Skipped-heavy batch at zero
    // forever. total - processing - waiting = 70 - 18 - 40 = 12.
    expect(text(card(zeroCompleted))).toContain('12 of 70')
    expect(text(card(zeroCompleted))).not.toContain('0 of 70')
  })

  it('still counts every terminal outcome, not just the successful one', () => {
    const oneCompleted = { ...zeroCompleted,
      documents: { completed: 1, processing: 18, waiting: 40, review: 10, failed: 0, skipped: 1 } }
    // Same twelve: one completed now, one fewer in review. The headline must not move, because
    // the same number of documents have been through automatic processing.
    expect(text(card(oneCompleted))).toContain('12 of 70 documents through automatic processing')
  })
})


describe('the ETA basis names the same thing the headline does', () => {
  const throughput = { calibrating: false, etaText: '8–12 minutes', ratePerMin: 6 }

  it('does not describe its sample as processed documents', () => {
    const gate = etaGate(zeroCompleted, throughput)
    expect(gate.show).toBe(true)
    expect(gate.basis).not.toContain('processed documents')
  })

  it('uses the headline\'s wording, so the two numbers read as one fact', () => {
    // They ARE one fact: `completed + review + failed + skipped` equals
    // `total - processing - waiting` because the six counters partition the scope. Two names for
    // it on the same card is how a reader concludes they are different measurements.
    expect(etaGate(zeroCompleted, throughput).basis)
      .toBe('based on 12 documents through automatic processing')
  })

  it('still withholds an estimate below the five-document floor', () => {
    const few = { ...zeroCompleted,
      documents: { completed: 0, processing: 18, waiting: 48, review: 4, failed: 0, skipped: 0 } }
    expect(etaGate(few, throughput)).toEqual(
      { show: false, note: 'Estimating after the first results' })
  })
})
