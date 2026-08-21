/**
 * The demo estate must read like a real one, not a broken drive.
 *
 * "Failed to open" (status='error') is a rare, real event — a password-protected, corrupt or
 * unsupported file. The SIM used to seed it at ~14% (one status-cycle slot in ten, plus a modulo),
 * so an assess run over 22 documents showed 18 of them "could not be opened" — which reads as a
 * systemic outage, not an estate. This pins the rate low so a future edit cannot quietly re-inflate
 * it, while keeping ENOUGH errors that the "failed to open" panel still has something to show.
 */
import { describe, it, expect } from 'vitest'
import { CORPUS } from './sim.js'

describe('the simulated estate seeds a realistic could-not-open rate', () => {
  const total = CORPUS.length
  const errors = CORPUS.filter((f) => f.status === 'error')

  it('has a substantial estate to reason about', () => {
    expect(total).toBeGreaterThan(100)
  })

  it('seeds a handful of failed-to-open documents, not a sixth of the drive', () => {
    // A realistic estate loses 1-3% of documents to unreadability. Well under 5% is the guardrail;
    // the old 14% is what this exists to prevent.
    expect(errors.length).toBeGreaterThan(0)          // the panel still populates
    expect(errors.length / total).toBeLessThan(0.05)  // …but it never reads as an outage
  })

  it('gives every failed-to-open document a reason and no score', () => {
    // The panel names each one with why; a document ACP never read has no score, ever.
    for (const f of errors) {
      expect(f.openIssue, `${f.file} failed to open with no reason`).toBeTruthy()
      expect(f.score, `${f.file} failed to open but carries a score`).toBeNull()
    }
  })
})
