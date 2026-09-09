import { it, expect, vi, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'
import BatchReviewSelection from './BatchReviewSelection.jsx'
import RemediationInbox from './RemediationInbox.jsx'
afterEach(unmountAll)
const ready = id => ({ id, file: `z-${id}.docx`, ruleId: '1.1.1', hasProposal: true, after: `alt ${id}`,
  proposals: [{ proposed_value: `alt ${id}` }], _raw: { decision_version: 0, source_revision: 'source', proposal_snapshot_ids: [`snapshot-${id}`] } })
const applied = Array.from({ length: 119 }, (_, i) => ({ id: `applied-${i}`, file: `a-${i}.docx`, autoApplied: true, after: 'Applied change' }))
const click = async el => act(async () => el.dispatchEvent(new MouseEvent('click', { bubbles: true })))
async function mount(Component, props) {
  const { root, container } = createTestRoot()
  const render = async next => act(async () => root.render(createElement(Component, { ...props, ...next })))
  await render()
  return { container, render, button: name => [...container.querySelectorAll('button')].find(b => b.textContent.includes(name)) }
}
it('keeps 119 already-applied rows out of the selectable pages and surfaces later ready proposals', async () => {
  const v = await mount(BatchReviewSelection, { visible: [...applied, ready('one'), ready('two')], onDecide: vi.fn(), scopeKey: 'scan' })
  expect(v.container.querySelectorAll('input[type=checkbox]')).toHaveLength(2)
  expect(v.button('Approve all ready (2)')).toBeTruthy()
  expect(v.container.querySelectorAll('input[disabled]')).toHaveLength(0)
  expect(v.container.textContent).not.toContain('Select only proposals you have reviewed')
})
it('freezes the complete cross-page ready set with optional inspection; refresh never adds new proposals', async () => {
  const onDecide = vi.fn().mockResolvedValue(undefined)
  const visible = [...applied, ...Array.from({ length: 25 }, (_, i) => ready(i))]
  const v = await mount(BatchReviewSelection, { visible, onDecide, scopeKey: 'scan', scopeLabel: 'All documents in this scan' })
  await click(v.button('Approve all ready (25)'))
  expect(onDecide).not.toHaveBeenCalled()
  expect(v.container.querySelector('details[open]')).toBeNull()
  await v.render({ visible: [...visible, ready('new')] })
  await click(v.button('Confirm approval'))
  expect(onDecide).toHaveBeenCalledTimes(25)
  expect(onDecide.mock.calls.map(c => c[0].id)).toEqual(Array.from({ length: 25 }, (_, i) => i))
})
it('opens scan-wide ready approval even when the individual queue tab has only applied work', async () => {
  const v = await mount(RemediationInbox, { queue: [...applied, ready('pending')], decisions: {}, initialTab: 'needs-review', scanId: 'scan', onDecide: vi.fn() })
  await click(v.button('Bulk approve ready proposals'))
  expect(v.button('Approve all ready (1)')).toBeTruthy()
  expect(v.container.textContent).toContain('All documents in this scan')
})
it('shows a truthful no-ready explanation and useful action instead of disabled checkboxes', async () => {
  const onReviewExcluded = vi.fn()
  const v = await mount(BatchReviewSelection, { visible: applied, onReviewExcluded, onDecide: vi.fn(), scopeKey: 'scan' })
  expect(v.container.querySelectorAll('input[type=checkbox]')).toHaveLength(0)
  expect(v.container.textContent).toContain('No proposals are ready for approval')
  await click(v.button('Open individual review'))
  expect(onReviewExcluded).toHaveBeenCalledOnce()
})

it.each([
  ['Fix manually', 'Manual issue', { id: 'manual', file: 'manual.docx', title: 'Manual issue' }],
  ['Awaiting verification', 'Writing issue', { ...ready('writing'), title: 'Writing issue', status: 'rechecking' }],
  ['Blocked', 'Blocked issue', { ...ready('blocked'), title: 'Blocked issue', status: 'blocked' }],
  ['Completed', 'Completed issue', { ...ready('done'), title: 'Completed issue', status: 'verified' }],
])('exits bulk selection when switching to %s and clears stale approval intent', async (category, title, other) => {
  const onDecide = vi.fn()
  const v = await mount(RemediationInbox, { queue: [ready('pending'), other], decisions: {}, scanId: 'scan', onDecide })
  expect(v.container.querySelector('.rem-wsfoot')).not.toBeNull()
  await click(v.button('Bulk approve ready proposals'))
  await click(v.button('Approve all ready (1)'))
  const progress = v.container.querySelector('.rem-wsfoot')
  expect(progress).toBeNull()
  await click(v.button(category))
  const panel = v.container.querySelector('[aria-label="Select findings for approval"]')
  expect(panel.closest('[hidden]')).toBeTruthy()
  expect(v.container.querySelector('.remediation-detail')?.textContent).toContain(title)
  expect(v.container.querySelector('.rinbox').style.display).not.toBe('none')
  await click(v.button('Approve AI suggestions'))
  await click(v.button('Bulk approve ready proposals'))
  expect(v.button('Confirm approval')).toBeUndefined()
  expect(onDecide).not.toHaveBeenCalled()
})

it('explains dynamic missing proposal information and opens focused individual review without a decision', async () => {
  const onDecide = vi.fn()
  const unversioned = ['one', 'two'].map(id => ({ ...ready(id), title: 'Legacy proposal', _raw: {} }))
  const missing = { ...ready('missing'), proposals: [{ proposed_value: '' }] }
  const v = await mount(RemediationInbox, { queue: [...unversioned, missing], decisions: {}, initialTab: 'needs-review', scanId: 'scan', onDecide })
  await click(v.button('Bulk approve ready proposals'))
  const empty = v.container.querySelector('.batch-review-empty')
  expect(empty.textContent).toContain('2 review items have no verifiable proposal version.')
  expect(empty.textContent).toContain('1 review item has no complete proposal.')
  expect(empty.textContent).toContain('Generating fresh proposals requires a separately approved run.')
  expect(empty.textContent).not.toContain('refresh outdated proposals')
  await click(v.button('Open individual review'))
  expect(v.container.querySelector('[aria-label="Select findings for approval"]').closest('[hidden]')).toBeTruthy()
  expect(document.activeElement.textContent).toContain('Legacy proposal')
  expect(document.activeElement.tagName).toMatch(/^H[1-6]$/)
  expect(onDecide).not.toHaveBeenCalled()
})
