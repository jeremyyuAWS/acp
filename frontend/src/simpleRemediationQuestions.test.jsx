import { act, createElement } from 'react'
import { readFileSync } from 'node:fs'
import { afterEach, expect, it, vi } from 'vitest'
import Choices from './RemediationPlanChoices.jsx'
import { createTestRoot, unmountAll } from './testRoots.js'
globalThis.IS_REACT_ACT_ENVIRONMENT = true
afterEach(unmountAll)
it('shows only two questions and an honest disabled budget when AI is enabled', async () => {
  const { root, container } = createTestRoot()
  const changed = vi.fn()
  const render = async ai => act(async () => root.render(createElement(Choices, { policy: { rule_based: 0, ai }, onChange: changed })))
  await render(1)
  expect([...container.querySelectorAll('legend')].map(n => n.textContent)).toEqual(['1. Which changes may ACP apply?', '2. May ACP also try AI?'])
  expect(container.querySelectorAll('input[type=radio]')).toHaveLength(4)
  expect(container.querySelector('input[type=number]').disabled).toBe(true)
  expect(container.textContent).toContain('Spending limits are not available on this server')
  expect(container.textContent).not.toContain('Your remediation plan')
  expect(container.textContent).not.toContain('AI providers & budget')
  await act(async () => container.querySelectorAll('input[type=radio]')[1].click())
  expect(changed).toHaveBeenLastCalledWith('rule_based', 2)
  await act(async () => container.querySelectorAll('input[type=radio]')[2].click())
  expect(changed).toHaveBeenLastCalledWith('ai', 0)
  await render(0)
  expect(container.querySelector('input[type=number]')).toBeNull()
})
it('deliberately hides retired advanced controls and preserves their code', () => {
  const css = readFileSync('src/simple-remediation-questions.css', 'utf8')
  expect(css).toContain('.remediation-impact__settings > .remediation-impact__advanced,')
  expect(css).toContain('.remediation-impact__settings > .remediation-impact__providers { display: none; }')
  const component = readFileSync('src/RemediationPlanChoices.jsx', 'utf8')
  expect(component).toContain('export function RetiredRemediationPlanChoices')
  expect(component).not.toContain('<RetiredRemediationPlanChoices')
})

it('enables the budget only when the server supports enforcement and preserves zero', async () => {
  const { root, container } = createTestRoot()
  await act(async () => root.render(createElement(Choices, { policy: {rule_based: 2, ai: 1, ai_budget_usd: '0.00'}, budgetSupported: true, onChange: vi.fn() })))
  expect(container.querySelector('input[type=number]').disabled).toBe(false)
  expect(container.querySelector('input[type=number]').value).toBe('0.00')
  expect(container.textContent).toContain('Rule-based fixes continue')
  expect(container.textContent).toContain('Infrastructure costs are separate')
})

it('lets users choose the waterfall without approving AI edits or starting a run', async () => {
  const { root, container } = createTestRoot()
  const changed = vi.fn()
  const render = async policy => act(async () => root.render(createElement(Choices, {
    policy, budgetSupported: true, onChange: changed,
  })))
  await render({ rule_based: 2, ai: 0, ai_budget_usd: '25.00' })
  expect(container.querySelector('.remediation-waterfall-plan').textContent).toContain('No new AI suggestions')
  await act(async () => container.querySelectorAll('input[type=radio]')[3].click())
  expect(changed).toHaveBeenCalledExactlyOnceWith('ai', 1)
  await render({ rule_based: 2, ai: 1, ai_budget_usd: '25.00' })
  const summary = container.querySelector('.remediation-waterfall-plan')
  expect(summary.querySelectorAll('li')).toHaveLength(3)
  expect(summary.textContent).toContain('try one more model when the budget allows')
  expect(summary.textContent).toContain('Review and edit AI suggestions')
  expect(summary.textContent).toContain('not estimated yet')
  expect(summary.textContent).toContain('Approve plan and start')
  expect(container.querySelector('input[type=number]').value).toBe('25.00')
  await render({ rule_based: 0, ai: 1, ai_budget_usd: '0.00' })
  expect(container.querySelector('.remediation-waterfall-plan').textContent).toContain('Prepare rule-based changes for your approval')
  expect(container.querySelector('.remediation-waterfall-plan').textContent).toContain('No paid AI attempts will run')
})
