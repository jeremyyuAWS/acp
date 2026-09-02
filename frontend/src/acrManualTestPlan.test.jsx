import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

/**
 * AcrManualTestPlan — the guided manual test plan runner (PRD §14, Phase 3).
 *
 * The properties worth pinning are the ones a reasonable person would break without noticing:
 *
 *   · the screen never says or implies that completing a plan is a pass (PRD §4.3),
 *   · every refusal sentence is the SERVER's, rendered verbatim, so the button the screen offers
 *     and the action the server permits cannot diverge,
 *   · which environment fields are required comes from the plan's own `needs`, not a list in the
 *     component — the same screen-disagrees-with-gate failure the metadata form avoids.
 */

const api = {
  getCriterionPlans: vi.fn(),
  startPlanRun: vi.fn(),
  recordPlanStep: vi.fn(),
  completePlanRun: vi.fn(),
}

vi.mock('./acrApi', () => ({
  getCriterionPlans: (...a) => api.getCriterionPlans(...a),
  startPlanRun: (...a) => api.startPlanRun(...a),
  recordPlanStep: (...a) => api.recordPlanStep(...a),
  completePlanRun: (...a) => api.completePlanRun(...a),
}))

const { default: AcrManualTestPlan } = await import('./AcrManualTestPlan.jsx')

const PLAN_DETAIL = {
  plan_id: 'status-messages',
  title: 'Status messages announced without focus movement',
  criteria: ['4.1.3'],
  why_manual: 'axe has NO rule for 4.1.3. Whether a status message is announced can only be heard.',
  needs: ['browser', 'assistive_tech', 'environment'],
  preconditions: ['Screen reader running with default verbosity.'],
  steps: [
    { action: 'Trigger each success message without moving focus.', expect: 'Each is announced.' },
    { action: 'Watch where focus is.', expect: 'Focus is not moved to the message.' },
  ],
  axe_rule_criteria: [],
  criteria_with_no_axe_rule: ['4.1.3'],
}

const base = (over = {}) => ({
  criterion_num: '4.1.3',
  plans: [{ plan_id: 'status-messages', title: PLAN_DETAIL.title, total_steps: 2,
            answered_steps: 0, started: false, complete: false,
            blocking_reason: 'not started', needs: PLAN_DETAIL.needs }],
  complete: false,
  blocking_reason: 'status-messages has not been started',
  note: 'Completing a plan records what a tester observed. It is not a pass and does not select '
        + 'a conformance status.',
  plan_detail: [PLAN_DETAIL],
  runs: [],
  step_outcomes: ['blocked', 'fail', 'not_applicable', 'pass'],
  ...over,
})

let container
const mount = async (data = base(), props = {}) => {
  api.getCriterionPlans.mockReset().mockResolvedValue(data)
  api.startPlanRun.mockReset().mockResolvedValue({ run_id: 'run1' })
  api.recordPlanStep.mockReset().mockResolvedValue({ complete: false })
  api.completePlanRun.mockReset().mockResolvedValue({ evidence_id: 'ev1' })
  const created = createTestRoot()
  container = created.container
  await act(async () => {
    created.root.render(createElement(AcrManualTestPlan, {
      reportId: 'acr_1', criterionNum: '4.1.3', canEdit: true, ...props,
    }))
  })
  await act(async () => { await Promise.resolve() })
  return container
}

