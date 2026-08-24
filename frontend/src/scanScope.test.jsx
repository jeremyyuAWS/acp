/**
 * The admin scan-scope grid: what it offers, and what it refuses to do quietly.
 *
 * The load-bearing case is `test an empty selection is refused, not saved`. On the backend `{}`
 * means NO RESTRICTION — `in_scope()` has always treated a falsy scope as "everything" — so a
 * grid with nothing ticked, saved literally, would assess the entire estate while looking on
 * screen exactly like "assess nothing". That is the one bug in this panel that would be both
 * silent and the precise opposite of the operator's intent, so it is refused with a reason
 * rather than translated.
 *
 * The grid itself is derived from scopePresets.js (generated from all three routes the backend
 * reaches a verdict by — RULE_FORMATS, REVIEW_FORMATS and the capability registry — CI-guarded
 * against drift in BOTH directions since #152), so these tests deliberately assert
 * BEHAVIOUR against that data rather than re-listing criteria — a test that retyped the universe
 * would be the second hand-maintained copy the codegen exists to prevent.
 *
 * DOM-level, not browser-level: this repo's preview server runs vite rooted at the SHARED
 * checkout whatever worktree you are in, so a browser check of a worktree change exercises code
 * that does not contain it (see CLAUDE.md).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

afterEach(unmountAll)

const settingsMock = { get: null, put: null }
vi.mock('./api.js', () => ({
  getSettings: (...a) => settingsMock.get(...a),
  updateSettings: (...a) => settingsMock.put(...a),
}))

const { default: ScanScope, parseStoredScope } = await import('./ScanScope.jsx')
const { SCOPE_PRESETS, SCOPE_UNIVERSE } = await import('./scopePresets.js')
const { TRACKED_17 } = await import('./ruleDetails.js')

// What the grid OFFERS — the universe narrowed to the criteria Mova iO tracks. Derived here the
// same way the component derives it, so these tests keep asserting behaviour against generated
// data rather than a hand-typed list (see the header).
const OFFERED = SCOPE_UNIVERSE.filter((r) => TRACKED_17.has(r.sc))

async function render(stored = '') {
  settingsMock.get = vi.fn(async () => ({ scan_scope: stored }))
  settingsMock.put = vi.fn(async (patch) => ({ scan_scope: typeof patch.scan_scope === 'string'
    ? patch.scan_scope : JSON.stringify(patch.scan_scope) }))
  const { root, container } = createTestRoot()
  await act(async () => { root.render(createElement(ScanScope)) })
  return container
}

const click = async (el) => { await act(async () => { el.click() }) }
const byLabel = (c, label) => [...c.querySelectorAll('input,button')]
  .find((e) => (e.getAttribute('aria-label') || '').includes(label))
const saveBtn = (c) => [...c.querySelectorAll('button')].find((b) => /Save scope/.test(b.textContent))
const status = (c) => c.querySelector('[role="status"]')?.textContent || ''


// ── the trap ──────────────────────────────────────────────────────────────────────────────────
describe('an empty selection under "restrict"', () => {
  it('is refused with a reason, and never sent', async () => {
    const c = await render('')                       // starts at "no restriction"
    const restrictRadio = c.querySelectorAll('input[type=radio]')[1]
    await click(restrictRadio)
    await click(saveBtn(c))

    expect(settingsMock.put).not.toHaveBeenCalled()
    expect(status(c)).toMatch(/assess everything/i)
  })
})


// ── loading ───────────────────────────────────────────────────────────────────────────────────
describe('loading the stored scope', () => {
  it('resolves a preset NAME into ticked boxes', async () => {
    const c = await render('engagement-14')
    const preset = SCOPE_PRESETS['engagement-14']
    const [sc, fmts] = Object.entries(preset)[0]
    const box = byLabel(c, `${sc} `)
    expect(box, `no checkbox rendered for ${sc}`).toBeTruthy()
    expect(box.checked).toBe(true)
    expect(fmts.length).toBeGreaterThan(0)
  })

  it('resolves a JSON map, so a data scope round-trips', async () => {
    const c = await render(JSON.stringify({ '1.4.3': ['docx'] }))
    expect(byLabel(c, '1.4.3 Contrast (Minimum), DOCX').checked).toBe(true)
    expect(byLabel(c, '1.4.3 Contrast (Minimum), PDF').checked).toBe(false)
  })

  it('treats an empty setting as no restriction, not as an empty scope', async () => {
    const c = await render('')
    expect(c.querySelectorAll('input[type=radio]')[0].checked).toBe(true)
    // the grid is not even rendered in that mode
    expect(c.querySelector('table')).toBeNull()
  })

  it('fails open on an unusable stored value, matching the backend', async () => {
    const c = await render('{not json')
    expect(c.querySelectorAll('input[type=radio]')[0].checked).toBe(true)
  })
})


// ── saving ────────────────────────────────────────────────────────────────────────────────────
describe('saving', () => {
  it('sends the selection as a map, formats sorted', async () => {
    const c = await render(JSON.stringify({ '1.4.3': ['pdf'] }))
    await click(byLabel(c, '1.4.3 Contrast (Minimum), DOCX'))
    await click(saveBtn(c))
    expect(settingsMock.put).toHaveBeenCalledWith({ scan_scope: { '1.4.3': ['docx', 'pdf'] } })
  })

  it('sends "" to clear, so the backend stores the simpler form', async () => {
    const c = await render('engagement-14')
    await click(c.querySelectorAll('input[type=radio]')[0])   // no restriction
    await click(saveBtn(c))
    expect(settingsMock.put).toHaveBeenCalledWith({ scan_scope: '' })
  })

  it('reports a SIM write as not written, never as success', async () => {
    const c = await render('')
    settingsMock.put = vi.fn(async () => ({ simulated: true }))
    await click(c.querySelectorAll('input[type=radio]')[1])
    await click(byLabel(c, '1.1.1 Non-text Content, DOCX'))
    await click(saveBtn(c))
    expect(status(c)).toMatch(/^SIM/)
    expect(status(c)).not.toMatch(/✓/)
  })

  it('adopts the SERVER\'s echo rather than its own request', async () => {
    // A save that is accepted but stores something else must not be reported as what was asked
    // for. The panel re-reads the response, so the grid shows what is actually stored.
    const c = await render('')
    settingsMock.put = vi.fn(async () => ({ scan_scope: JSON.stringify({ '2.4.2': ['pptx'] }) }))
    await click(c.querySelectorAll('input[type=radio]')[1])
    await click(byLabel(c, '1.1.1 Non-text Content, DOCX'))
    await click(saveBtn(c))
    expect(byLabel(c, '2.4.2 Page Titled, PPTX').checked).toBe(true)
    expect(byLabel(c, '1.1.1 Non-text Content, DOCX').checked).toBe(false)
  })

  it('surfaces an owner-only rejection as read-only, not as a generic failure', async () => {
    const c = await render('')
    settingsMock.put = vi.fn(async () => { throw new Error('403 Forbidden') })
    await click(c.querySelectorAll('input[type=radio]')[1])
    await click(byLabel(c, '1.1.1 Non-text Content, DOCX'))
    await click(saveBtn(c))
    expect(status(c)).toMatch(/owner-only/i)
  })
})


// ── the grid only offers what the engine can judge ────────────────────────────────────────────
describe('the grid', () => {
  it('renders no checkbox where the engine has no verdict for the pair', async () => {
    const c = await render('engagement-14')
    // 2.1.1 Keyboard applies only to PPTX (static deck); DOCX has no lane, so that cell
    // must not be a checkbox at all — a disabled box would read as "off", implying a choice
    // nobody made.
    const rowKB = SCOPE_UNIVERSE.find((r) => r.sc === '2.1.1')
    expect(rowKB.formats).not.toContain('docx')
    expect(byLabel(c, '2.1.1 Keyboard, DOCX')).toBeFalsy()
    expect(byLabel(c, '2.1.1 Keyboard, PPTX')).toBeTruthy()
    // 1.4.1 Use of Color now has a pptx review lane (colour-only hyperlinks in DrawingML),
    // so both PPTX and DOCX checkboxes must be present.
    const row141 = SCOPE_UNIVERSE.find((r) => r.sc === '1.4.1')
    expect(row141.formats).toContain('pptx')
    expect(byLabel(c, '1.4.1 Use of Color, PPTX')).toBeTruthy()
    expect(byLabel(c, '1.4.1 Use of Color, DOCX')).toBeTruthy()
  })

  it('names every checkbox for a screen reader', async () => {
    const c = await render('engagement-14')
    const boxes = [...c.querySelectorAll('input[type=checkbox]')]
    expect(boxes.length).toBeGreaterThan(20)
    for (const b of boxes) expect(b.getAttribute('aria-label')).toMatch(/^\d+\.\d+\.\d+ .+, (DOCX|XLSX|PPTX|PDF)$/)
  })

  it('uses real row and column headers', async () => {
    const c = await render('engagement-14')
    expect(c.querySelector('caption')).toBeTruthy()
    expect([...c.querySelectorAll('th[scope="col"]')].length).toBeGreaterThan(4)
    expect([...c.querySelectorAll('th[scope="row"]')].length).toBe(OFFERED.length)
  })

  it('offers the tracked criteria only, not the whole universe', async () => {
    // The universe is every pair the engine can reach a verdict on — the right answer to "what
    // COULD be scoped", and the wrong one to "what should this operator choose between". Twelve
    // of the 29 are AAA rules and viewer behaviours Mova iO does not track, and each was a row to
    // read and dismiss on the screen meant to be the first thing an operator does.
    const c = await render('engagement-14')
    const shown = [...c.querySelectorAll('th[scope="row"] b')].map((b) => b.textContent)
    expect(new Set(shown)).toEqual(new Set([...TRACKED_17]))

    // Derived on both sides, so this keeps meaning something as either list changes.
    const untracked = SCOPE_UNIVERSE.map((r) => r.sc).filter((sc) => !TRACKED_17.has(sc))
    expect(untracked.length, 'nothing to filter — the universe is already the tracked list')
      .toBeGreaterThan(0)
    for (const sc of untracked) expect(shown, `${sc} is offered but not tracked`).not.toContain(sc)
  })

  it('drops no tracked criterion — every one of the 17 has a row', async () => {
    // The failure this guards is the quiet direction: a filter that hides a criterion the product
    // says it follows, leaving an operator unable to scope it and nothing on screen to say why.
    const c = await render('engagement-14')
    const shown = [...c.querySelectorAll('th[scope="row"] b')].map((b) => b.textContent)
    const missing = [...TRACKED_17].filter((sc) => !shown.includes(sc))
    expect(missing, `tracked but not offerable: ${missing.join(', ')}`).toHaveLength(0)
  })
})


// ── the parser, directly ──────────────────────────────────────────────────────────────────────
describe('parseStoredScope', () => {
  it.each([['', null], ['   ', null], ['{}', null], ['{bad', null], ['nope', null]])(
    'reads %o as no restriction', (raw, want) => { expect(parseStoredScope(raw)).toBe(want) })

  it('drops criteria with no formats, which would otherwise be a phantom row', () => {
    expect(parseStoredScope(JSON.stringify({ '1.4.3': [] }))).toBe(null)
  })
})
