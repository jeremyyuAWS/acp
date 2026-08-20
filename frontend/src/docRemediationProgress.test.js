import { describe, it, expect } from 'vitest'
import {
  STAGES, STAGE_KEYS, findingStage, docRemediationProgress, remainingSummary, allBlocked,
} from './docRemediationProgress.js'
import { workflowStatusOf } from './remediationInboxModel.js'

// R7 — the per-document pipeline. Two things are pinned hardest: that the stage precedence is the
// SHIPPED one (workflowStatusOf) rather than a second opinion, and that the one place it deliberately
// differs — splitting `completed` — is the split that stops "settled with no fix" being counted as
// "the re-scan confirmed it".

const F = (over) => ({ id: over.id ?? 1, file: 'plan.docx', rule_id: 'SC_1_3_1', ...over })

describe('findingStage', () => {
  it('renames workflowStatusOf’s buckets rather than re-deriving them', () => {
    const pairs = [
      [F({ id: 1 }), 'manual', 'authoring'],
      [F({ id: 2, after: 'A bar chart' }), 'needs-review', 'to-review'],
      [F({ id: 3, status: 'recheck' }), 'awaiting-validation', 'written'],
      [F({ id: 4, status: 'blocked' }), 'blocked', 'blocked'],
    ]
    for (const [f, workflow, stage] of pairs) {
      expect(workflowStatusOf(f, {})).toBe(workflow)   // the premise, pinned
      expect(findingStage(f, {})).toBe(stage)
    }
  })

  it('splits `completed` — a confirmed re-scan and a settled-without-a-fix are not one number', () => {
    const verified = F({ id: 5, status: 'verified' })
    const rejected = F({ id: 6 })
    const notApplicable = F({ id: 7 })
    const decisions = { 6: { state: 'rejected' }, 7: { state: 'not_applicable' } }

    // All three read `completed` on the workflow tabs. That is correct there and wrong here.
    expect(workflowStatusOf(verified, {})).toBe('completed')
    expect(workflowStatusOf(rejected, decisions)).toBe('completed')
    expect(workflowStatusOf(notApplicable, decisions)).toBe('completed')

    expect(findingStage(verified, {})).toBe('confirmed')
    expect(findingStage(rejected, decisions)).toBe('settled')
    expect(findingStage(notApplicable, decisions)).toBe('settled')
  })

  it('an accepted decision is written, not confirmed — the re-scan has not run', () => {
    expect(findingStage(F({ id: 8 }), { 8: { state: 'accepted' } })).toBe('written')
    expect(findingStage(F({ id: 9 }), { 9: { state: 'approved' } })).toBe('written')
  })

  it('an auto-applied fix nobody has acknowledged still needs the reviewer', () => {
    // laneOf puts it in the green review lane and workflowStatusOf deliberately leaves it in
    // needs-review — it is written to the copy but unconfirmed by a person. It must not read as done.
    const f = F({ id: 10, autoApplied: true })
    expect(workflowStatusOf(f, {})).toBe('needs-review')
    expect(findingStage(f, {})).toBe('to-review')
  })

  it('puts every finding in exactly one of the declared stages', () => {
    const all = [
      F({ id: 1 }), F({ id: 2, after: 'x' }), F({ id: 3, status: 'recheck' }),
      F({ id: 4, status: 'blocked' }), F({ id: 5, status: 'verified' }),
      F({ id: 6, rejectedFix: true }), F({ id: 7, autoApplied: true }),
    ]
    for (const f of all) expect(STAGE_KEYS).toContain(findingStage(f, {}))
  })
})