const text = () => container.textContent
const button = (re) => [...container.querySelectorAll('button')].find((b) => re.test(b.textContent))
const click = async (el) => {
  await act(async () => { el.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
  await act(async () => { await Promise.resolve() })
}
const showSteps = () => click(button(/Show steps/))

afterEach(unmountAll)

describe('what the runner must not claim', () => {
  it('renders the server\'s "not a pass" note rather than paraphrasing it', async () => {
    await mount()
    expect(text()).toMatch(/It is not a pass and does not select a conformance status/)
  })

  it('states plan state in words, not by colour alone (1.4.1)', async () => {
    await mount()
    expect(text()).toMatch(/not started/)
  })

  it('reports what is outstanding using the server\'s own sentence', async () => {
    await mount(base({ blocking_reason: 'status-messages: 2 of 2 steps still have no recorded outcome' }))
    expect(text()).toMatch(/2 of 2 steps still have no recorded outcome/)
  })

  it('says when automation contributed nothing at all', async () => {
    // The honest framing of an axe gap: not "untested", but "the tool said nothing".
    await mount()
    await showSteps()
    expect(text()).toMatch(/axe-core has no rule at all for 4\.1\.3/)
  })
})

describe('required fields come from the plan, not from this component', () => {
  it('renders exactly the plan\'s declared needs, each required', async () => {
    await mount(base({
      runs: [{ id: 'run1', plan_id: 'status-messages', criterion_num: '4.1.3',
               steps: {}, evidence_id: null }],
      plans: [{ ...base().plans[0], started: true }],
    }))
    await showSteps()
    for (const f of PLAN_DETAIL.needs) {
      const el = container.querySelector(`#acr-plan-${f}`)
      expect(el, `${f} field missing`).toBeTruthy()
      expect(el.required).toBe(true)
    }
    // A field the plan does NOT declare must not be demanded.
    expect(container.querySelector('#acr-plan-viewport')).toBeNull()
  })
})

describe('running a plan', () => {
  it('starts a run', async () => {
    await mount()
    await showSteps()
    await click(button(/Start this plan/))
    expect(api.startPlanRun).toHaveBeenCalledWith('acr_1', '4.1.3', 'status-messages')
  })

  it('records every outcome the server offers, including fail', async () => {
    // A failing step must finish the step: completeness is about whether the tester looked.
    await mount(base({
      runs: [{ id: 'run1', plan_id: 'status-messages', criterion_num: '4.1.3',
               steps: {}, evidence_id: null }],
    }))
    await showSteps()
    await click(button(/^Failed/))
    expect(api.recordPlanStep).toHaveBeenCalledWith('acr_1', 'run1', 0, 'fail')
  })

  it('shows an already-recorded outcome as pressed', async () => {
    await mount(base({
      runs: [{ id: 'run1', plan_id: 'status-messages', criterion_num: '4.1.3',
               steps: { 0: 'pass' }, evidence_id: null }],
    }))
    await showSteps()
    const pressed = [...container.querySelectorAll('button[aria-pressed="true"]')]
    expect(pressed).toHaveLength(1)
    expect(pressed[0].textContent).toMatch(/Passed/)
  })

  it('surfaces a server refusal verbatim', async () => {
    await mount(base({
      runs: [{ id: 'run1', plan_id: 'status-messages', criterion_num: '4.1.3',
               steps: {}, evidence_id: null }],
    }))
    api.recordPlanStep.mockRejectedValue(new Error('this run is complete; start a new run'))
    await showSteps()
    await click(button(/^Passed/))
    expect(container.querySelector('[role="alert"]').textContent).toMatch(/this run is complete/)
  })

  it('offers no controls to a reader without edit rights', async () => {
    await mount(base(), { canEdit: false })
    await showSteps()
    expect(button(/Start this plan/)).toBeFalsy()
    expect(button(/^Passed/)).toBeFalsy()
  })
})

describe('accessibility', () => {
  it('announces plan progress through a live region (4.1.3)', async () => {
    await mount()
    expect(container.querySelector('[role="status"]').getAttribute('aria-live')).toBe('polite')
  })

  it('gives the step outcome buttons a group name and unique names (2.4.4, 1.3.1)', async () => {
    await mount(base({
      runs: [{ id: 'run1', plan_id: 'status-messages', criterion_num: '4.1.3',
               steps: {}, evidence_id: null }],
    }))
    await showSteps()
    const groups = [...container.querySelectorAll('[role="group"]')]
    expect(groups.length).toBe(PLAN_DETAIL.steps.length)
    expect(groups[0].getAttribute('aria-label')).toMatch(/step 1/)
    // Every "Passed" button reads the same visually; the visually-hidden suffix separates them.
    const passes = [...container.querySelectorAll('button')].filter((b) => /^Passed/.test(b.textContent))
    expect(new Set(passes.map((b) => b.textContent)).size).toBe(passes.length)
  })

  it('marks the disclosure with aria-expanded (4.1.2)', async () => {
    await mount()
    const toggle = button(/Show steps/)
    expect(toggle.getAttribute('aria-expanded')).toBe('false')
    await click(toggle)
    expect(button(/Hide steps/).getAttribute('aria-expanded')).toBe('true')
  })

  it('has no axe-detectable violations', async () => {
    await mount(base({
      runs: [{ id: 'run1', plan_id: 'status-messages', criterion_num: '4.1.3',
               steps: {}, evidence_id: null }],
    }))
    await showSteps()
    const axe = (await import('axe-core')).default
    const results = await axe.run(container, {
      resultTypes: ['violations'],
      runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'] },
      // jsdom has no layout engine, so contrast is undecidable here; A11ySelfCheck.jsx checks it
      // in a real browser. An honest statement of what this environment can decide.
      rules: { 'color-contrast': { enabled: false } },
    })
    expect(results.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([])
  })
})
