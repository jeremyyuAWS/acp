import { afterEach, expect, it, vi } from 'vitest'
import { createElement, act } from 'react'
import RemediationPlanChoices from './RemediationPlanChoices.jsx'
import { createTestRoot, unmountAll } from './testRoots.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
afterEach(unmountAll)
const base = { rule_based: 2, ai: 1, ai_zone: 'any', ai_budget_usd: '1.00' }
async function mount(policy = base) {
  const { container, root } = createTestRoot()
  const onChange = vi.fn()
  await act(async () => root.render(createElement(RemediationPlanChoices, { step: 1, policy, onChange, budgetSupported: true })))
  return { container, onChange }
}
it('shows a collapsed, opt-in preview with honest support scope and an associated description', async () => {
  const { container, onChange } = await mount()
  const advanced = container.querySelector('.remediation-document-wide')
  expect(advanced.open).toBe(false)
  expect(advanced.textContent).toContain('Initially supports PDF form-field names')
  expect(advanced.textContent).toContain('not supported by this preview')
  const checkbox = advanced.querySelector('input')
  expect(checkbox.checked).toBe(false)
  expect(checkbox.closest('label').textContent).toContain('Document-wide AI fixes (preview)')
  expect(container.querySelector(`[id="${checkbox.getAttribute('aria-describedby')}"]`)).toBeTruthy()
  await act(async () => checkbox.click())
  expect(onChange).toHaveBeenCalledWith('document_wide_ai', true)
})
it('hides the option for rules only', async () => {
  const { container } = await mount({ ...base, ai: 0 })
  expect(container.querySelector('.remediation-document-wide')).toBeNull()
})
it('explains local-only unavailability and prevents selecting cloud processing', async () => {
  const { container } = await mount({ ...base, ai_zone: 'local' })
  expect(container.querySelector('.remediation-document-wide input').disabled).toBe(true)
  expect(container.querySelector('.remediation-document-wide').textContent).toContain('no document is sent to a cloud provider')
})
it('reflects previously selected consent without changing approval settings', async () => {
  const { container, onChange } = await mount({ ...base, document_wide_ai: true, auto_approve_ai: true })
  expect(container.querySelector('.remediation-document-wide input').checked).toBe(true)
  expect(onChange).not.toHaveBeenCalled()
})
