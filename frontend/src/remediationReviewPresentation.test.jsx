import { act, createElement } from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import RemediationInbox from './RemediationInbox.jsx'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
beforeEach(() => { localStorage.clear(); sessionStorage.clear() })
afterEach(async () => { await unmountAll(); vi.unstubAllGlobals() })
const longSource = 'The retained source passage contains important original content. '.repeat(100) + 'Exact source ending.'
const finding = { id: 1, file: 'annual-report.docx', title: 'DOCX · Passage language needs review', rule_id: '3.1.2', hasProposal: true, before: longSource, after: 'fr', rationale: 'Confirm the language before changing its metadata.' }
async function mount(overrides = {}, props = {}) {
  const { container, root } = createTestRoot()
  const onDecide = vi.fn(async () => {})
  await act(async () => root.render(createElement(RemediationInbox, { queue: [{ ...finding, ...overrides }], decisions: {}, onDecide, ...props })))
  return { container, root, onDecide }
}
it('keeps the review decision compact while retaining the full source in a closed disclosure', async () => {
  const { container, onDecide } = await mount()
  const comparison = container.querySelector('.remediation-comparison')
  expect(comparison.textContent.length).toBeLessThan(500)
  expect(comparison.textContent).toContain('fr')
  expect(comparison.textContent).toContain('excerpt')
  const source = [...container.querySelectorAll('details')].find(detail => detail.querySelector('summary')?.textContent === 'Show full source')
  expect(source).toBeTruthy()
  expect(source.open).toBe(false)
  expect(source.textContent).toContain(longSource)
  expect(container.querySelector('.remediation-review-problem').textContent.length).toBeLessThan(280)
  expect(container.querySelector('.remediation-detail-content').textContent).toContain('Confirm the language')
  await act(async () => { source.open = true; source.dispatchEvent(new Event('toggle')) })
  expect(onDecide).not.toHaveBeenCalled()
})
it('copies the exact source rather than its shortened preview', async () => {
  const copy = vi.fn(async () => {})
  vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText: copy } })
  const { container, onDecide } = await mount()
  const button = [...container.querySelectorAll('button')].find(button => button.textContent === 'Copy current')
  await act(async () => button.click())
  expect(copy).toHaveBeenCalledWith(longSource)
  expect(onDecide).not.toHaveBeenCalled()
})
it('never shortens the actual editable proposal or the saved decision', async () => {
  const proposed = 'A complete replacement description. '.repeat(50)
  const { container, onDecide } = await mount({ after: proposed })
  expect(container.querySelector('.remediation-comparison').textContent.length).toBeLessThan(850)
  expect(container.querySelector('textarea').value).toBe(proposed)
  const button = [...container.querySelectorAll('button')].find(button => button.textContent.includes('Yes, apply fix'))
  await act(async () => button.click())
  expect(onDecide).toHaveBeenCalledWith(expect.objectContaining({ id: 1 }), expect.objectContaining({ value: proposed }))
})
it('preserves short exact comparisons and keeps missing values explicit', async () => {
  const { container } = await mount({ before: null, after: 'French' })
  expect(container.querySelector('.remediation-comparison').textContent).toContain('Not recorded')
  expect(container.querySelector('.remediation-comparison').textContent).toContain('French')
  expect([...container.querySelectorAll('summary')].some(summary => summary.textContent === 'Show full source')).toBe(false)
})
