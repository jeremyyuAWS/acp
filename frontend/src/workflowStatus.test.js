import { describe, it, expect } from 'vitest'
import { workflowStatusOf, workflowCounts, matchesWorkflow, workflowStepIndex, isResolved, WORKFLOW_TABS } from './remediationInboxModel.js'

describe('workflowStatusOf — pipeline stage from real state (no invented flags)', () => {
  it('a blocked finding → blocked', () => {
    expect(workflowStatusOf({ status: 'blocked' })).toBe('blocked')
  })
  it('a fresh AI draft awaiting a decision → needs-review', () => {
    expect(workflowStatusOf({ hasProposal: true, after: 'x' })).toBe('needs-review')
  })
  it('an unacknowledged auto-fix → needs-review (the reviewer still confirms the change)', () => {
    // The double-count fix: an auto-fix used to land in ready-to-validate AND count as resolved.
    // It now waits in Needs review until the reviewer confirms it.
    expect(workflowStatusOf({ autoApplied: true })).toBe('needs-review')
  })
  it('a manual-from-start finding and a rejected AI fix → manual (needs hand-editing)', () => {
    expect(workflowStatusOf({ id: 9 })).toBe('manual')
    expect(workflowStatusOf({ rejectedFix: true })).toBe('manual')
  })
  it('an approved/accepted decision → awaiting-validation (fix in, not yet re-scanned)', () => {
    expect(workflowStatusOf({ id: 1, hasProposal: true, after: 'x' }, { 1: { state: 'accepted' } })).toBe('awaiting-validation')
  })
  it('an assigned or deferred decision → manual (a person will hand-fix it)', () => {
    expect(workflowStatusOf({ id: 1 }, { 1: { state: 'assigned' } })).toBe('manual')
    expect(workflowStatusOf({ id: 1 }, { 1: { state: 'deferred' } })).toBe('manual')
  })
  it('verified → completed; rejected → completed; not_applicable → completed', () => {
    expect(workflowStatusOf({ id: 1, status: 'verified' })).toBe('completed')
    expect(workflowStatusOf({ id: 1 }, { 1: { state: 'rejected' } })).toBe('completed')
    expect(workflowStatusOf({ id: 1 }, { 1: { state: 'not_applicable' } })).toBe('completed')
  })
  it('verified wins over an approved decision (Completed, not awaiting)', () => {
    expect(workflowStatusOf({ id: 1, status: 'verified' }, { 1: { state: 'accepted' } })).toBe('completed')
  })
})

describe('workflowCounts / matchesWorkflow', () => {
  const LIST = [
    { id: 1, autoApplied: true },              // needs-review (unacknowledged auto-fix)
    { id: 2, hasProposal: true, after: 'x' },  // needs-review (AI draft)
    { id: 3 },                                 // manual (manual-from-start)
    { id: 4, status: 'blocked' },              // blocked
  ]
  it('counts each stage, summing to the list length', () => {
    expect(workflowCounts(LIST)).toMatchObject({ all: 4, 'needs-review': 2, manual: 1, 'awaiting-validation': 0, blocked: 1, completed: 0 })
  })
  it('matchesWorkflow filters by stage; "all" passes everything', () => {
    expect(LIST.filter((f) => matchesWorkflow(f, 'needs-review')).map((f) => f.id)).toEqual([1, 2])
    expect(LIST.filter((f) => matchesWorkflow(f, 'all')).length).toBe(4)
  })
  it('exposes the five workflow tabs', () => {
    expect(WORKFLOW_TABS).toEqual(['needs-review', 'manual', 'awaiting-validation', 'blocked', 'completed'])
  })
})

describe('count consistency — the reported double-count is fixed', () => {
  it('acknowledged auto-fixes are Awaiting validation, NOT Completed (no "done" the re-scan has not earned)', () => {
    // The reported bug: 25 auto-fixes read "25 of 25 resolved" AND "Ready to validate 25" at once.
    // Now: acknowledged (accepted) auto-fixes are Awaiting validation and count as reviewed, but the
    // Completed tab excludes them — so "3 of 3 reviewed" coexists with "Awaiting validation 3" with
    // no surface claiming completion before the certifying re-scan.
    const list = [1, 2, 3].map((id) => ({ id, autoApplied: true }))
    const decisions = { 1: { state: 'accepted' }, 2: { state: 'accepted' }, 3: { state: 'accepted' } }
    const counts = workflowCounts(list, decisions)
    expect(counts['awaiting-validation']).toBe(3)
    expect(counts.completed).toBe(0)
    expect(list.filter((f) => isResolved(f, decisions)).length).toBe(3)  // reviewed = 3 (a separate lens)
  })
  it('an UNacknowledged auto-fix is Needs review and is NOT yet counted as reviewed', () => {
    const f = { id: 1, autoApplied: true }
    expect(workflowStatusOf(f, {})).toBe('needs-review')
    expect(isResolved(f, {})).toBe(false)   // it still needs the reviewer's confirmation
  })
  it('every finding lands in exactly one tab — the counts sum to the queue length', () => {
    const list = [
      { id: 1, autoApplied: true },                                   // needs-review
      { id: 2, hasProposal: true, after: 'x' },                       // needs-review
      { id: 3 },                                                      // manual
      { id: 4, rejectedFix: true },                                   // manual
      { id: 5, status: 'blocked' },                                   // blocked
      { id: 6, id2: 1, status: 'verified' },                          // completed
    ]
    const decisions = { 2: { state: 'accepted' } }                    // → awaiting-validation
    const counts = workflowCounts(list, decisions)
    const summed = WORKFLOW_TABS.reduce((s, t) => s + counts[t], 0)
    expect(summed).toBe(list.length)
  })
})

describe('workflowStepIndex — the footer loop step (Show 0 → Review 1 → Verify 2)', () => {
  it('a fresh manual finding is at Show the problem (0)', () => {
    expect(workflowStepIndex({ id: 1 })).toBe(0)                               // no proposal to review
    expect(workflowStepIndex({ id: 1, status: 'blocked' })).toBe(0)           // blocked → still just showing it
  })
  it('a proposal awaiting review — AI draft or unconfirmed auto-fix — is at Review (1)', () => {
    expect(workflowStepIndex({ id: 1, hasProposal: true, after: 'x' })).toBe(1)  // apply lane, needs review
    expect(workflowStepIndex({ id: 1, autoApplied: true })).toBe(1)              // unconfirmed auto-fix: review the change
  })
  it('an approved fix awaiting the re-scan is at Verify (2)', () => {
    expect(workflowStepIndex({ id: 1, hasProposal: true, after: 'x' }, { 1: { state: 'accepted' } })).toBe(2)
  })
  it('a fully done finding is past all three (3 — none active)', () => {
    expect(workflowStepIndex({ id: 1, status: 'verified' })).toBe(3)
    expect(workflowStepIndex({ id: 1 }, { 1: { state: 'rejected' } })).toBe(3)
  })
})
