import { afterEach, describe, expect, it } from 'vitest'
import { createElement, act } from 'react'
import axe from 'axe-core'
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
  it('is a prominent preview with five exact, aligned, clickable snap points', async () => {
    const container = await mount({ findings: [], runId: 'run-1' })
    const slider = container.querySelector('input[type="range"]')
    expect(container.textContent).toContain('Choose how much ACP can automate')
    expect(container.textContent).toContain('Preview only')
    expect(slider.min).toBe('1')
    expect(slider.max).toBe('5')
    expect(slider.getAttribute('aria-valuetext')).toContain('Balanced')
    const ticks = [...container.querySelectorAll('.automation-policy__ticks button')]
    expect(ticks.map((tick) => tick.style.left))
      .toEqual(['0%', '25%', '50%', '75%', '100%'])
    expect(ticks.map((tick) => tick.textContent)).toEqual(['Strict', 'Cautious', 'Balanced', 'Assisted', 'Maximum'])
    await act(async () => { ticks[4].click() })
    expect(slider.value).toBe('5')
    expect(ticks[4].getAttribute('aria-current')).toBe('step')
  })

  it('updates its honest current-queue forecast without changing the run', async () => {
    const container = await mount({
      runId: 'run-2',
      findings: [{ file: 'benefits.docx', rule_id: 'WCAG_2_4_4', hasProposal: true, proposals: [{ proposed_value: 'Learn about benefits' }] }],
    })
    const slider = container.querySelector('input[type="range"]')
    expect(container.textContent).toContain('Balanced would automate none')
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(slider, '4')
      slider.dispatchEvent(new Event('input', { bubbles: true }))
    })
    expect(container.querySelector('.automation-policy__policies .is-preview strong').textContent).toBe('Assisted')
    expect(container.textContent).toContain('1 finding across 1 file')
    expect(container.textContent).toContain('ACP automates')
    const delta = container.querySelector('.automation-policy__delta')
    expect(delta.textContent).toBe('+1 vs production')
    expect(container.textContent).toContain('The remaining 0 stay with people.')
    expect(container.textContent).toContain('This preview does not change the active run or production policy.')
  })

  it('animates and announces a negative delta when the threshold becomes stricter', async () => {
    const container = await mount({
      runId: 'run-3',
      findings: [{ file: 'contrast.docx', rule_id: 'WCAG_1_4_3', hasProposal: true,
        proposals: [{ proposed_value: '#595959' }] }],
    })
    const slider = container.querySelector('input[type="range"]')
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(slider, '1')
      slider.dispatchEvent(new Event('input', { bubbles: true }))
    })
    const deltas = [...container.querySelectorAll('.automation-policy__delta')]
    expect(deltas.map((node) => node.textContent)).toEqual(['−1 vs production', '+1 total human decisions'])
  })

  it('shows allocation and an explainable human-review breakdown', async () => {
    const container = await mount({
      runId: 'run-4',
      findings: [
        { file: 'draft.docx', rule_id: 'WCAG_2_4_4', hasProposal: true, proposals: [{ proposed_value: 'Better link' }] },
        { file: 'manual.pdf', rule_id: 'WCAG_1_1_1', hasProposal: false, proposals: [] },
        { file: 'rejected.pptx', rule_id: 'WCAG_1_4_3', hasProposal: true, rejectedFix: true },
      ],
    })
    expect(container.textContent).toContain('Balanced would automate none of the 3 open findings')
    expect(container.querySelector('.automation-policy__flow').getAttribute('aria-label'))
      .toBe('Routing impact: 3 open findings; 0 automated; 1 sent to review; 2 always requires a person')
    expect(container.textContent).toContain('Why 3 findings stay with people')
    expect(container.textContent).toContain('Needs authoring')
    expect(container.textContent).toContain('Previously rejected')
  })

  it('visibly separates the production policy from the selected preview', async () => {
    const container = await mount({ findings: [], runId: 'policies' })
    expect(container.querySelector('.automation-policy__policies').textContent)
      .toContain('Current production policyBalanced')
    await act(async () => { container.querySelectorAll('.automation-policy__ticks button')[0].click() })
    expect(container.querySelector('.automation-policy__policies').textContent)
      .toContain('Preview policyStrict')
  })

  it('keeps native keyboard and touch semantics on the range control', async () => {
    const container = await mount({ findings: [], runId: 'input' })
    const slider = container.querySelector('input[type="range"]')
    slider.focus()
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(slider, '4')
      slider.dispatchEvent(new Event('change', { bubbles: true }))
    })
    expect(slider.value).toBe('4')
    expect(slider.step).toBe('1')
    expect(slider.getAttribute('aria-valuetext')).toContain('Assisted')
  })

  it.each([
    [{ previewStatus: 'pending', findings: [] }, 'Calculating routing impact'],
    [{ findings: null }, 'Routing impact is unavailable'],
    [{ previewStatus: 'error', findings: [] }, 'Routing impact is unavailable'],
    [{ previewStatus: 'inconsistent', findings: [] }, 'Routing impact could not be reconciled'],
  ])('renders honest pending and unknown states', async (props, copy) => {
    const container = await mount(props)
    expect(container.textContent).toContain(copy)
    expect(container.querySelector('.automation-policy__flow')).toBeNull()
  })

  it('uses a truthful zero state when the run has no findings', async () => {
    const container = await mount({ findings: [] })
    expect(container.textContent).toContain('no open eligible findings')
    expect(container.textContent).toContain('no policy has anything to automate or route')
  })

  it('exposes its routing relationship as one labelled flow and no KPI grid', async () => {
    const container = await mount({ findings: [
      { file: 'a.docx', rule_id: 'WCAG_1_4_3', hasProposal: true, proposals: [{ proposed_value: '#555' }] },
    ] })
    expect(container.querySelector('.automation-policy__flow')).not.toBeNull()
    expect(container.querySelector('.automation-policy__forecast')).toBeNull()
    expect(container.querySelector('.automation-policy__flow').getAttribute('aria-label')).toMatch(/Routing impact/)
  })

  it('has no automated accessibility violations', async () => {
    const container = await mount({ findings: [
      { file: 'a.docx', rule_id: 'WCAG_2_4_4', hasProposal: true, proposals: [{ proposed_value: 'Policy details' }] },
    ] })
    const result = await axe.run(container, { rules: { region: { enabled: false } } })
    expect(result.violations).toEqual([])
  })
})
