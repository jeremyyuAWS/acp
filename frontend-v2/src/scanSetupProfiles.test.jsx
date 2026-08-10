/**
 * Step 2, RENDERED — the profile-first checks configurator and its shortcuts into the one
 * `criteria` Set.
 *
 * scanSetupDom.test.jsx already holds the load-bearing invariant (an empty criteria × formats
 * intersection is refused, never saved). This file covers what was added on top: three profiles,
 * the bulk/tri-state controls, the file-type-narrowed rows, the lane filter, and the honest
 * footer. Every expectation is derived from the SAME generated data the component reads
 * (SCOPE_UNIVERSE, TRACKED_17, CAPABILITY_FALLBACK) — a hand-typed copy of "which docx checks are
 * automated" would be the second source of truth the codegen exists to prevent, and it would rot
 * the first time a lane moved (docx 4.1.2 moved auto only days ago).
 *
 * DOM-level, not browser-level: the preview server runs vite rooted at the SHARED checkout
 * whatever worktree you are in, so a browser check of a worktree change exercises code that does
 * not contain it (CLAUDE.md). These assertions run against the component actually under edit.
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
const { SCOPE_UNIVERSE } = await import('./scopePresets.js')
const { TRACKED_17 } = await import('./ruleDetails.js')
const { CAPABILITY_FALLBACK, modeFor } = await import('./capability.js')

const OFFERED = SCOPE_UNIVERSE.filter((r) => TRACKED_17.has(r.sc))

// The component's own definitions, re-derived here so the tests track the data, not a snapshot.
const availableOn = (fmts) => OFFERED.filter((r) => r.formats.some((f) => fmts.has(f)))
const autoOnlyOn = (fmts) => availableOn(fmts)
  .filter((r) => r.formats.filter((f) => fmts.has(f))
    .every((f) => modeFor(CAPABILITY_FALLBACK, f, r.sc) === 'auto'))
  .map((r) => r.sc).sort()
const docxLane = (sc) => modeFor(CAPABILITY_FALLBACK, 'docx', sc)

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
const chip = (c, fmt) => [...c.querySelectorAll('button')]
  .find((b) => new RegExp(`\\b${fmt}\\b`, 'i').test(b.textContent))
const box = (c, sc) => [...c.querySelectorAll('input[type=checkbox]')]
  .find((e) => (e.getAttribute('aria-label') || '').startsWith(sc + ' '))
const catbox = (c, name) => [...c.querySelectorAll('input[type=checkbox]')]
  .find((e) => e.getAttribute('aria-label') === `Select all ${name}`)
const rowFmt = (c, sc) => box(c, sc)?.closest('.setuprow')?.querySelector('.setuprow-f')?.textContent
const savedScope = () => JSON.parse(settingsMock.put.mock.calls.at(-1)[0].scan_scope)
const setFormat = async (c, fmt, on) => {
  const el = chip(c, fmt)
  if ((el.getAttribute('aria-pressed') === 'true') !== on) await click(el)
}
const enterCustom = async (c) => { await click(btn(c, /^Custom$/)) }


describe('profiles reach a correct scope in one click', () => {
  it('defaults to Recommended', async () => {
    const { c } = await render()
    expect(btn(c, /Recommended/).getAttribute('aria-checked')).toBe('true')
  })

  it('Automated only selects exactly the deterministic-first docx checks', async () => {
    const { c } = await render()                 // default formats = docx
    await click(btn(c, /Automated only/))
    await click(btn(c, /Save scope only/))
    expect(Object.keys(savedScope()).sort()).toEqual(autoOnlyOn(new Set(['docx'])))
    // and every one of them really is automated on docx — the label is not decorative
    for (const sc of Object.keys(savedScope())) expect(docxLane(sc)).toBe('auto')
  })

  it('Automated only RE-DERIVES when the file types change, so it keeps meaning its name', async () => {
    const { c } = await render()
    await click(btn(c, /Automated only/))
    await setFormat(c, 'PDF', true)              // now docx + pdf
    await click(btn(c, /Save scope only/))
    // strict: a criterion automated on docx but not on pdf must drop out, because the scan it
    // names would otherwise route something to a person
    expect(Object.keys(savedScope()).sort()).toEqual(autoOnlyOn(new Set(['docx', 'pdf'])))
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
    const avail = availableOn(new Set(['docx'])).map((r) => r.sc).sort()
    expect(Object.keys(savedScope()).sort()).toEqual(avail)
  })

  it('a principle checkbox selects exactly that principle', async () => {
    const { c } = await render()
    await enterCustom(c)
    await click(btn(c, /Clear all/))
    await click(catbox(c, 'Perceivable'))
    await click(btn(c, /Save scope only/))
    const saved = Object.keys(savedScope()).sort()
    const perceivable = availableOn(new Set(['docx'])).filter((r) => r.sc.startsWith('1.')).map((r) => r.sc).sort()
    expect(saved).toEqual(perceivable)
    expect(saved.every((sc) => sc.startsWith('1.'))).toBe(true)
  })
})


describe('the row talks about the ticked file types, not all four', () => {
  it('a Word-only scan shows DOCX on a criterion that also exists elsewhere', async () => {
    const { c } = await render()
    await enterCustom(c)
    // 1.1.1 exists on all four formats; with only Word ticked the row must say just DOCX
    expect(rowFmt(c, '1.1.1')).toBe('DOCX')
    await setFormat(c, 'PDF', true)
    expect(rowFmt(c, '1.1.1')).toBe('DOCX · PDF')
  })

  it('a criterion with no ticked-format lane is not offered at all', async () => {
    const { c } = await render()
    await enterCustom(c)
    // 2.1.1 is pptx-only; on a Word scan there is nothing to tick, so no checkbox
    expect(box(c, '2.1.1')).toBeFalsy()
    await setFormat(c, 'PPTX', true)
    expect(box(c, '2.1.1')).toBeTruthy()
  })
})


describe('the lane filter answers "which checks need a person?"', () => {
  it('shows only the matching lane and hides the rest', async () => {
    const human = OFFERED.find((r) => r.formats.includes('docx') && docxLane(r.sc) === 'human')
    const auto = OFFERED.find((r) => r.formats.includes('docx') && docxLane(r.sc) === 'auto')
    expect(human && auto, 'expected both a human-review and an automated docx criterion').toBeTruthy()

    const { c } = await render()
    await enterCustom(c)
    await click(btn(c, /Human review \d/))
    expect(box(c, human.sc), 'the human-review row should stay').toBeTruthy()
    expect(box(c, auto.sc), 'the automated row should be filtered out of view').toBeFalsy()
  })
})


describe('the footer says what the scan will actually do', () => {
  it('reports the running check count and a lane breakdown', async () => {
    const { c } = await render()
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
