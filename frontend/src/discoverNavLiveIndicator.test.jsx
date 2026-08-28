/**
 * The live-scan nav indicator + the Discover tab staying reachable while its own scan is busy.
 *
 * Every earlier fix for "does the user know their scan is still running" (the queued card, the
 * live freshness badge, the stale-banner suppression) lived entirely inside the Discover tab
 * body — a user who navigated away to Overview or Assess while a scan was queued/running saw
 * nothing anywhere telling them so. Worse: `App.jsx`'s nav-lock logic (`busy && step > 0 &&
 * view !== k`) locked EVERY numbered tab including Discover itself once you left it, so there
 * was no way back in to check until the scan finished — found live 2026-08-28 while adding the
 * badge this file tests, since a badge pointing at an unopenable tab would have been pointless.
 *
 * DOM-level, not browser-level: this repo's preview server runs vite rooted at the SHARED
 * checkout whatever worktree you are in (CLAUDE.md), so a browser check would exercise code
 * without this.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'
import { gotoStep } from './wizardNav.testkit.js'

globalThis.__BUILD_TIME__ = '2026-08-01T00:00:00.000Z'
globalThis.__BUILD_VERSION__ = '2026.8.1'

// Never resolves — doScan's `setBusy(true)` runs before this is awaited, so busy stays true for
// the rest of the test, unlike appScanGate.test.jsx's throwing stub (which resets busy via the
// `finally` block on the very next microtask, too fast to observe here).
const startScanQueued = vi.fn(() => new Promise(() => {}))

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
  startScanQueued,
}))

const { default: App } = await import('./App.jsx')

afterEach(unmountAll)
beforeEach(() => { startScanQueued.mockClear() })

const flush = async () => { for (let i = 0; i < 4; i++) await act(async () => { await Promise.resolve() }) }
const click = async (el) => { await act(async () => { el.click() }); await flush() }
const dialog = (c) => c.querySelector('[role="dialog"]')
const byText = (c, sel, re) => [...c.querySelectorAll(sel)].find((e) => re.test(e.textContent))
const tab = (c, label) => byText(c, '[role="tab"]', new RegExp(label))

async function startABusyScan() {
  const { root, container: c } = createTestRoot()
  await act(async () => { root.render(createElement(App)) })
  await flush()
  await click(byText(c, 'button', /Sign in with SSO/))
  await click(tab(c, 'Discover'))
  await click(byText(c, 'button', /Re-scan all sources/))
  await gotoStep(dialog(c), act, 3)
  await click(dialog(c).querySelector('button[data-wizard-forward]'))
  expect(startScanQueued, 'scan never dispatched — busy will never become true').toHaveBeenCalled()
  return c
}

describe('the live-scan nav badge and the fix that makes it reachable', () => {
  it('does not show the badge while already on Discover — the tab body says it more richly there', async () => {
    const c = await startABusyScan()
    expect(tab(c, 'Discover').querySelector('.pulsedot')).toBeFalsy()
  })

  it('shows a live badge on the Discover tab once the user navigates away, and Discover stays clickable', async () => {
    const c = await startABusyScan()
    await click(tab(c, 'Overview'))     // step 0 — always reachable, the escape hatch used live
    const discoverTab = tab(c, 'Discover')
    expect(discoverTab.querySelector('.pulsedot'), 'no live badge on Discover from Overview').toBeTruthy()
    expect(discoverTab.disabled, 'Discover locked itself out of its own running scan').toBe(false)
    // Not just visually unlocked — genuinely re-enterable.
    await click(discoverTab)
    expect(discoverTab.getAttribute('aria-selected')).toBe('true')
  })

  it('still locks the OTHER numbered steps while the scan is busy — only Discover is exempt', async () => {
    const c = await startABusyScan()
    await click(tab(c, 'Overview'))
    const assessTab = tab(c, 'Assess')
    expect(assessTab.disabled, 'Assess should still be locked mid-scan').toBe(true)
    expect(assessTab.title).toMatch(/scan or assessment is running/i)
  })

  it('does not show the badge when no scan is busy', async () => {
    const { root, container: c } = createTestRoot()
    await act(async () => { root.render(createElement(App)) })
    await flush()
    await click(byText(c, 'button', /Sign in with SSO/))
    expect(tab(c, 'Discover').querySelector('.pulsedot')).toBeFalsy()
    expect(startScanQueued).not.toHaveBeenCalled()
  })
})
