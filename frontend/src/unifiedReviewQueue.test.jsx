import { it, expect, vi, afterEach } from 'vitest'
import { createElement, act } from 'react'
import axe from 'axe-core'
import RemediationInbox from './RemediationInbox.jsx'
import { createTestRoot, unmountAll } from './testRoots.js'
afterEach(unmountAll)
const proposal = { id: 'proposal', file: 'a.docx', title: 'Draft needs approval', hasProposal: true, after: 'A meaningful title', ruleId: '2.4.2' }
const queue = [
  { ...proposal, id: 'done', file: 'done.docx', title: 'Verified change', status: 'verified' },
  { ...proposal, id: 'waiting', file: 'waiting.docx', title: 'Approved change', status: 'approved' },
  { id: 'manual', file: 'manual.docx', title: 'Manual correction', ruleId: '1.1.1' },
  { ...proposal, id: 'blocked', file: 'blocked.docx', title: 'Blocked change', status: 'blocked' },
  proposal,
]
async function mount() {
  localStorage.clear(); sessionStorage.clear()
  const view = createTestRoot()
  const onDecide = vi.fn()
  await act(async () => view.root.render(createElement(RemediationInbox, { queue, onDecide, onRecheck: vi.fn() })))
  return { ...view, onDecide }
}
it('shows all statuses together without workflow tabs and places actionable work before waiting and completed items', async () => {
  const { container } = await mount()
  expect(container.querySelector('[aria-label="Workflow status"]')).toBeNull()
  expect(container.querySelector('select[aria-label="Filter by status"]').value).toBe('all')
  const rows = [...container.querySelectorAll('.rinbox-row')]
  expect(rows).toHaveLength(5)
  expect(rows.find(row => row.textContent.includes('Approved change')).textContent).toContain('Awaiting verification')
  expect(rows.find(row => row.textContent.includes('Verified change')).textContent).toContain('Completed')
  expect(rows.slice(0, 2).map(row => row.id).sort()).toEqual(['rinbox-row-manual', 'rinbox-row-proposal'])
  expect(rows.at(-1).id).toBe('rinbox-row-done')
})
it('lets the reviewer inspect a waiting item in the same queue without another approval or editable proposal', async () => {
  const { container, onDecide } = await mount()
  await act(async () => container.querySelector('#rinbox-row-waiting').click())
  const pane = container.querySelector('.remediation-detail')
  expect(pane.querySelector('textarea')).toBeNull()
  expect(pane.textContent).not.toContain('Save and continue')
  expect(pane.textContent).toMatch(/awaiting|re-scan/i)
  expect(onDecide).not.toHaveBeenCalled()
  expect(container.querySelectorAll('.rinbox-row')).toHaveLength(5)
})
it('keeps status filtering optional and accessible', async () => {
  const { container } = await mount()
  const filter = container.querySelector('select[aria-label="Filter by status"]')
  await act(async () => { filter.value = 'awaiting-validation'; filter.dispatchEvent(new Event('change', { bubbles: true })) })
  expect(container.querySelectorAll('.rinbox-row')).toHaveLength(1)
  await act(async () => { filter.value = 'all'; filter.dispatchEvent(new Event('change', { bubbles: true })) })
  expect(container.querySelectorAll('.rinbox-row')).toHaveLength(5)
  const result = await axe.run(container, { rules: { 'color-contrast': { enabled: false } } })
  expect(result.violations).toEqual([])
})
