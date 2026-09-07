import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, createElement } from 'react'
import AutomationPolicyActions from './AutomationPolicyActions.jsx'
import { createTestRoot, unmountAll } from './testRoots.js'
import * as api from './api.js'

vi.mock('./api.js', () => ({ getRemediationAutomationPolicy: vi.fn(), submitRemediationPolicyAction: vi.fn() }))
globalThis.IS_REACT_ACT_ENVIRONMENT = true
afterEach(() => { vi.clearAllMocks(); unmountAll() })
const contract = { policy: { level: 3, revision: 7 }, capabilities: { apply_waiting: false } }

async function mount(props = {}) {
  api.getRemediationAutomationPolicy.mockResolvedValue(contract)
  const view = createTestRoot()
  await act(async () => { view.root.render(createElement(AutomationPolicyActions,
    { runId: 'r1', previewLevel: 4, onReset: vi.fn(), ...props })) })
  return view.container
}

describe('AutomationPolicyActions', () => {
  it('shows save/reset but hides unsafe active-run apply', async () => {
    const c = await mount()
    expect(c.textContent).toContain('Save for future runs')
    expect(c.textContent).toContain('Reset preview')
    expect(c.textContent).not.toContain('Apply to eligible waiting work')
  })
  it('submits revision and stable key and focuses confirmation', async () => {
    api.submitRemediationPolicyAction.mockResolvedValue({ policy: { level: 4, revision: 8 } })
    const c = await mount()
    await act(async () => { c.querySelector('button').click() })
    const args = api.submitRemediationPolicyAction.mock.calls[0]
    expect(args.slice(0, 4)).toEqual(['r1', 'save_future', 4, 7])
    expect(args[4].length).toBeGreaterThanOrEqual(16)
    expect(document.activeElement.getAttribute('role')).toBe('status')
  })
  it('resets to saved policy and focuses feedback', async () => {
    const onReset = vi.fn(); const c = await mount({ onReset })
    const reset = [...c.querySelectorAll('button')].find((b) => b.textContent === 'Reset preview')
    await act(async () => { reset.click() })
    expect(onReset).toHaveBeenCalledWith(3)
    expect(document.activeElement.getAttribute('role')).toBe('status')
  })
  it('keeps errors visible and focused', async () => {
    api.submitRemediationPolicyAction.mockRejectedValue(Object.assign(new Error('Policy changed'), { status: 409 }))
    const c = await mount(); await act(async () => { c.querySelector('button').click() })
    expect(document.activeElement.getAttribute('role')).toBe('alert')
    expect(document.activeElement.textContent).toBe('Policy changed')
  })
})
