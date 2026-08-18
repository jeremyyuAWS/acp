/**
 * The pre-scan screen, RENDERED — what an operator can actually do to the criterion scope.
 *
 * scanSetup.test.js covers this component by readFileSync-ing the source and asserting on text.
 * That proves the code SAYS the right things; it cannot prove a checkbox is reachable, that
 * clearing the criteria collapses the scope, or that an empty selection is refused rather than
 * saved. This repo has been bitten by prose-matching assertions three times (CLAUDE.md).
 *
 * THE FORMAT AXIS IS GONE FROM HERE (Discover/Assess PRD §4.1). Document type is chosen in Assess
 * (AssessScope.jsx) now, so this screen no longer renders a file-type picker; it selects the WCAG
 * criteria and derives their scope over the stored format set (default: every supported format).
 * The load-bearing case is unchanged in spirit — an empty scope is refused, because on the backend
 * `{}` means NO RESTRICTION, so "assess nothing" saved literally is "assess everything" in disguise.
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
const { SCOPE_UNIVERSE, SCOPE_FORMATS } = await import('./scopePresets.js')
const { TRACKED_17 } = await import('./ruleDetails.js')

// Derived exactly as the component derives it, so these tests assert behaviour against generated
// data instead of re-typing the 17 — a hand-written copy would be the second source of truth the
// codegen exists to prevent.
const OFFERED = SCOPE_UNIVERSE.filter((r) => TRACKED_17.has(r.sc))

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
// NOT [role="status"]: the always-present scope summary carries that role too, and reading the
// first match silently returns the summary instead of the save message.
const status = (c) => c.querySelector('.setupmsg')?.textContent || ''
const savedScope = () => JSON.parse(settingsMock.put.mock.calls.at(-1)[0].scan_scope)


describe('the first screen selects checks, not file types', () => {
  it('renders no file-type picker', async () => {
    const { c } = await render()
    for (const f of SCOPE_FORMATS) {
      expect(chip(c, f), `a pressable chip for ${f} is still present`).toBeFalsy()
    }
  })

  it('saves every Core-17 criterion over its full format set by default', async () => {
    // Default is "no format restriction": each criterion carries its full generated lane set,
    // because document type is now an Assess decision rather than a narrowing made here.
    const { c } = await render()
    await click(btn(c, /Save scope only/))
    const scope = savedScope()
    for (const row of OFFERED) {
      expect(scope[row.sc], `${row.sc} missing from the default scope`).toBeTruthy()
      expect([...scope[row.sc]].sort()).toEqual([...row.formats].sort())
    }
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


describe('an empty selection is refused, not saved', () => {
  it('refuses when every check is cleared, and sends nothing', async () => {
    const { c } = await render()
    await click(btn(c, /^Custom$/))
    await click(btn(c, /Clear all/))
    await click(btn(c, /Save scope only/))

    expect(settingsMock.put).not.toHaveBeenCalled()
    expect(status(c)).toMatch(/empty scope would assess everything/i)
  })

  it('disables the scan buttons rather than scanning an empty scope', async () => {
    const { c } = await render()
    await click(btn(c, /^Custom$/))
    await click(btn(c, /Clear all/))
    const scan = btn(c, /Save & /)
    expect(scan).toBeTruthy()
    expect(scan.disabled).toBe(true)
  })
})


describe('a scan never runs on a scope that did not persist', () => {
  it('does not start the scan when the save fails', async () => {
    // scanAndSave awaits save() and then calls onScan only if it returned true; save() swallows its
    // own error into a status message. A failed write must not scan against whatever scope was
    // stored BEFORE while the screen shows the selection the operator just made.
    const { c, onScan } = await render()
    settingsMock.put = vi.fn(async () => { throw new Error('session expired') })
    await click(btn(c, /Save & /))

    expect(status(c)).toMatch(/session expired/i)
    expect(onScan, 'scanned despite the scope failing to save').not.toHaveBeenCalled()
  })
})
