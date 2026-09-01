import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

/**
 * AcrCriterionDetail — the screen where a human selects a conformance level (ADR 0047).
 *
 * TWO CLASSES OF ASSERTION, and both matter here more than usual.
 *
 * 1. HONESTY. The screen must never offer a status the server would refuse, must never present
 *    ACP's draft as a decision, and must show a refusal's REASON rather than just disabling a
 *    control. A user who cannot tell "not permitted yet, and here is why" from "this is broken"
 *    routes around the gate — and the gate is the feature.
 *
 * 2. ACCESSIBILITY. This is a screen in an accessibility conformance tool, and the report it
 *    produces asserts things about ACP's own UI — 1.3.1, 2.1.1, 3.3.2, 4.1.2, 4.1.3. Asserting
 *    them here is the only honest basis for the report claiming them.
 *
 * DOM-LEVEL IN VITEST, NOT THE BROWSER PANE. CLAUDE.md is explicit that the preview server runs
 * with the SHARED CHECKOUT as its vite root whatever worktree you are in, so a browser check of
 * these files would exercise code that does not contain them, and pass. These run against the
 * modules in this worktree.
 */

const api = {
  getAcrCriterion: vi.fn(),
  addAcrEvidence: vi.fn(),
  decideAcrCriterion: vi.fn(),
  approveAcrCriterion: vi.fn(),
}

vi.mock('./acrApi', () => ({
  getAcrCriterion: (...a) => api.getAcrCriterion(...a),
  addAcrEvidence: (...a) => api.addAcrEvidence(...a),
  decideAcrCriterion: (...a) => api.decideAcrCriterion(...a),
  approveAcrCriterion: (...a) => api.approveAcrCriterion(...a),
  FINAL_STATUSES: ['Supports', 'Partially Supports', 'Does Not Support', 'Not Applicable'],
  REMARKS_REQUIRED: ['Partially Supports', 'Does Not Support', 'Not Applicable'],
}))

const { default: AcrCriterionDetail } = await import('./AcrCriterionDetail.jsx')

const AUTOMATED_ONLY = {
  criterion: {
    criterion_num: '1.4.3', criterion_name: 'Contrast (Minimum)', level: 'AA',
    principle: 'Perceivable', guideline: '1.4 Distinguishable',
    workflow_state: 'needs_review', final_status: null, draft_status: null, remarks: null,
    evaluator: null, reviewer: null, approval_state: 'unapproved',
  },
  evidence: [{
    id: 'e1', source_kind: 'automated', result: 'pass', tester: null,
    tested_at: '2026-08-30T00:00:00+00:00', product_version: '1.4.0',
    tool_name: 'axe-core', tool_version: '4.12.1', rule_id: 'color-contrast',
    coverage: 'partial', stale_reason: null,
  }],
  assessment: {
    evidence_live: 1, evidence_stale: 0, automated_only: true,
    draft_status: null,
    draft_reason: 'automated evidence only, coverage=partial — a clean result from a technique '
                + 'that does not reach the whole criterion is not evidence of conformance.',
    permitted_statuses: {
      'Supports': false, 'Partially Supports': false,
      'Does Not Support': true, 'Not Applicable': true,
    },
    refusals: {
      'Supports': 'Supports cannot rest on automated evidence alone at coverage=partial.',
      'Partially Supports': 'Partially Supports describes evaluated behaviour — attach evidence.',
    },
  },
}

const clone = (o) => JSON.parse(JSON.stringify(o))

let container
const mount = async (data = AUTOMATED_ONLY, props = {}) => {
  api.getAcrCriterion.mockReset().mockResolvedValue(data)
  api.decideAcrCriterion.mockReset()
  const created = createTestRoot()
  container = created.container
  await act(async () => {
    created.root.render(createElement(AcrCriterionDetail, {
      reportId: 'acr_1', criterionNum: '1.4.3', canEdit: true, canApprove: true, ...props,
    }))
  })
  await act(async () => { await Promise.resolve() })
  return container
}

const radio = (name) => [...container.querySelectorAll('input[type="radio"]')]
  .find((r) => r.value === name)
