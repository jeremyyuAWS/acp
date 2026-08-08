/**
 * The first screen, RENDERED — what an operator can actually do to the two filters.
 *
 * scanSetup.test.js already covers this component, but it does so by readFileSync-ing the source
 * and asserting on the text. That proves the code SAYS the right things; it cannot prove a
 * checkbox is reachable, that a format toggle narrows anything, or that an empty selection is
 * refused rather than saved. This repo has been bitten by prose-matching assertions three times
 * (see CLAUDE.md), and the component those assertions guard is the one the product opens on.
 *
 * The load-bearing case is `saving is refused when the two axes intersect to nothing`. `scope` is
 * derived as criteria × formats, so untick every file type and a full set of criteria still
 * collapses to {} — and on the backend `{}` means NO RESTRICTION, not "nothing". Saved literally
 * that is "assess everything" wearing the appearance of "assess nothing", which is both silent
 * and the exact inverse of the intent.
 *
 * DOM-level, not browser-level: this repo's preview server runs vite rooted at the SHARED
 * checkout whatever worktree you are in, so a browser check of a worktree change exercises code
 * that does not contain it (CLAUDE.md).
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

afterEach(unmountAll)

const settingsMock = { get: null, put: null }
vi.mock('./api.js', () => ({
  getSettings: (...a) => settingsMock.get(...a),
  updateSettings: (...a) => settingsMock.put(...a),
}))

const { default: ScanSetup } = await import('./ScanSetup.jsx')
const { SCOPE_PRESETS, SCOPE_UNIVERSE, SCOPE_FORMATS } = await import('./scopePresets.js')
const { TRACKED_17 } = await import('./ruleDetails.js')

// Derived exactly as the component derives it, so these tests assert behaviour against generated
// data instead of re-typing the 17 — a hand-written copy would be the second source of truth the
// codegen exists to prevent.
const OFFERED = SCOPE_UNIVERSE.filter((r) => TRACKED_17.has(r.sc))
const CORE = 'acp-core-17'

async function render(props = {}) {
  settingsMock.get = vi.fn(async () => ({ scan_scope: '' }))
  settingsMock.put = vi.fn(async () => ({}))
  const onScan = vi.fn()
  const { root, container } = createTestRoot()
  await act(async () => {
    root.render(createElement(ScanSetup, { onScan, busy: false, ...props }))
  })
  return { c: container, onScan }
}

const click = async (el) => { await act(async () => { el.click() }) }
const btn = (c, re) => [...c.querySelectorAll('button')].find((b) => re.test(b.textContent))
// Chips read "✓ Word · DOCX" — the tick is part of the label and moves with the state, so match
// on the format token rather than the whole string.
const chip = (c, fmt) => [...c.querySelectorAll('button')]
  .find((b) => new RegExp(`\\b${fmt}\\b`, 'i').test(b.textContent))
const box = (c, sc) => [...c.querySelectorAll('input[type=checkbox]')]
  .find((e) => (e.getAttribute('aria-label') || '').startsWith(sc + ' '))
// NOT [role="status"]: the always-present scope summary carries that role too, and reading the
// first match silently returns the summary instead of the save message — which is how an
// assertion about an error ends up passing against unrelated text.
const status = (c) => c.querySelector('.setupmsg')?.textContent || ''
const FORMAT_CHIPS = ['DOCX', 'XLSX', 'PPTX', 'PDF']
const savedScope = () => JSON.parse(settingsMock.put.mock.calls.at(-1)[0].scan_scope)


describe('the first screen shows both filters', () => {
  it('renders a chip for every file type the engine supports', async () => {
    const { c } = await render()
    for (const f of SCOPE_FORMATS) {
      expect(chip(c, f), `no chip for ${f}`).toBeTruthy()
    }
  })

  it('starts on the Core 17 preset with every format on, so the default is scannable', async () => {
    const { c } = await render()
    await click(btn(c, /Save scope only/))
    const scope = savedScope()
    expect(Object.keys(scope).sort()).toEqual(Object.keys(SCOPE_PRESETS[CORE]).sort())
  })
})


describe('the file-type filter actually narrows what is saved', () => {
  it('drops a deselected format from every criterion', async () => {
    const { c } = await render()
    await click(chip(c, 'PDF'))
    await click(btn(c, /Save scope only/))
    const scope = savedScope()
    for (const [sc, fmts] of Object.entries(scope)) {
      expect(fmts, `${sc} kept pdf after it was deselected`).not.toContain('pdf')
    }
    // and the criteria that ONLY exist on pdf drop out entirely rather than saving an empty list
    for (const [sc, fmts] of Object.entries(scope)) {
      expect(fmts.length, `${sc} saved with no formats`).toBeGreaterThan(0)
    }
  })

  it('removes a criterion whose only format was deselected', async () => {
    // 2.1.1 is pptx-only in the Core 17 — an asymmetry the preset records deliberately, so
    // deselecting PowerPoint must take the criterion with it rather than leave it empty.
    const pptxOnly = Object.entries(SCOPE_PRESETS[CORE])
      .find(([, f]) => [...f].length === 1 && [...f][0] === 'pptx')
    expect(pptxOnly, 'expected a pptx-only criterion in the preset').toBeTruthy()
    const { c } = await render()
    await click(chip(c, 'PPTX'))
    await click(btn(c, /Save scope only/))
    expect(savedScope()).not.toHaveProperty(pptxOnly[0])
  })
})


describe('the criterion filter actually narrows what is saved', () => {
  it('drops a criterion when its box is unticked', async () => {
    const { c } = await render()
    await click(btn(c, /^Custom$/))
    const target = OFFERED[0].sc
    const b = box(c, target)
    expect(b, `no checkbox for ${target}`).toBeTruthy()
    await click(b)
    await click(btn(c, /Save scope only/))
    expect(savedScope()).not.toHaveProperty(target)
  })
})


describe('an empty intersection is refused, not saved', () => {
  it('refuses when every file type is deselected, and sends nothing', async () => {
    const { c } = await render()
    for (const f of FORMAT_CHIPS) await click(chip(c, f))
    await click(btn(c, /Save scope only/))

    expect(settingsMock.put).not.toHaveBeenCalled()
    expect(status(c)).toMatch(/empty scope would assess everything/i)
  })

  it('disables the scan buttons rather than scanning an empty scope', async () => {
    const { c } = await render()
    for (const f of FORMAT_CHIPS) await click(chip(c, f))
    const scan = btn(c, /Save & /)
    expect(scan).toBeTruthy()
    expect(scan.disabled).toBe(true)
  })
})


describe('a scan never runs on a scope that did not persist', () => {
  it('does not start the scan when the save fails', async () => {
    // scanAndSave awaits save() and then calls onScan unconditionally, and save() swallows its
    // own error into a status message. So a failed write — an expired session, a 500 — would
    // otherwise scan against whatever scope was stored BEFORE, while the screen shows the
    // selection the operator just made. The scope is the whole point of this screen; running
    // without it is worse than not running.
    const { c, onScan } = await render()
    settingsMock.put = vi.fn(async () => { throw new Error('session expired') })
    await click(btn(c, /Save & /))

    expect(status(c)).toMatch(/session expired/i)
    expect(onScan, 'scanned despite the scope failing to save').not.toHaveBeenCalled()
  })
})
