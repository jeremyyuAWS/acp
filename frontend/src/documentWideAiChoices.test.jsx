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
it('offers individual or document review with honest support scope', async () => {
  const { container, onChange } = await mount()
  const advanced = container.querySelector('.remediation-document-wide')
  expect(advanced.tagName).toBe('FIELDSET')
  expect(advanced.textContent).toContain('PDF form-field names')
  expect(advanced.textContent).toContain('Word image descriptions')
  expect(advanced.textContent).toContain('existing tagged PDF images')
  expect(advanced.textContent).toContain('unambiguous page-image evidence')
  const checkbox = advanced.querySelectorAll('input')[1]
  expect(checkbox.checked).toBe(false)
  expect(checkbox.closest('label').textContent).toContain('Review the document together')
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
  expect(container.querySelectorAll('.remediation-document-wide input')[1].disabled).toBe(true)
  expect(container.querySelector('.remediation-document-wide').textContent).toContain('Choose Cloud AI to review the document together')
})
it('reflects previously selected consent without changing approval settings', async () => {
  const { container, onChange } = await mount({ ...base, document_wide_ai: true, auto_approve_ai: true })
  expect(container.querySelectorAll('.remediation-document-wide input')[1].checked).toBe(true)
  expect(onChange).not.toHaveBeenCalled()
})
it('offers explicit full-PDF consent without silently upgrading old choices', async () => {
  const { container, onChange } = await mount({ ...base, document_wide_ai: true })
  const choices = container.querySelectorAll('.remediation-document-input input')
  expect(choices[0].checked).toBe(true)
  expect(choices[1].checked).toBe(false)
  expect(container.textContent).toContain('Full PDF — advanced preview')
  expect(container.textContent).toContain('Other file formats keep using extracted context')
  await act(async () => choices[1].click())
  expect(onChange).toHaveBeenCalledWith('document_wide_input_mode', 'native_pdf')
})
it('cannot select full-PDF processing without a positive budget', async () => {
  const { container } = await mount({ ...base, document_wide_ai: true, ai_budget_usd: '0.00' })
  expect(container.querySelectorAll('.remediation-document-input input')[1].disabled).toBe(true)
})
