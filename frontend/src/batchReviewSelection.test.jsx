import { describe, it, expect, afterEach, vi } from 'vitest'
import { createElement } from 'react'
import { act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'
import BatchReviewSelection from './BatchReviewSelection.jsx'
import { batchDecision, exclusionReason, snapshotFinding, selectionProblem } from './batchReviewSelection.js'
afterEach(unmountAll)
const finding = (id, overrides = {}) => ({ id, file: `${String(id).padStart(3, '0')}.docx`, scanId: 'scan', ruleId: '1.1.1', hasProposal: true,
  after: `draft ${id}`, proposals: [{ proposed_value: `draft ${id}`, before: 'old' }],
  _raw: { decision_version: 2, proposal_snapshot_ids: [`snapshot-${id}`], source_revision: 'source-1' }, ...overrides })
const click = async el => act(async () => el.dispatchEvent(new MouseEvent('click', { bubbles: true })))
async function mount(props) {
  const { container, root } = createTestRoot()
  const render = async extra => act(async () => root.render(createElement(BatchReviewSelection, { scopeKey: 'scan', ...props, ...extra })))
  await render()
  return { container, render, button: text => [...container.querySelectorAll('button')].find(b => b.textContent.includes(text)) }
}
describe('explicit batch selection', () => {
  it('starts empty, paging and preview never write; one checkbox binds only that exact finding', async () => {
    const onDecide = vi.fn().mockResolvedValue(undefined)
    const view = await mount({ visible: Array.from({ length: 23 }, (_, i) => finding(i)), onDecide })
    expect(view.button('Approve selected').disabled).toBe(true)
    await click(view.button('Next batch page'))
    await click(view.container.querySelector('input'))
    await click(view.button('Approve selected'))
    expect(onDecide).not.toHaveBeenCalled()
    expect(view.container.textContent).toContain('1 findings selected (1 review items) · 1 proposals · 1 files')
    expect(view.container.textContent).toContain('old')
    await click(view.button('Confirm approval'))
    expect(onDecide).toHaveBeenCalledTimes(1)
    expect(onDecide.mock.calls[0][0].id).toBe(10)
    expect(onDecide.mock.calls[0][1]).toMatchObject({ expectedVersion: 2, expectedSourceRevision: 'source-1', expectedProposalSnapshotIds: ['snapshot-10'], approvedValues: ['draft 10'] })
    expect(view.container.textContent).toContain('1 recorded')
  })
  it('never broadens selection with refresh or filters and blocks changed proposal versions', async () => {
    const a = finding(1), onDecide = vi.fn()
    const v = await mount({ visible: [a], onDecide })
    await click(v.container.querySelector('input'))
    await v.render({ visible: [a, finding(2)] })
    expect(v.container.textContent).toContain('1 findings selected')
    await v.render({ visible: [finding(2)] })
    expect(v.button('Approve selected').disabled).toBe(true)
    await v.render({ visible: [finding(1, { _raw: { ...a._raw, proposal_snapshot_ids: ['new'] } })] })
    expect(v.container.textContent).toContain('Proposal or source changed')
    expect(onDecide).not.toHaveBeenCalled()
    await v.render({ scopeKey: 'other-scan' })
    expect(v.container.textContent).toContain('0 findings selected')
  })
  it('counts every proposal and excludes manual, missing, applied and edited work', async () => {
    const multi = finding(1, { proposals: [{ proposed_value: 'A' }, { proposed_value: 'B' }], _raw: { ...finding(1)._raw, finding_count: 2, proposal_snapshot_ids: ['a', 'b'] } })
    const missing = finding(2, { proposals: [{ proposed_value: 'A' }, {}] })
    const v = await mount({ visible: [multi, missing, finding(3, { autoApplied: true }), finding(4)], drafts: { 4: 'unsaved' }, onDecide: vi.fn() })
    await click(v.button('Select eligible'))
    expect(v.container.textContent).toContain('2 findings selected (1 review items) · 2 proposals · 1 files')
    expect(v.container.textContent).toContain('missing proposal')
    expect(exclusionReason(finding(9, { hasProposal: false, after: null, proposals: [] }))).toBe('Manual work')
  })
  it('retains failed IDs with the same request ID and never retries successes or ambiguous writes', async () => {
    const onDecide = vi.fn(async f => {
      if (f.id === 2) throw Object.assign(new Error('conflict'), { status: 409 })
      if (f.id === 3) throw new TypeError('connection lost')
    })
    const v = await mount({ visible: [finding(1), finding(2), finding(3)], onDecide })
    await click(v.button('Select eligible')); await click(v.button('Approve selected')); await click(v.button('Confirm approval'))
    expect(v.container.textContent).toContain('1 recorded · 1 not recorded · 1 uncertain')
    const requestId = onDecide.mock.calls[1][1].requestId
    await click(v.button('Approve selected')); await click(v.button('Confirm approval'))
    expect(onDecide.mock.calls.map(c => c[0].id)).toEqual([1, 2, 3, 2])
    expect(onDecide.mock.calls[3][1].requestId).toBe(requestId)
  })
  it('stops unsent work after a scope change during a write and suppresses double submit', async () => {
    let release
    const onDecide = vi.fn(() => new Promise(resolve => { release = resolve }))
    const v = await mount({ visible: [finding(1), finding(2)], onDecide })
    await click(v.button('Select eligible')); await click(v.button('Approve selected'))
    const confirm = v.button('Confirm approval')
    await click(confirm); await click(confirm)
    expect(onDecide).toHaveBeenCalledTimes(1)
    await v.render({ scopeKey: 'changed' })
    await act(async () => release())
    expect(onDecide).toHaveBeenCalledTimes(1)
    expect(v.container.textContent).toContain('Review scope changed')
  })
  it('freezes all values and detects locator and source replacement', () => {
    const f = finding(1), entry = snapshotFinding(f)
    f.proposals[0].proposed_value = 'replacement'
    expect(batchDecision(entry).approvedValues).toEqual(['draft 1'])
    expect(selectionProblem(entry, [f], {}, {})).toContain('changed')
  })
})