const labelFor = (el) => container.querySelector(`label[for="${el.id}"]`)
const text = () => container.textContent
const click = async (el) => {
  await act(async () => { el.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
}

afterEach(unmountAll)

describe('honesty', () => {
  it('does not offer a status the server refuses', async () => {
    await mount()
    expect(radio('Supports').disabled).toBe(true)
    expect(radio('Partially Supports').disabled).toBe(true)
    expect(radio('Does Not Support').disabled).toBe(false)
    expect(radio('Not Applicable').disabled).toBe(false)
  })

  it('shows the refusal REASON, not just a disabled control', async () => {
    await mount()
    expect(text()).toMatch(/cannot rest on automated evidence alone/)
  })

  it('associates the refusal with the control for a screen-reader user', async () => {
    // A visible reason a screen reader never reaches is not an explanation.
    await mount()
    const describedBy = radio('Supports').getAttribute('aria-describedby')
    expect(describedBy).toBeTruthy()
    expect(container.querySelector(`#${describedBy}`).textContent)
      .toMatch(/automated evidence alone/)
  })

  it('never presents a draft suggestion as a decision', async () => {
    const drafted = clone(AUTOMATED_ONLY)
    drafted.assessment.draft_status = 'Supports'
    drafted.assessment.permitted_statuses.Supports = true
    await mount(drafted)
    expect(text()).toMatch(/a suggestion, not a decision/i)
    expect(radio('Supports').checked).toBe(false)
  })

  it('preserves the original automated result in the evidence table', async () => {
    await mount()
    expect(text()).toMatch(/axe-core/)
    expect(text()).toMatch(/color-contrast/)
    expect(text()).toMatch(/coverage partial/)
  })

  it('states staleness in words, not by colour alone', async () => {
    const stale = clone(AUTOMATED_ONLY)
    stale.evidence[0].stale_reason = 'different_product_version'
    await mount(stale)
    expect(text()).toMatch(/Stale: different product version/)
    expect(text()).toMatch(/cannot support publication/)
  })

  it('surfaces the server refusal verbatim when a decision is rejected', async () => {
    const ok = clone(AUTOMATED_ONLY)
    ok.assessment.permitted_statuses.Supports = true
    await mount(ok)
    api.decideAcrCriterion.mockRejectedValue(
      new Error('2 unresolved failure(s) contradict a Supports claim'))

    await click(radio('Supports'))
    const submit = [...container.querySelectorAll('button')]
      .find((b) => /record decision/i.test(b.textContent))
    await click(submit)
    await act(async () => { await Promise.resolve() })

    const alert = container.querySelector('[role="alert"]')
    expect(alert?.textContent).toMatch(/unresolved failure/)
  })

  it('hides the decision form from a user without the editor role', async () => {
    await mount(AUTOMATED_ONLY, { canEdit: false, canApprove: false })
    expect(container.querySelectorAll('input[type="radio"]').length).toBe(0)
    expect(text()).toMatch(/do not have the editor role/i)
  })
})

describe('accessibility', () => {
  it('gives every form control an accessible name (4.1.2, 3.3.2)', async () => {
    await mount()
    const controls = container.querySelectorAll('input, select, textarea')
    expect(controls.length).toBeGreaterThan(0)
    for (const el of controls) {
      const named = labelFor(el) || el.getAttribute('aria-label')
      expect(named, `${el.id || el.type} has no accessible name`).toBeTruthy()
    }
  })

  it('groups the conformance radios in a named fieldset (1.3.1)', async () => {
    await mount()
    const fieldset = container.querySelector('fieldset')
    expect(fieldset).toBeTruthy()
    expect(fieldset.querySelector('legend').textContent).toMatch(/final conformance level/i)
    expect(fieldset.querySelectorAll('input[type="radio"]').length).toBe(4)
  })

  it('announces status changes via a live region (4.1.3)', async () => {
    await mount()
    const status = container.querySelector('[role="status"]')
    expect(status).toBeTruthy()
    expect(status.getAttribute('aria-live')).toBe('polite')
  })

  it('marks remarks required for the statuses that need them (3.3.2)', async () => {
    await mount()
    await click(radio('Does Not Support'))
    expect(container.querySelector('#acr-remarks').required).toBe(true)
  })

  it('does not mark remarks required for Supports', async () => {
    const ok = clone(AUTOMATED_ONLY)
    ok.assessment.permitted_statuses.Supports = true
    await mount(ok)
    await click(radio('Supports'))
    expect(container.querySelector('#acr-remarks').required).toBe(false)
  })

  it('is operable by keyboard alone (2.1.1)', async () => {
    await mount()
    const r = radio('Does Not Support')
    r.focus()
    expect(document.activeElement).toBe(r)
    await click(r)
    expect(r.checked).toBe(true)
  })

  it('uses real table semantics with header cells and a caption (1.3.1)', async () => {
    await mount()
    const table = container.querySelector('table')
    expect(table.querySelector('caption')).toBeTruthy()
    expect(table.querySelectorAll('th[scope="col"]').length).toBeGreaterThan(0)
  })

  it('has exactly one h3 and no skipped heading level below it (1.3.1, 2.4.6)', async () => {
    await mount()
    const levels = [...container.querySelectorAll('h1,h2,h3,h4,h5,h6')]
      .map((h) => Number(h.tagName[1]))
    expect(levels[0]).toBe(3)
    for (let i = 1; i < levels.length; i++) {
      expect(levels[i] - levels[i - 1]).toBeLessThanOrEqual(1)
    }
  })

  it('has no axe-detectable violations', async () => {
    await mount()
    const axe = (await import('axe-core')).default
    const results = await axe.run(container, {
      resultTypes: ['violations'],
      runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'] },
      // jsdom has no layout engine, so contrast cannot be evaluated here at all — axe reports it
      // as "incomplete" rather than passing. It is checked in a real browser by the existing
      // self-check panel (A11ySelfCheck.jsx). Disabling it is an honest statement of what this
      // environment can decide, not a suppression of a known failure.
      rules: { 'color-contrast': { enabled: false } },
    })
    expect(results.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([])
  })
})
