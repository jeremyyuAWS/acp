/**
 * The scope-rule editor, RENDERED (Discover/Assess PRD §4.4 / AC-09, Phase C4d).
 *
 * Pins five things: the create form POSTs the right body (selector/value/codes/priority/override/
 * enabled); the Core-17 multi-select renders "code — name"; a validation 400 shows inline; the list
 * renders existing rules with the OVERRIDE badge and enable/delete controls; and the scope-aware
 * eligibility summary renders and refreshes after a change.
 *
 * DOM-level, not browser-level: the preview server runs vite rooted at the SHARED checkout whatever
 * worktree you are in (CLAUDE.md), so this renders the component directly against mocked API calls.
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

afterEach(unmountAll)

const api = {
  fetchScopeSelectors: null, fetchScopeRules: null, createScopeRule: null,
  setScopeRuleEnabled: null, deleteScopeRule: null, fetchScopedEligibility: null,
}
vi.mock('./api.js', () => ({
  fetchScopeSelectors: (...a) => api.fetchScopeSelectors(...a),
  fetchScopeRules: (...a) => api.fetchScopeRules(...a),
  createScopeRule: (...a) => api.createScopeRule(...a),
  setScopeRuleEnabled: (...a) => api.setScopeRuleEnabled(...a),
  deleteScopeRule: (...a) => api.deleteScopeRule(...a),
  fetchScopedEligibility: (...a) => api.fetchScopedEligibility(...a),
}))

const { default: ScopeRules } = await import('./ScopeRules.jsx')

const CATALOG = [
  { code: '1.1.1', name: 'Non-text Content', formats: ['docx', 'pdf'] },
  { code: '1.4.3', name: 'Contrast (Minimum)', formats: ['docx', 'pdf', 'pptx'] },
  { code: '2.4.6', name: 'Headings and Labels', formats: ['docx'] },
]
const SELECTORS = ['folder', 'owner', 'department']

const settle = async () => { await act(async () => { await new Promise((r) => setTimeout(r, 0)) }) }
const click = async (el) => { await act(async () => { el.click() }) }
const set = async (el, value) => {
  await act(async () => {
    const proto = el.tagName === 'SELECT' ? window.HTMLSelectElement.prototype : window.HTMLInputElement.prototype
    Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, value)
    el.dispatchEvent(new Event('input', { bubbles: true }))
    el.dispatchEvent(new Event('change', { bubbles: true }))
  })
}
const btn = (c, re) => [...c.querySelectorAll('button')].find((b) => re.test(b.textContent))
const codeBox = (c, code) => [...c.querySelectorAll('input[type=checkbox]')]
  .find((e) => (e.getAttribute('aria-label') || '').startsWith(code + ' '))
const field = (c, label) => c.querySelector(`[aria-label="${label}"]`)

async function render({ rules = [], eligibility = { discovered: 100, eligible: 60, by_format: { docx: 60 }, rules_applied: rules.filter((r) => r.enabled).length } } = {}) {
  api.fetchScopeSelectors = vi.fn(async () => ({ selectors: SELECTORS, codes: CATALOG }))
  api.fetchScopeRules = vi.fn(async () => rules)
  api.createScopeRule = vi.fn(async (body) => ({ rule_id: 'new', ...body }))
  api.setScopeRuleEnabled = vi.fn(async () => ({}))
  api.deleteScopeRule = vi.fn(async () => ({ deleted: 'x' }))
  api.fetchScopedEligibility = vi.fn(async () => eligibility)
  const { root, container } = createTestRoot()
  await act(async () => { root.render(createElement(ScopeRules)) })
  await settle()
  return { c: container }
}


describe('the Core-17 multi-select renders code + name', () => {
  it('shows each catalog entry as "code — name"', async () => {
    const { c } = await render()
    expect(c.textContent).toContain('1.4.3 — Contrast (Minimum)')
    expect(codeBox(c, '1.4.3').getAttribute('aria-label')).toBe('1.4.3 — Contrast (Minimum)')
    expect([...c.querySelectorAll('.scoperules-code')].length).toBe(3)
  })
})


describe('the create form posts the right body', () => {
  it('sends selector, value, selected codes, priority, override and enabled', async () => {
    const { c } = await render()
    await set(field(c, 'Selector'), 'owner')
    await set(field(c, 'owner email'), 'jordan@acme.com')
    await click(codeBox(c, '1.4.3'))
    await click(codeBox(c, '2.4.6'))
    await set(field(c, 'Priority'), '5')
    await click(field(c, 'Override'))
    await click(btn(c, /Create scope rule/))
    await settle()

    expect(api.createScopeRule).toHaveBeenCalledTimes(1)
    const body = api.createScopeRule.mock.calls[0][0]
    expect(body.selector).toBe('owner')
    expect(body.value).toBe('jordan@acme.com')
    expect([...body.codes].sort()).toEqual(['1.4.3', '2.4.6'])
    expect(body.priority).toBe(5)
    expect(body.is_override).toBe(true)
    expect(body.enabled).toBe(true)
  })

  it('labels the value input per selector', async () => {
    const { c } = await render()
    expect(field(c, 'folder path'), 'default is the folder-path label').toBeTruthy()
    await set(field(c, 'Selector'), 'department')
    expect(field(c, 'department'), 'switches to the department label').toBeTruthy()
  })
})


describe('a validation 400 shows inline', () => {
  it('surfaces the backend detail without throwing', async () => {
    const { c } = await render()
    api.createScopeRule = vi.fn(async () => { throw new Error('codes not in the allowed Core-17 set: ["9.9.9"]') })
    await set(field(c, 'folder path'), 'Finance/')
    await click(codeBox(c, '1.1.1'))
    await click(btn(c, /Create scope rule/))
    await settle()
    expect(c.querySelector('.scoperules-err')?.textContent).toContain('codes not in the allowed Core-17 set')
  })

  it('blocks an empty selection client-side with a message', async () => {
    const { c } = await render()
    await set(field(c, 'folder path'), 'Finance/')   // value present, but no codes ticked
    await click(btn(c, /Create scope rule/))
    await settle()
    expect(api.createScopeRule).not.toHaveBeenCalled()
    expect(c.querySelector('.scoperules-err')?.textContent).toMatch(/at least one WCAG code/)
  })
})


describe('the list renders rules with the override badge and controls', () => {
  const RULES = [
    { rule_id: 'r1', name: 'Finance — full AA', selector: 'folder', value: 'Finance/', codes: ['1.4.3'], priority: 10, is_override: true, enabled: true },
    { rule_id: 'r2', name: 'HR subset', selector: 'department', value: 'HR', codes: ['1.1.1', '2.4.6'], priority: 2, is_override: false, enabled: false },
  ]

  it('shows an OVERRIDE badge only on the override rule', async () => {
    const { c } = await render({ rules: RULES })
    const cards = [...c.querySelectorAll('.scoperule')]
    expect(cards.length).toBe(2)
    const overrides = [...c.querySelectorAll('.scoperule-override')]
    expect(overrides.length).toBe(1)
    expect(cards[0].textContent).toContain('OVERRIDE')       // r1, priority 10, listed first
    expect(cards[0].textContent).toContain('Finance/')
    expect(cards[0].textContent).toContain('priority 10')
  })

  it('toggles a rule via setScopeRuleEnabled and re-reads the list', async () => {
    const { c } = await render({ rules: RULES })
    const enableBtn = btn(c, /^Enable$/)          // r2 is disabled → offers Enable
    expect(enableBtn).toBeTruthy()
    api.fetchScopeRules.mockClear()
    await click(enableBtn)
    await settle()
    expect(api.setScopeRuleEnabled).toHaveBeenCalledWith('r2', true)
    expect(api.fetchScopeRules).toHaveBeenCalled()  // refreshed after the change
  })

  it('deletes a rule via deleteScopeRule', async () => {
    const { c } = await render({ rules: RULES })
    const del = [...c.querySelectorAll('.scoperule-del')][0]
    await click(del)
    await settle()
    expect(api.deleteScopeRule).toHaveBeenCalledWith('r1')
  })
})


describe('the scoped-eligibility summary renders', () => {
  it('states eligible-of-discovered and how many rules reach a file', async () => {
    const { c } = await render({
      rules: [{ rule_id: 'r1', name: 'F', selector: 'folder', value: 'Finance/', codes: ['1.4.3'], priority: 1, is_override: false, enabled: true }],
      eligibility: { discovered: 175, eligible: 92, by_format: { docx: 92 }, rules_applied: 1 },
    })
    const text = c.querySelector('.scoperules-elign')?.textContent || ''
    expect(text).toMatch(/92\b/)
    expect(text).toMatch(/175\b/)
    expect(text).toMatch(/1 rule\b/)
  })
})
