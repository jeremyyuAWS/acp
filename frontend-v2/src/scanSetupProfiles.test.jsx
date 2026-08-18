/**
 * The checks step, RENDERED — the profile-first criterion configurator and its shortcuts into the
 * one `criteria` Set.
 *
 * scanSetupDom.test.jsx holds the load-bearing invariant (an empty scope is refused, never saved).
 * This file covers what sits on top: the three profiles, the bulk/tri-state controls, the lane
 * filter, and the honest footer. Every expectation is derived from the SAME generated data the
 * component reads (SCOPE_UNIVERSE, TRACKED_17, CAPABILITY_FALLBACK) — a hand-typed copy would be
 * the second source of truth the codegen exists to prevent.
 *
 * THE FORMAT AXIS MOVED TO ASSESS (Discover/Assess PRD §4.1). This screen no longer offers file
 * types, so the default is "no format restriction" — every supported format. A stored scope is
 * read back on mount and narrows the format set; the lane-filter case seeds a docx-only stored
 * scope so it can assert docx capability lanes deterministically.
 *
 * DOM-level, not browser-level: the preview server runs vite rooted at the SHARED checkout whatever
 * worktree you are in (CLAUDE.md). These assertions run against the component actually under edit.
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
const { SCOPE_UNIVERSE, SCOPE_FORMATS } = await import('./scopePresets.js')
const { TRACKED_17 } = await import('./ruleDetails.js')
const { CAPABILITY_FALLBACK, modeFor } = await import('./capability.js')

const OFFERED = SCOPE_UNIVERSE.filter((r) => TRACKED_17.has(r.sc))
const ALL = new Set(SCOPE_FORMATS)

// The component's own definitions, re-derived here so the tests track the data, not a snapshot.
const availableOn = (fmts) => OFFERED.filter((r) => r.formats.some((f) => fmts.has(f)))
const autoOnlyOn = (fmts) => availableOn(fmts)
  .filter((r) => r.formats.filter((f) => fmts.has(f))
    .every((f) => modeFor(CAPABILITY_FALLBACK, f, r.sc) === 'auto'))
  .map((r) => r.sc).sort()
const docxLane = (sc) => modeFor(CAPABILITY_FALLBACK, 'docx', sc)
// A docx-only stored scope over every docx-lane criterion — seeds the component's format set to
// {docx} on mount, so lane assertions can be made against a single deterministic format.
const DOCX_SCOPE = JSON.stringify(Object.fromEntries(
  OFFERED.filter((r) => r.formats.includes('docx')).map((r) => [r.sc, ['docx']]),
))

async function render(props = {}, scanScope = '') {
  settingsMock.get = vi.fn(async () => ({ scan_scope: scanScope }))
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
const box = (c, sc) => [...c.querySelectorAll('input[type=checkbox]')]
  .find((e) => (e.getAttribute('aria-label') || '').startsWith(sc + ' '))
const catbox = (c, name) => [...c.querySelectorAll('input[type=checkbox]')]
  .find((e) => e.getAttribute('aria-label') === `Select all ${name}`)
const savedScope = () => JSON.parse(settingsMock.put.mock.calls.at(-1)[0].scan_scope)
const enterCustom = async (c) => { await click(btn(c, /^Custom$/)) }


describe('profiles reach a correct scope in one click', () => {
  it('defaults to Recommended', async () => {
    const { c } = await render()
    expect(btn(c, /Recommended/).getAttribute('aria-checked')).toBe('true')
  })

  it('Automated only selects exactly the deterministic-first checks over all formats', async () => {
    const { c } = await render()                 // default formats = every supported format
    await click(btn(c, /Automated only/))
    await click(btn(c, /Save scope only/))
    expect(Object.keys(savedScope()).sort()).toEqual(autoOnlyOn(ALL))
  })

  it('any per-criterion edit drops the profile to Custom', async () => {
    const { c } = await render()
    await enterCustom(c)
    expect(btn(c, /^Custom$/).getAttribute('aria-checked')).toBe('true')
    expect(btn(c, /Recommended/).getAttribute('aria-checked')).toBe('false')
  })
})


describe('the bulk controls all write the one selection', () => {
  it('Clear all empties the scope; Select all restores every available check', async () => {
    const { c } = await render()
    await enterCustom(c)
    await click(btn(c, /Clear all/))
    expect(btn(c, /Save & /).disabled).toBe(true)          // nothing to scan

    await click(btn(c, /Select all/))
    await click(btn(c, /Save scope only/))
    const avail = availableOn(ALL).map((r) => r.sc).sort()
    expect(Object.keys(savedScope()).sort()).toEqual(avail)
  })

  it('a principle checkbox selects exactly that principle', async () => {
    const { c } = await render()
    await enterCustom(c)
    await click(btn(c, /Clear all/))
    await click(catbox(c, 'Perceivable'))
    await click(btn(c, /Save scope only/))
    const saved = Object.keys(savedScope()).sort()
    const perceivable = availableOn(ALL).filter((r) => r.sc.startsWith('1.')).map((r) => r.sc).sort()
    expect(saved).toEqual(perceivable)
    expect(saved.every((sc) => sc.startsWith('1.'))).toBe(true)
  })
})


describe('the lane filter answers "which checks need a person?"', () => {
  it('shows only the matching lane and hides the rest', async () => {
    const human = OFFERED.find((r) => r.formats.includes('docx') && docxLane(r.sc) === 'human')
    const auto = OFFERED.find((r) => r.formats.includes('docx') && docxLane(r.sc) === 'auto')
    expect(human && auto, 'expected both a human-review and an automated docx criterion').toBeTruthy()

    // Seed a docx-only stored scope so the lanes are computed over docx alone.
    const { c } = await render({}, DOCX_SCOPE)
    await enterCustom(c)
    await click(btn(c, /Human review \d/))
    expect(box(c, human.sc), 'the human-review row should stay').toBeTruthy()
    expect(box(c, auto.sc), 'the automated row should be filtered out of view').toBeFalsy()
  })
})


describe('the footer says what the scan will actually do', () => {
  it('reports the running check count and a lane breakdown', async () => {
    // docx-seeded so the lanes resolve to concrete modes (docx carries deterministic 'auto'
    // lanes), rather than the "varies by format" the all-format default mostly produces.
    const { c } = await render({}, DOCX_SCOPE)
    const run = c.querySelector('.setuprun').textContent
    expect(run).toMatch(/\d+ checks will run/)
    expect(run.toLowerCase()).toContain('automated')
    // the persistent summary card is present and decision-oriented
    const summary = [...c.querySelectorAll('.setupsummary')].map((e) => e.textContent).join(' ')
    expect(summary).toContain('Scan configuration')
    expect(summary).toContain('Files')
    expect(summary).toContain('Execution')
  })
})
