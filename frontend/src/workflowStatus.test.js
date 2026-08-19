import { describe, it, expect } from 'vitest'
import { workflowStatusOf, workflowCounts, matchesWorkflow, workflowStepIndex, WORKFLOW_TABS } from './remediationInboxModel.js'

describe('workflowStatusOf — pipeline stage from real state (no invented flags)', () => {
  it('a blocked finding → blocked', () => {
    expect(workflowStatusOf({ status: 'blocked' })).toBe('blocked')
  })
  it('an untouched finding → inbox (fresh AI draft, fresh manual, or an un-assigned rejected fix)', () => {
    expect(workflowStatusOf({ hasProposal: true, after: 'x' })).toBe('inbox')
    expect(workflowStatusOf({ id: 9 })).toBe('inbox')
    // a rejected AI fix still needs triage ("Mark as assigned") — nobody has started it yet.
    expect(workflowStatusOf({ rejectedFix: true })).toBe('inbox')
  })
  it('an applied auto-fix → ready-to-validate', () => {
    expect(workflowStatusOf({ autoApplied: true })).toBe('ready-to-validate')
  })
  it('an approved decision → ready-to-validate; verified → done; rejected → done', () => {
    expect(workflowStatusOf({ id: 1, hasProposal: true, after: 'x' }, { 1: { state: 'accepted' } })).toBe('ready-to-validate')
    expect(workflowStatusOf({ id: 1, status: 'verified' })).toBe('done')
    expect(workflowStatusOf({ id: 1 }, { 1: { state: 'rejected' } })).toBe('done')
  })
  it('an assigned or deferred decision → in-progress (a person has taken it on)', () => {
    expect(workflowStatusOf({ id: 1 }, { 1: { state: 'assigned' } })).toBe('in-progress')
    expect(workflowStatusOf({ id: 1, rejectedFix: true }, { 1: { state: 'assigned' } })).toBe('in-progress')
  })
  it('verified wins over an approved decision (fully done, not awaiting)', () => {
    expect(workflowStatusOf({ id: 1, status: 'verified' }, { 1: { state: 'accepted' } })).toBe('done')
  })
})

describe('workflowCounts / matchesWorkflow', () => {
  const LIST = [
    { id: 1, autoApplied: true },              // ready-to-validate
    { id: 2, hasProposal: true, after: 'x' },  // inbox
    { id: 3 },                                 // inbox (manual)
    { id: 4, status: 'blocked' },              // blocked
  ]
  it('counts each stage, summing to the list length', () => {
    expect(workflowCounts(LIST)).toMatchObject({ all: 4, inbox: 2, 'ready-to-validate': 1, blocked: 1, 'in-progress': 0, done: 0 })
  })
  it('matchesWorkflow filters by stage; "all" passes everything', () => {
    expect(LIST.filter((f) => matchesWorkflow(f, 'inbox')).map((f) => f.id)).toEqual([2, 3])
    expect(LIST.filter((f) => matchesWorkflow(f, 'all')).length).toBe(4)
  })
  it('exposes the four pipeline tabs plus Done', () => {
    expect(WORKFLOW_TABS).toEqual(['inbox', 'in-progress', 'ready-to-validate', 'blocked', 'done'])
  })
})

describe('workflowStepIndex — the footer loop step (Show 0 → Review 1 → Verify 2)', () => {
  it('a fresh manual finding is at Show the problem (0)', () => {
    expect(workflowStepIndex({ id: 1 })).toBe(0)                               // no proposal to review
    expect(workflowStepIndex({ id: 1, status: 'blocked' })).toBe(0)           // blocked → still just showing it
  })
  it('a finding with an AI proposal awaiting a decision is at Review (1)', () => {
    expect(workflowStepIndex({ id: 1, hasProposal: true, after: 'x' })).toBe(1)  // apply lane, still inbox
  })
  it('a fix that is in (auto-applied or approved) is at Verify (2)', () => {
    expect(workflowStepIndex({ id: 1, autoApplied: true })).toBe(2)
    expect(workflowStepIndex({ id: 1, hasProposal: true, after: 'x' }, { 1: { state: 'accepted' } })).toBe(2)
  })
  it('a fully done finding is past all three (3 — none active)', () => {
    expect(workflowStepIndex({ id: 1, status: 'verified' })).toBe(3)
    expect(workflowStepIndex({ id: 1 }, { 1: { state: 'rejected' } })).toBe(3)
  })
})
