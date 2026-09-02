/**
 * The universal scan gate, at the App level.
 *
 * `doScan` is the single dispatch funnel, but every entry point now calls `requestScan` (wired as
 * their `onScan` prop), which OPENS the app-level ScanReviewModal instead of scanning. The only
 * path that actually starts a scan is the modal's "Start scan" confirm. This mounts the REAL App,
 * signs in via the demo persona, and drives Discover's "Re-scan all sources" to prove:
 *   - clicking a scan entry opens the gate and does NOT start a scan;
 *   - confirming in the gate is what starts the scan (the scan API is called then, not before);
 *   - cancelling the gate starts nothing.
 *
 * Durable (queuedScan) is the default (2026-08-21) — see App.jsx's own comment on that useState —
 * so a confirm from this gate takes the QUEUED path. startScanQueued is stubbed to throw, so
 * `doScan` bails immediately after calling it — we assert only that it WAS or WAS NOT called,
 * never running the real poll loop.
 *
 * DOM-level, not browser-level: this repo's preview server runs vite rooted at the SHARED checkout
 * whatever worktree you are in (CLAUDE.md), so a browser check would exercise code without this.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'
import { gotoStep } from './wizardNav.testkit.js'

// vite replaces these `define` literals at build time; vitest does not, and App.jsx reads them
// unguarded in its header, so define them as globals before it renders.
globalThis.__BUILD_TIME__ = '2026-08-01T00:00:00.000Z'
globalThis.__BUILD_VERSION__ = '2026.8.1'

const startScanQueued = vi.fn(async () => { throw new Error('test stub — do not run the poll loop') })
const startScan = vi.fn(async () => { throw new Error('test stub — do not run the poll loop') })
const getScanLocations = vi.fn(async () => ({
  locations: { drive: [{ id: 'old-filter', name: 'Previous filtered folder' }] },
}))

// Spread the real api and override only what App's startup + a scan touch, so a new export never
// silently breaks this mount. getConfig → demo mode (persona picker); the scan API throws so the
// dispatch is observable without the durable poll loop.
vi.mock('./api.js', async (importActual) => ({
  ...(await importActual()),
  getConfig: vi.fn(async () => ({ auth: 'demo' })),
  getRubric: vi.fn(async () => ({ target: 'WCAG 2.1 AA', hash: 'abcdef0123' })),
  getSources: vi.fn(async () => []),
  listScans: vi.fn(async () => []),
  getActiveScan: vi.fn(async () => null),
  getSettings: vi.fn(async () => ({ scan_scope: '' })),
  updateSettings: vi.fn(async () => ({ scan_scope: '' })),
  getScan: vi.fn(async () => ({ run: { id: 's1', status: 'done' }, files: [] })),
  getDecisions: vi.fn(async () => ({})),
  getScanLocations,
  startScanQueued,
  // The Durable toggle is no longer on the modal, so a default confirm takes the NON-queued path
  // and THIS is the call that has to be observable. Throws for the same reason startScanQueued
  // does: it stops doScan before the getJob poll loop.
  startScan,
}))

const { default: App } = await import('./App.jsx')

afterEach(unmountAll)
beforeEach(() => { startScanQueued.mockClear(); startScan.mockClear(); getScanLocations.mockClear() })

const flush = async () => { for (let i = 0; i < 4; i++) await act(async () => { await Promise.resolve() }) }
const click = async (el) => { await act(async () => { el.click() }); await flush() }
const dialog = (c) => c.querySelector('[role="dialog"]')
const byText = (c, sel, re) => [...c.querySelectorAll(sel)].find((e) => re.test(e.textContent))
const durableSwitch = (c) => [...dialog(c).querySelectorAll('[role="switch"]')]
  .find((s) => (s.getAttribute('aria-label') || '').includes('Durable scan'))

async function mountSignedInOnDiscover() {
  const { root, container } = createTestRoot()
  await act(async () => { root.render(createElement(App)) })
  await flush()
  // Demo sign-in — the SSO button signs in as the compliance persona (allows Discover).
  await click(byText(container, 'button', /Sign in with SSO/))
  // Land on Discover (its "Re-scan all sources" is a scan entry point).
  const discoverTab = byText(container, '[role="tab"]', /Discover/)
  expect(discoverTab, 'no Discover tab after sign-in').toBeTruthy()
  await click(discoverTab)
  return container
}

describe('the universal scan gate (App)', () => {
  it('implements one-stop workflow tabs with a resolvable active panel', async () => {
    const c = await mountSignedInOnDiscover()
    const tabs = [...c.querySelectorAll('nav[aria-label="Compliance workflow"] [role="tab"]')]
    const active = tabs.find((tab) => tab.getAttribute('aria-selected') === 'true')
    expect(active.textContent).toMatch(/Discover/)
    expect(tabs.filter((tab) => tab.tabIndex === 0)).toEqual([active])
    expect(tabs.every((tab) => tab.getAttribute('aria-controls') === 'workflow-panel')).toBe(true)
    const panel = c.querySelector('#workflow-panel[role="tabpanel"]')
    expect(panel).toBeTruthy()
    expect(panel.getAttribute('aria-labelledby')).toBe(active.id)

    await act(async () => active.dispatchEvent(new KeyboardEvent('keydown', {
      key: 'ArrowRight', bubbles: true,
    })))
    await flush()
    const next = tabs.find((tab) => tab.getAttribute('aria-selected') === 'true')
    expect(next.textContent).toMatch(/Assess/)
    expect(document.activeElement).toBe(next)
  })

  it('opens the review modal from a scan entry point and does NOT scan yet', async () => {
    const c = await mountSignedInOnDiscover()
    const rescan = byText(c, 'button', /Re-scan all sources/)
    expect(rescan, 'no "Re-scan all sources" button on Discover').toBeTruthy()
    expect(dialog(c)).toBeNull()
    await click(rescan)
    // The gate is open…
    const d = dialog(c)
    expect(d).toBeTruthy()
    expect(d.getAttribute('aria-label')).toBe('New discovery')
    // The "Formats & WCAG criteria" heading is gone (it named step 2's subject while the
    // user was on step 1). This assertion was a proxy for "the review modal opened" — so
    // assert the estimate line, which is the modal's own content and is step-independent.
    expect(d.textContent).toMatch(/Document count is determined when the scan starts|documents in/)
    // …and nothing has been dispatched.
    expect(startScanQueued).not.toHaveBeenCalled()
  })

  it('does not put the engine switches in front of the user', async () => {
    // The four behaviour toggles were removed from this surface: they are platform behaviour, not
    // per-run decisions. Their DEFAULTS are still pinned — against App.jsx's source, in
    // scanBehaviourDefaults.test.js — so this assertion moved rather than disappeared, and what
    // it guards here is that they do not come back to the gate.
    const c = await mountSignedInOnDiscover()
    await click(byText(c, 'button', /Re-scan all sources/))
    expect(durableSwitch(c), 'the Durable toggle is back on the scan gate').toBeFalsy()
    expect([...dialog(c).querySelectorAll('[role="switch"]')].length).toBe(0)
  })

  it('starts the scan only when the gate is confirmed', async () => {
    const c = await mountSignedInOnDiscover()
    await click(byText(c, 'button', /Re-scan all sources/))
    expect(startScanQueued).not.toHaveBeenCalled()
    // Durable is ON by default and no longer togglable here, so a confirm takes the queued path
    // (App.jsx's `if (queuedScan) { startScanQueued(...) }`). Three steps, so walk to the run
    // control the way a user does.
    //
    // Both eras of this comment were sitting here at once — "Three steps now, so walk to Start"
    // immediately above "One screen now (PRD DISC-01) — no Continue to walk". Neither was deleted
    // when the other was added, so the file asserted one thing and explained two. The guarantee
    // itself never changed: nothing scans until the gate is confirmed.
    await gotoStep(dialog(c), act, 3)
    const start = dialog(c).querySelector('button[data-wizard-forward]')
    expect(start).toBeTruthy()
    expect(start.textContent).toMatch(/Run discovery/)
    await click(start)
    // Confirm dispatched the scan (source 'all' for "Re-scan all sources") and closed the gate.
    expect(startScanQueued).toHaveBeenCalled()
    expect(startScanQueued.mock.calls[0][0]).toBe('all')
    expect(startScanQueued.mock.calls[0][6]).toEqual([])
    expect(startScanQueued.mock.calls[0][7]).toEqual([])
    expect(startScan).not.toHaveBeenCalled()
    expect(dialog(c)).toBeNull()
  })

  it('cancelling the gate starts nothing', async () => {
    const c = await mountSignedInOnDiscover()
    await click(byText(c, 'button', /Re-scan all sources/))
    const cancel = [...dialog(c).querySelectorAll('button')].find((b) => b.textContent.trim() === 'Cancel')
    await click(cancel)
    expect(dialog(c)).toBeNull()
    expect(startScanQueued).not.toHaveBeenCalled()
    expect(startScan).not.toHaveBeenCalled()
  })
})

describe('"Choose folder to scan…" opens the SAME gate, not a second folder picker', () => {
  // Found live 2026-08-28: this button used to open a standalone FolderPicker modal, and on a
  // selection immediately opened THIS wizard again at its default "Entire connected source" step
  // — re-asking the folder question a moment after it was answered, which read as a regression
  // rather than a review step. It now opens the same gate, pre-set to "Specific folders".
  //
  // "Choose folder to scan…" is gated on hasDriveToken (App.jsx), which the demo persona used by
  // mountSignedInOnDiscover() does not set — matches App.jsx's own `sessionStorage.getItem('gd_token')`
  // initializer, so the button renders exactly as it would after a real Drive connection.
  afterEach(() => sessionStorage.removeItem('gd_token'))

  it('lands on "Specific folders" already selected, not "Entire connected source"', async () => {
    sessionStorage.setItem('gd_token', 'test-token')
    const c = await mountSignedInOnDiscover()
    expect(dialog(c)).toBeNull()
    await click(byText(c, 'button', /Choose folder to scan…/))
    const d = dialog(c)
    expect(d, 'no gate opened').toBeTruthy()
    expect(d.getAttribute('aria-label')).toBe('New discovery')
    const radios = [...d.querySelectorAll('[role="radio"]')]
    const specific = radios.find((r) => /Specific folders/.test(r.textContent))
    const entire = radios.find((r) => /Entire connected source/.test(r.textContent))
    expect(specific, 'no "Specific folders" option in the gate').toBeTruthy()
    expect(specific.getAttribute('aria-checked')).toBe('true')
    expect(entire.getAttribute('aria-checked')).toBe('false')
  })

  it('"Re-scan all sources" still lands on "Entire connected source" by default', async () => {
    // Also needs a connected source with a folder hierarchy — without one, the wizard shows its
    // flat "no folder hierarchy to narrow" case instead of the two-option radiogroup at all.
    sessionStorage.setItem('gd_token', 'test-token')
    const c = await mountSignedInOnDiscover()
    await click(byText(c, 'button', /Re-scan all sources/))
    const d = dialog(c)
    const radios = [...d.querySelectorAll('[role="radio"]')]
    const entire = radios.find((r) => /Entire connected source/.test(r.textContent))
    expect(entire.getAttribute('aria-checked')).toBe('true')
  })
})
