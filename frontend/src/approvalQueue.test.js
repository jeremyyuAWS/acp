/**
 * The approval queue, tested as the split it exists to make.
 *
 * A queue row is created per (document, criterion) whenever a run defers to a human. Some carry a
 * model's actual draft; some carry nothing. Both arrive from the same endpoint looking identical,
 * and the difference is the whole point: there is nothing to approve on a row with no draft, and
 * offering an Approve button on one asks a reviewer to sign off on the absence of a suggestion.
 *
 * The regression this guards against is real and specific. The queue card used to fall back to a
 * canned template whenever no proposal existed, so every image in every document rendered an
 * identical "AI-generated alt text added — confirm or reword" whether or not a model had said
 * anything. `draft === null` is a fact and there is no fallback for it.
 */
import { describe, it, expect } from 'vitest'
import { approvalQueue, approvalItem, reconcileQueue, scOfRuleId } from './approvalQueue.js'

const row = (over = {}) => ({
  id: 'q1', scan_id: 's', file: 'a.docx', rule_id: '1.1.1', rule_name: 'Non-text Content',
  status: 'pending', finding_count: 1, ...over,
})
const drafted = (over = {}) => row({
  proposals: [{ proposed_value: 'Bar chart: revenue rising from £4.1m to £5.8m.',
                before: 'image, no alt text', rationale: 'read from the chart axes' }],
  ...over,
})

describe('an absent queue is not an empty one', () => {
  it('returns null when nothing has been loaded', () => {
    expect(approvalQueue(null)).toBeNull()
    expect(approvalQueue(undefined)).toBeNull()
    expect(approvalQueue({ detail: 'forbidden' })).toBeNull()
    expect(reconcileQueue(null)).toBeNull()
  })

  it('distinguishes that from a queue that really holds nothing', () => {
    const q = approvalQueue([])
    expect(q).not.toBeNull()
    expect(q.awaiting).toEqual([])
    expect(q.total).toBe(0)
  })
})

describe('a row with no draft is not an approval', () => {
  it('separates drafted rows from undrafted ones', () => {
    const q = approvalQueue([drafted({ id: 'has' }), row({ id: 'none' })])
    expect(q.awaiting.map((i) => i.id)).toEqual(['has'])
    expect(q.undrafted.map((i) => i.id)).toEqual(['none'])
  })

  it('never invents a draft for a row that carries none', () => {
    // No template, no "AI fix ready", no empty string standing in for text.
    expect(approvalItem(row()).draft).toBeNull()
    expect(approvalItem(row({ proposals: [] })).draft).toBeNull()
    expect(approvalItem(row({ proposals: [{ before: 'x' }] })).draft).toBeNull()
  })

  it('treats an empty-string draft as no draft', () => {
    // A proposal whose value is '' would otherwise render an Approve button over blank space.
    const q = approvalQueue([row({ id: 'blank', proposals: [{ proposed_value: '' }] })])
    expect(q.awaiting).toEqual([])
    expect(q.undrafted.map((i) => i.id)).toEqual(['blank'])
  })

  it('does not read a reviewer-typed approved_value as a model draft', () => {
    // approved_value only ever holds what a REVIEWER typed back. Treating it as the draft would
    // show an already-decided value as something still awaiting a decision.
    const q = approvalQueue([row({ id: 'x', approved_value: 'a person wrote this' })])
    expect(q.awaiting).toEqual([])
    expect(q.undrafted[0].draft).toBeNull()
  })
})

describe('only rows still waiting on a person are offered', () => {
  it('drops rows a decision has already been recorded on', () => {
    const q = approvalQueue([
      drafted({ id: 'a', status: 'pending' }),
      drafted({ id: 'b', status: 'approved' }),
      drafted({ id: 'c', status: 'rejected' }),
      drafted({ id: 'd', status: 'skipped' }),
    ])
    expect(q.awaiting.map((i) => i.id)).toEqual(['a'])
    expect(q.resolved).toBe(3)
  })

  it('treats an unknown or missing status as still waiting', () => {
    // The other default hides work. A status the backend has not invented yet must surface, not
    // silently disappear from a queue somebody is working through.
    const q = approvalQueue([drafted({ id: 'a', status: null }), drafted({ id: 'b', status: 'triaged' })])
    expect(q.awaiting.map((i) => i.id)).toEqual(['a', 'b'])
    expect(q.resolved).toBe(0)
  })

  it('prints an identity that sums to the rows it was given', () => {
    const q = approvalQueue([drafted({ id: 'a' }), row({ id: 'b' }), drafted({ id: 'c', status: 'approved' })])
    const r = reconcileQueue(q)
    expect(r.ok).toBe(true)
    expect(r.line).toBe('1 awaiting approval + 1 with no draft + 1 already decided = 3 queue items')
  })
})

describe('one row is not one draft', () => {
  it('carries how many values a single approval would accept', () => {
    const q = approvalQueue([drafted({
      proposals: [{ proposed_value: 'one' }, { proposed_value: 'two' }, { proposed_value: 'three' }],
    })])
    expect(q.awaiting[0].draftCount).toBe(3)
    expect(q.awaiting[0].draft).toBe('one')
  })
})

describe('the row is read, never guessed', () => {
  it('normalizes every rule_id shape the queue actually stores', () => {
    expect(scOfRuleId('1.1.1')).toBe('1.1.1')
    expect(scOfRuleId('SC_1_1_1')).toBe('1.1.1')
    expect(scOfRuleId('WCAG_2_4_4')).toBe('2.4.4')
    expect(scOfRuleId(null)).toBe('')
  })

  it('reports no page rather than a wrong one when none was attributed', () => {
    expect(approvalItem(row({ page: null })).page).toBeNull()
    expect(approvalItem(drafted({ page: 4 })).page).toBe(4)
  })

  it('carries validated as a boolean fact about the fix, not a reason to skip approval', () => {
    // `validated` says a deterministic fix cleared on the re-scan. It is evidence; it never moves
    // a row out of `awaiting`, because approving is still a human act.
    const q = approvalQueue([drafted({ id: 'v', validated: 1 })])
    expect(q.awaiting[0].validated).toBe(true)
    expect(q.awaiting).toHaveLength(1)
  })

  it('orders by document then criterion, so the list is stable between polls', () => {
    const q = approvalQueue([
      drafted({ id: '1', file: 'b.docx', rule_id: '1.1.1' }),
      drafted({ id: '2', file: 'a.docx', rule_id: '2.4.4' }),
      drafted({ id: '3', file: 'a.docx', rule_id: '1.10.1' }),
      drafted({ id: '4', file: 'a.docx', rule_id: '1.2.1' }),
    ])
    // '1.10.1' after '1.2.1': numeric collation, not lexicographic.
    expect(q.awaiting.map((i) => i.id)).toEqual(['4', '3', '2', '1'])
  })
})
