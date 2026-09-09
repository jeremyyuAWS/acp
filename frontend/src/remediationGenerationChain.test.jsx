import { act, createElement, useState } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import Options from './RemediationGenerationChain.jsx'
import { generationChainProblem, secondFallbackUnavailable, withSecondFallback } from './remediationGenerationChain.js'
globalThis.IS_REACT_ACT_ENVIRONMENT = true
afterEach(unmountAll)
const step = (model, position) => ({ step_id: ['primary', 'fallback_1', 'fallback_2'][position], position, provider: 'fixture-provider', model, enabled: true, capabilities: ['text'] })
const catalog = () => ({ version: 1, supported: true, max_steps: 3, default_steps: [step('primary-model', 0), step('fallback-model', 1)], models: ['primary-model', 'fallback-model', 'third-model'].map(model => ({ provider: 'fixture-provider', model, capabilities: ['text'], allowed: true, available: true })) })
const policy = () => ({ ai: 1, rule_based: 2, ai_budget_usd: '10.00' })
const click = async el => act(async () => el.click())
async function mount(extra = {}) {
  const { root, container } = createTestRoot(), changed = vi.fn()
  function Fixture(props) {
    const [value, setValue] = useState(props.initial || policy())
    return createElement(Options, { policy: value, options: catalog(), budgetSupported: true, ...props, onChange: (key, next) => { changed(key, next); setValue(current => ({ ...current, [key]: next })) } })
  }
  const render = async props => act(async () => root.render(createElement(Fixture, { ...extra, ...props })))
  await render()
  return { container, changed, render }
}
it('starts off in a closed disclosure without changing the old plan or dispatching work', async () => {
  const v = await mount()
  expect(v.container.querySelector('details').open).toBe(false)
  expect(v.container.querySelector('input').checked).toBe(false)
  expect(v.container.textContent).toContain('fixture-provider · primary-model')
  await click(v.container.querySelector('summary'))
  expect(v.changed).not.toHaveBeenCalled()
})
it('freezes all three steps and removes only the third when turned off', async () => {
  const options = catalog(), v = await mount({ options })
  await click(v.container.querySelector('input'))
  const chain = v.changed.mock.calls[0][1]
  expect(chain).toEqual({ version: 1, steps: [...options.default_steps, step('third-model', 2)] })
  expect(v.container.querySelectorAll('option')).toHaveLength(1)
  expect(v.container.querySelector('[role=note]').textContent).toContain('Account access')
  options.default_steps[0].model = 'settings-changed-later'
  expect(chain.steps[0].model).toBe('primary-model')
  await click(v.container.querySelector('input'))
  expect(v.changed.mock.calls[1][1].steps).toEqual(chain.steps.slice(0, 2))
})
it.each([
  ['missing metadata', undefined, '10.00', 'not available'],
  ['unsupported scope', { ...catalog(), supported: false, reason: 'Only exact slide-title findings are supported.' }, '10.00', 'Only exact slide-title'],
  ['zero budget', catalog(), '0.00', 'positive AI spending'],
  ['denied provider', { ...catalog(), models: catalog().models.map(m => ({ ...m, allowed: false })) }, '10.00', 'permitted text models'],
  ['third unavailable', { ...catalog(), models: catalog().models.slice(0, 2) }, '10.00', 'No distinct'],
])('disables with an explicit reason: %s', async (_name, options, budget, reason) => {
  const v = await mount({ options, initial: { ...policy(), ai_budget_usd: budget } })
  expect(v.container.querySelector('input').disabled).toBe(true)
  expect(v.container.textContent).toContain(reason)
  await click(v.container.querySelector('input'))
  expect(v.changed).not.toHaveBeenCalled()
})
it('preserves the selected chain after a settings refresh and reports revoked permission', async () => {
  const options = catalog(), initial = { ...policy(), generation_chain: withSecondFallback(policy(), options, options.models[2]) }
  const v = await mount({ initial })
  await v.render({ options: { ...catalog(), default_steps: [step('new-primary', 0), step('new-first', 1)], models: catalog().models.map(m => ({ ...m, allowed: false })) } })
  expect(v.container.textContent).toContain('fixture-provider · primary-model')
  expect(v.container.textContent).toContain('no longer available or permitted')
  expect(v.changed).not.toHaveBeenCalled()
  expect(v.container.querySelector('input').disabled).toBe(false)
})
it('rejects duplicate, cross-provider and unordered steps; absent legacy chains remain valid', () => {
  const options = catalog(), chain = withSecondFallback(policy(), options, options.models[2])
  expect(generationChainProblem(policy(), undefined, false)).toBeNull()
  for (const change of [{ model: 'primary-model' }, { provider: 'other-provider' }, { position: 1 }]) {
    const bad = { ...chain, steps: [chain.steps[0], chain.steps[1], { ...chain.steps[2], ...change }] }
    expect(generationChainProblem({ ...policy(), generation_chain: bad }, options, true)).toContain('invalid')
  }
  expect(secondFallbackUnavailable(policy(), options, false)).toContain('enforced')
})

it('displays the authoritative account-access caveat for the selected third model without probing it', async () => {
  const options = catalog()
  options.models[2] = { ...options.models[2], access_verified: false, reason: 'Configuration verified; account model access has not been tested.' }
  const v = await mount({ options })
  await click(v.container.querySelector('input'))
  expect(v.container.querySelector('[role=note]').textContent).toBe(options.models[2].reason)
  expect(v.changed).toHaveBeenCalledTimes(1)
})
