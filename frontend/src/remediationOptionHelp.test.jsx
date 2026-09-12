import { act, createElement } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import Choices from './RemediationPlanChoices.jsx'
import { createTestRoot, unmountAll } from './testRoots.js'
globalThis.IS_REACT_ACT_ENVIRONMENT = true
afterEach(unmountAll)

it('offers separate accessible help without changing radio selection or budget', async () => {
  const { root, container } = createTestRoot()
  const changed = vi.fn()
  await act(async () => root.render(createElement(Choices, {
    policy: { rule_based: 0, ai: 1, ai_budget_usd: '25.00' },
    budgetSupported: true, onChange: changed,
  })))
  const buttons = [...container.querySelectorAll('.remediation-option-help button')]
  expect(buttons).toHaveLength(4)
  expect(container.querySelectorAll('.remediation-plan-option')).toHaveLength(4)
  expect(buttons.map(button => button.getAttribute('aria-label'))).toEqual([
    'About review before applying', 'About apply and verify automatically',
    'About local models', 'About local and cloud models',
  ])
  for (const button of buttons) {
    expect(button.closest('label')).toBeNull()
    await act(async () => button.focus())
    expect(container.querySelector('[role=tooltip]').id).toBe(button.getAttribute('aria-describedby'))
    await act(async () => button.click())
    expect(changed).not.toHaveBeenCalled()
    await act(async () => button.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })))
    expect(container.querySelector('[role=tooltip]')).toBeNull()
    await act(async () => button.blur())
  }
  await act(async () => buttons[0].focus())
  expect(container.querySelector('[role=tooltip]').textContent).toContain('AI is a separate choice')
  expect(container.querySelector('input[type=number]')).toBeNull()
  expect(container.querySelector('input[type=radio]').checked).toBe(true)
})

it('shows help on hover and keeps it visible while the pointer is over the explanation', async () => {
  const { root, container } = createTestRoot()
  await act(async () => root.render(createElement(Choices, { policy: { rule_based: 2, ai: 0 }, onChange: vi.fn() })))
  const help = container.querySelector('.remediation-option-help')
  await act(async () => help.dispatchEvent(new MouseEvent('mouseover', { bubbles: true })))
  expect(help.querySelector('[role=tooltip]')).not.toBeNull()
  await act(async () => help.dispatchEvent(new MouseEvent('mouseout', { bubbles: true, relatedTarget: document.body })))
  expect(help.querySelector('[role=tooltip]')).toBeNull()
})
