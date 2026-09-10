import { afterEach, expect, it, vi } from 'vitest'
import { act, createElement } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'
import RemediationLiveDocuments from './RemediationLiveDocuments.jsx'
import { getFileRemediationDiffs } from './api.js'
vi.mock('./api.js', () => ({ getFileRemediationDiffs: vi.fn() }))
globalThis.IS_REACT_ACT_ENVIRONMENT = true
afterEach(async () => { await unmountAll(); vi.clearAllMocks() })
const files = ['A.docx', 'B.docx'].map(file => ({ file, name: file, status: 'analysed', issues: [{ wcag: 'SC_1_1_1', severity: 'SERIOUS' }] }))
const fix = { file: 'A.docx', rule_id: 'SC_1_1_1', before: 'Missing alt text', after: 'A mountain lake', page: 2 }
const props = { scanId: 'run', files, cap: { docx: { '1.1.1': 'assisted' } }, assessment: { docx: { '1.1.1': 'auto' } }, fixes: [fix], fixTotal: 9 }
async function mount(extra = {}) {
  const { root, container } = createTestRoot()
  await act(async () => root.render(createElement(RemediationLiveDocuments, { ...props, ...extra })))
  return { root, container }
}
it('reuses Documents, keeps all files visible, and opens evidence grouped by SC for only the selected file', async () => {
  getFileRemediationDiffs.mockResolvedValue([fix, { ...fix, rule_id: 'SC_3_1_1', before: '', after: 'en-US' }])
  const { container } = await mount()
  expect(container.textContent).toContain('Documents')
  expect(container.querySelector('.col-category [aria-label="Applied — verification pending: 1 records"]')).not.toBeNull()
  expect(container.querySelector('.col-category details')).toBeNull()
  expect(container.textContent).toContain('9 across the run')
  expect(container.querySelectorAll('tbody tr')).toHaveLength(2)
  await act(async () => [...container.querySelectorAll('button')].find(n => n.textContent.includes('View fixes')).click())
  expect(getFileRemediationDiffs).toHaveBeenCalledWith('run', 'A.docx')
  const dialog = container.querySelector('.remediation-file-page')
  expect(dialog.querySelector('h2').textContent).toBe('A.docx')
  expect(dialog.querySelectorAll('.remediation-sc-card')).toHaveLength(2)
  expect(dialog.textContent).toContain('SC 1.1.1 Non-text Content')
  expect(dialog.textContent).toContain('A mountain lake')
  expect(dialog.textContent).toContain('Page 2')
  expect(dialog.textContent).toContain('Verification: Not reported')
})
it('refreshes an open file as completed work arrives and preserves loaded evidence when the read fails', async () => {
  getFileRemediationDiffs.mockResolvedValue([fix])
  const { root, container } = await mount()
  await act(async () => [...container.querySelectorAll('button')].find(n => n.textContent.includes('View fixes')).click())
  getFileRemediationDiffs.mockRejectedValue(new Error('offline'))
  await act(async () => root.render(createElement(RemediationLiveDocuments, { ...props, refreshKey: 'next' })))
  expect(container.querySelector('.remediation-file-page').textContent).toContain('does not establish that the file has no fixes')
  expect(container.querySelector('.remediation-file-page').textContent).toContain('A mountain lake')
  expect(getFileRemediationDiffs).toHaveBeenCalledTimes(2)
})

it('ignores a late response after a different document is opened', async () => {
  let finishFirst
  getFileRemediationDiffs.mockImplementation((_id, file) => file === 'A.docx'
    ? new Promise(resolve => { finishFirst = resolve })
    : Promise.resolve([{ ...fix, file: 'B.docx', after: 'Second document' }]))
  const { container } = await mount()
  const buttons = () => [...container.querySelectorAll('button')].filter(n => n.textContent.includes('View fixes'))
  await act(async () => buttons()[0].click())
  await act(async () => [...container.querySelectorAll('button')].find(n => n.textContent === '← All documents').click())
  await act(async () => buttons()[1].click())
  await act(async () => finishFirst([fix]))
  const drawer = container.querySelector('.remediation-file-page')
  expect(drawer.textContent).toContain('Second document')
  expect(drawer.textContent).not.toContain('A mountain lake')
})

it('offers remediation-state filtering while keeping change records separate from findings', async () => {
  const { container } = await mount({ fixes: [{ ...fix, verified: true }] })
  const button = [...container.querySelectorAll('button')].find(node => node.querySelector('[title="Fixed and verified"]'))
  expect(button.textContent).toContain('Verified 0 · 1 change records')
  await act(async () => button.click())
  expect(container.querySelectorAll('tbody tr')).toHaveLength(1)
  expect(container.querySelector('tbody').textContent).toContain('A.docx')
  expect(container.querySelector('tbody').textContent).not.toContain('B.docx')
})

it('uses an Assess-style file page with remediation pills and returns focus to View fixes', async () => {
  getFileRemediationDiffs.mockResolvedValue([fix])
  const { container } = await mount()
  const open = [...container.querySelectorAll('button')].find(n => n.textContent.includes('View fixes'))
  open.focus()
  await act(async () => open.click())
  const page = container.querySelector('.remediation-file-page')
  expect(document.activeElement).toBe(page.querySelector('h2'))
  expect(page.querySelector('.remediation-file-summary')).not.toBeNull()
  expect(page.querySelector('.remediation-sc-card .remediation-category-pill')).not.toBeNull()
  expect(page.querySelectorAll('details')).toHaveLength(0)
  expect(container.querySelector('[role=dialog]')).toBeNull()
  await act(async () => [...page.querySelectorAll('button')].find(n => n.textContent === '← All documents').click())
  expect(document.activeElement).toBe(open)
})