describe('docRemediationProgress', () => {
  const QUEUE = [
    F({ id: 1, file: 'plan.docx', after: 'A bar chart', rule_id: 'SC_1_1_1' }), // to-review
    F({ id: 2, file: 'plan.docx' }),                                            // authoring
    F({ id: 3, file: 'plan.docx', status: 'recheck' }),                         // written
    F({ id: 4, file: 'plan.docx', status: 'verified' }),                        // confirmed
    F({ id: 5, file: 'plan.docx', status: 'blocked' }),                         // blocked
    F({ id: 6, file: 'other.pdf', status: 'verified' }),                        // a different document
  ]

  it('is NULL for a queue that has not loaded — missing is not measured zero', () => {
    expect(docRemediationProgress(null, 'plan.docx')).toBeNull()
    expect(docRemediationProgress(undefined, 'plan.docx')).toBeNull()
  })

  it('an empty queue IS a measured zero, and is reported as one', () => {
    const p = docRemediationProgress([], 'plan.docx')
    expect(p).not.toBeNull()
    expect(p.total).toBe(0)
    expect(p.pct).toBeNull()          // no fraction exists — not 0%
    expect(p.complete).toBe(false)    // nothing was completed; there was nothing to complete
  })

  it('counts one document’s findings by stage, and ignores the rest of the queue', () => {
    const p = docRemediationProgress(QUEUE, 'plan.docx')
    expect(p.total).toBe(5)
    expect(p.counts).toEqual({
      'to-review': 1, authoring: 1, written: 1, confirmed: 1, settled: 0, blocked: 1,
    })
  })

  it('reports what is left by who it is waiting on', () => {
    const p = docRemediationProgress(QUEUE, 'plan.docx')
    expect(p.needsPerson).toBe(2)     // to-review + authoring
    expect(p.needsSystem).toBe(1)     // written, awaiting the re-scan
    expect(p.blocked).toBe(1)
    expect(remainingSummary(p)).toBe('2 need you · 1 awaiting the re-scan · 1 blocked')
  })

  it('prints an identity line the counts must satisfy', () => {
    const p = docRemediationProgress(QUEUE, 'plan.docx')
    expect(p.reconcile.ok).toBe(true)
    expect(p.reconcile.sum).toBe(p.total)
    expect(p.reconcile.line).toBe('1 + 1 + 1 + 1 + 0 + 1 = 5 findings')
  })

  it('holds the document at the earliest spine stage that still has work', () => {
    const p = docRemediationProgress(QUEUE, 'plan.docx')
    expect(p.at.key).toBe('to-review')

    // Clear the review work and it moves along the spine, not straight to done.
    const later = docRemediationProgress(QUEUE.filter((f) => f.id !== 1), 'plan.docx')
    expect(later.at.key).toBe('authoring')
  })

  it('a document with nothing outstanding is complete and has no held-at stage', () => {
    const p = docRemediationProgress([
      F({ id: 1, status: 'verified' }),
      F({ id: 2 }),
    ], 'plan.docx', { 2: { state: 'not_applicable' } })
    expect(p.complete).toBe(true)
    expect(p.at).toBeNull()
    expect(p.pct).toBe(100)
    expect(remainingSummary(p)).toBe('')
  })

  it('does not count a blocked finding as progress through the pipeline', () => {
    const p = docRemediationProgress([F({ id: 1, status: 'blocked' })], 'plan.docx')
    expect(p.done).toBe(0)
    expect(p.pct).toBe(0)          // a real measured zero: one finding, none through
    expect(p.complete).toBe(false)
    expect(allBlocked(p)).toBe(true)
  })

  it('a document whose remaining work is only blocked is NOT complete', () => {
    // The trap this pins: nothing is outstanding, because nothing can be done. Reporting that as
    // complete tells a reviewer the document is finished when a finding was never remediated.
    const p = docRemediationProgress([
      F({ id: 1, status: 'verified' }),
      F({ id: 2, status: 'verified' }),
      F({ id: 3, status: 'blocked' }),
    ], 'plan.docx')
    expect(p.needsPerson).toBe(0)
    expect(p.needsSystem).toBe(0)
    expect(p.complete).toBe(false)
    expect(allBlocked(p)).toBe(false)   // not ALL blocked either — it is its own state
    expect(remainingSummary(p)).toBe('1 blocked')
  })

  it('reports the whole queue when no document is named', () => {
    expect(docRemediationProgress(QUEUE, null).total).toBe(6)
  })

  it('borrows the effort estimate rather than inventing a second one', () => {
    const p = docRemediationProgress(QUEUE, 'plan.docx')
    expect(p.remainingSec).toBeGreaterThan(0)
    expect(p.remainingLabel).toMatch(/remaining/)
  })

  it('every declared stage appears in the returned rows, including the empty ones', () => {
    const p = docRemediationProgress(QUEUE, 'plan.docx')
    expect(p.stages.map((s) => s.key)).toEqual(STAGES.map((s) => s.key))
  })
})

describe('remainingSummary / allBlocked', () => {
  it('are safe on a null progress object', () => {
    expect(remainingSummary(null)).toBe('')
    expect(allBlocked(null)).toBe(false)
  })
  it('singularise the person count', () => {
    const p = docRemediationProgress([F({ id: 1, after: 'x' })], 'plan.docx')
    expect(remainingSummary(p)).toBe('1 needs you')
  })
})
