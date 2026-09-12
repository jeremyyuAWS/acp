import { act, createElement } from 'react'
import { readFileSync } from 'node:fs'
import { afterEach, expect, it, vi } from 'vitest'
import Choices from './RemediationPlanChoices.jsx'
import { createTestRoot, unmountAll } from './testRoots.js'
afterEach(unmountAll)
it('offers only application and local/cloud model choices, with no input or spending questions', async () => {
  const {root,container} = createTestRoot(), changed = vi.fn()
  await act(async () => root.render(createElement(Choices,{policy:{rule_based:2,ai:1,ai_zone:'local'},budgetSupported:true,onChange:changed})))
  expect([...container.querySelectorAll('legend')].map(n=>n.textContent)).toEqual(['1. Which changes may ACP apply?','2. Which models may ACP use?'])
  expect(container.querySelectorAll('input[type=radio]')).toHaveLength(4)
  expect(container.querySelector('input[type=number]')).toBeNull()
  expect(container.textContent).not.toContain('How should AI review')
  expect(container.textContent).not.toContain('What should Cloud AI receive')
  expect(container.textContent).not.toContain('AI spending limit')
  expect(container.textContent).not.toContain('AI provider details')
  expect(changed).not.toHaveBeenCalled()
  await act(async()=>container.querySelectorAll('input[type=radio]')[3].click())
  expect(changed).toHaveBeenCalledExactlyOnceWith('ai_mode','any')
  expect(container.textContent).toContain('full supported file')
})
it('leaves Q3 entirely to the publishing question supplied by the parent', async () => {
  const {root,container}=createTestRoot()
  await act(async()=>root.render(createElement(Choices,{step:2,policy:{rule_based:2,ai:1},onChange:vi.fn()})))
  expect(container.querySelectorAll('fieldset:not([hidden])')).toHaveLength(0)
  expect(container.querySelector('input[type=number]')).toBeNull()
})
it('retains the detailed controls without mounting them in the live choices', () => {
  const source=readFileSync('src/RemediationPlanChoices.jsx','utf8')
  expect(source).toContain('export function RetiredDetailedRemediationPlanChoices')
  expect(source).not.toContain('<RetiredDetailedRemediationPlanChoices')
  expect(source).toContain('AI spending limit for this run')
})
