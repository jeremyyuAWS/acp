import { afterEach, describe, expect, it } from 'vitest'
import { createElement, act } from 'react'
import AutomationPolicyControl from './AutomationPolicyControl.jsx'
import { createTestRoot, unmountAll } from './testRoots.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
afterEach(() => { sessionStorage.clear(); unmountAll() })

async function mount(props = {}) {
  const { container, root } = createTestRoot()
  await act(async () => { root.render(createElement(AutomationPolicyControl, props)) })
  return container
}

describe('AutomationPolicyControl', () => {
  it('is a prominent preview with an accessible five-level slider', async () => {
    const container = await mount({ findings: [], runId: 'run-1' })
    const slider = container.querySelector('input[type="range"]')
    expect(container.textContent).toContain('Choose how much ACP can automate')
    expect(container.textContent).toContain('Preview only')
    expect(slider.min).toBe('1')
    expect(slider.max).toBe('5')
    expect(slider.getAttribute('aria-valuetext')).toContain('Balanced')
  })

  it('updates its honest current-queue forecast without changing the run', async () => {
    const container = await mount({
      runId: 'run-2',
      findings: [{ file: 'benefits.docx', rule_id: 'WCAG_2_4_4', hasProposal: true, proposals: [{ proposed_value: 'Learn about benefits' }] }],
    })
    const slider = container.querySelector('input[type="range"]')
    expect(container.textContent).toContain('0 findings across 0 files')
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(slider, '4')
      slider.dispatchEvent(new Event('input', { bubbles: true }))
    })
    expect(container.querySelector('.automation-policy__selection strong').textContent).toBe('Assisted')
    expect(container.textContent).toContain('1 finding across 1 file')
    expect(container.textContent).toContain('eligible for automation')
    expect(container.textContent).toContain('This preview does not change the active run.')
  })
})
