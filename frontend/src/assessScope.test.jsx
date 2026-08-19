/**
 * The Assess-time scope picker, RENDERED (Discover/Assess PRD §4.4).
 *
 * Four things are pinned: it renders the Core-17 code-set as "code — name"; the eligible-file
 * count reflects the current selection (fetched live, debounced); Save writes scan_scope derived
 * from the selection; and the document-type picker is authoritative for the format axis — unticking
 * a format drops it from every criterion in the saved scope.
 *
 * DOM-level, not browser-level: the preview server runs vite rooted at the SHARED checkout whatever
 * worktree you are in (CLAUDE.md), so this renders the component directly against mocked API calls.
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

afterEach(unmountAll)

const api = { getSettings: null, updateSettings: null, fetchCodeset: null, fetchEligibility: null }
vi.mock('./api.js', () => ({
  getSettings: (...a) => api.getSettings(...a),
  updateSettings: (...a) => api.updateSettings(...a),
  fetchCodeset: (...a) => api.fetchCodeset(...a),
  fetchEligibility: (...a) => api.fetchEligibility(...a),
}))

const { default: AssessScope } = await import('./AssessScope.jsx')
const { SCOPE_UNIVERSE } = await import('./scopePresets.js')
const { TRACKED_17 } = await import('./ruleDetails.js')

// The catalog the endpoint would return — derived from the same generated tables the UI reads.
const CODESET = SCOPE_UNIVERSE.filter((r) => TRACKED_17.has(r.sc))
  .map((r) => ({ code: r.sc, name: r.name, formats: [...r.formats] }))

async function render(props = {}, { scan_scope = '' } = {}) {
  api.getSettings = vi.fn(async () => ({ scan_scope }))
  api.updateSettings = vi.fn(async () => ({}))          // not simulated → a real save
  api.fetchCodeset = vi.fn(async () => CODESET)
  // The eligible count is a function of the selected codes, so toggling a code visibly moves it.
  api.fetchEligibility = vi.fn(async (codes) => ({
    discovered: 100, eligible: codes.length, by_format: { docx: codes.length },
    formats: ['docx'], codes: [],
  }))
  const { root, container } = createTestRoot()
  await act(async () => { root.render(createElement(AssessScope, props)) })
  await settle()          // let the catalog load and the first eligibility fetch fire
  return { c: container }
}

// The eligibility fetch is debounced (300ms); a real wait lets it fire and its state settle.
const settle = async () => { await act(async () => { await new Promise((r) => setTimeout(r, 360)) }) }
const click = async (el) => { await act(async () => { el.click() }) }
const btn = (c, re) => [...c.querySelectorAll('button')].find((b) => re.test(b.textContent))
const codeBox = (c, code) => [...c.querySelectorAll('input[type=checkbox]')]
  .find((e) => (e.getAttribute('aria-label') || '').startsWith(code + ' '))
const chip = (c, fmt) => [...c.querySelectorAll('button[aria-pressed]')]
  .find((b) => new RegExp(`\\b${fmt}\\b`, 'i').test(b.textContent))
const eligText = (c) => c.querySelector('.assessscope-elign')?.textContent || ''
const savedScope = () => JSON.parse(api.updateSettings.mock.calls.at(-1)[0].scan_scope)


describe('the WCAG picker renders the Core 17 as code + name', () => {
  it('shows all seventeen with both the code and its title', async () => {
    const { c } = await render()
    const rows = [...c.querySelectorAll('.assessscope-code')]
    expect(rows.length).toBe(17)
    expect(c.textContent).toContain('1.4.3 — Contrast (Minimum)')
    // every row is a checkbox labelled "code — name"
    expect(codeBox(c, '1.4.3').getAttribute('aria-label')).toBe('1.4.3 — Contrast (Minimum)')
  })
})


describe('the eligible-file count reflects the selection', () => {
  it('starts at the full selection and drops when a code is unticked', async () => {
    const { c } = await render()
    expect(eligText(c)).toMatch(/17\s+files eligible/)

    await click(codeBox(c, '1.1.1'))          // 17 → 16 selected
    await settle()                            // debounced refetch
    expect(api.fetchEligibility).toHaveBeenLastCalledWith(expect.not.arrayContaining(['1.1.1']))
    expect(eligText(c)).toMatch(/16\s+files eligible/)
  })
})


describe('Save writes scan_scope from the selection', () => {
  it('derives the map as selected codes × selected document types', async () => {
    const { c } = await render()
    await click(btn(c, /Save assessment scope/))
    expect(api.updateSettings).toHaveBeenCalledTimes(1)
    const scope = savedScope()
    // all 17 selected by default, each on its full format set
    expect(Object.keys(scope).sort()).toEqual(CODESET.map((r) => r.code).sort())
    expect([...scope['1.4.3']].sort()).toEqual([...CODESET.find((r) => r.code === '1.4.3').formats].sort())
  })

  it('refuses an empty selection rather than storing "assess everything"', async () => {
    const { c } = await render()
    await click(btn(c, /Clear all/))
    await settle()
    const save = btn(c, /Save assessment scope/)
    expect(save.disabled).toBe(true)          // nothing to save
  })
})


describe('the document-type picker is authoritative for the format axis', () => {
  it('drops an unticked format from every criterion in the saved scope', async () => {
    const { c } = await render()
    const pdf = chip(c, 'PDF')
    expect(pdf, 'no PDF document-type chip').toBeTruthy()
    await click(pdf)                          // untick PDF
    await click(btn(c, /Save assessment scope/))
    const scope = savedScope()
    for (const [sc, fmts] of Object.entries(scope)) {
      expect(fmts, `${sc} kept pdf after it was unticked`).not.toContain('pdf')
    }
    // a criterion that only had pdf would drop out rather than save an empty list
    for (const [sc, fmts] of Object.entries(scope)) {
      expect(fmts.length, `${sc} saved with no formats`).toBeGreaterThan(0)
    }
  })
})
