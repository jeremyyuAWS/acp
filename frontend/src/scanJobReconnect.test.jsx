/**
 * Reconnecting to an in-flight DEFAULT-path scan job after a page reload.
 *
 * The default (session-scoped, non-durable) scan path has no scan_runs row until well into its
 * run — _scan_discover creates it only after the full source listing returns, so getActiveScan()
 * (the existing reconnect mechanism for the durable path) cannot see a scan in that window at
 * all. A reload during a long crawl showed nothing running: no progress, no error, nothing — the
 * same invisibility #607 fixed for a job whose replica died, still present for the ordinary case
 * of a plain reload.
 *
 * sessionStorage['active_job_id'] is what survives the reload: set the moment a job starts,
 * cleared the moment it resolves (success OR failure) so a finished job is never reconnected to
 * again. These tests mount the real App and drive it through sessionStorage + the scan API mocks,
 * matching appScanGate.test.jsx's harness.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'
import { gotoStep } from './wizardNav.testkit.js'

globalThis.__BUILD_TIME__ = '2026-08-01T00:00:00.000Z'
globalThis.__BUILD_VERSION__ = '2026.8.1'

const startScan = vi.fn()
const getJob = vi.fn()
const getScan = vi.fn(async () => ({ run: { id: 's1', status: 'done', files: 3 }, files: [] }))
const listScans = vi.fn(async () => [])

vi.mock('./api.js', async (importActual) => ({
  ...(await importActual()),
  getConfig: vi.fn(async () => ({ auth: 'demo' })),
  getRubric: vi.fn(async () => ({ target: 'WCAG 2.1 AA', hash: 'abcdef0123' })),
  getSources: vi.fn(async () => []),
  listScans,
  getActiveScan: vi.fn(async () => null),
  getSettings: vi.fn(async () => ({ scan_scope: '' })),
  updateSettings: vi.fn(async () => ({ scan_scope: '' })),
  getScan,
  getDecisions: vi.fn(async () => ({})),
  startScanQueued: vi.fn(async () => { throw new Error('not used by this test') }),
  startScan,
  getJob,
}))

const { default: App } = await import('./App.jsx')

afterEach(() => { unmountAll(); sessionStorage.clear() })
beforeEach(() => {
  sessionStorage.clear()
  startScan.mockClear(); getJob.mockClear(); getScan.mockClear(); listScans.mockClear()
})

const flush = async () => { for (let i = 0; i < 4; i++) await act(async () => { await Promise.resolve() }) }
const byText = (c, sel, re) => [...c.querySelectorAll(sel)].find((e) => re.test(e.textContent))

async function mountSignedIn() {
  const { root, container } = createTestRoot()
  await act(async () => { root.render(createElement(App)) })
  await flush()
  await act(async () => { byText(container, 'button', /Sign in with SSO/)?.click() })
  await flush()
  return container
}

describe('reconnecting to a pending default-path job on mount', () => {
  it('resumes polling a job left in sessionStorage from before the reload', async () => {
    sessionStorage.setItem('active_job_id', 'j1')
    getJob.mockResolvedValue({ done: true, scan_id: 's1', phase: 'done' })

    const c = await mountSignedIn()
    // The poll waits 350ms before its first getJob call — real time, not faked, to avoid fighting
    // act()'s own microtask flushing.
    await new Promise((r) => setTimeout(r, 500))
    await flush()

    expect(getJob).toHaveBeenCalledWith('j1')
    // Resolved successfully → the key is cleared, so a LATER reload does not reconnect again.
    expect(sessionStorage.getItem('active_job_id')).toBeNull()
    // And no fresh scan was started — this was a RECONNECT, not a new dispatch.
    expect(startScan).not.toHaveBeenCalled()
    void c
  })

  it('surfaces the job error exactly as a live tab would have (built on #607)', async () => {
    sessionStorage.setItem('active_job_id', 'j2')
    getJob.mockResolvedValue({ done: true, error: 'scan interrupted — the server likely restarted mid-run; please start a new scan' })

    const c = await mountSignedIn()
    await new Promise((r) => setTimeout(r, 500))
    await flush()

    const err = c.querySelector('.err[role="alert"]')
    expect(err, 'no error banner shown for a job that resolved with an error').toBeTruthy()
    expect(err.textContent).toMatch(/scan interrupted/)
    // The key must still be cleared on the error path — a dangling key would try this dead job
    // again on every future reload, forever.
    expect(sessionStorage.getItem('active_job_id')).toBeNull()
  })

  it('does not reconnect when sessionStorage holds no pending job', async () => {
    await mountSignedIn()
    await flush()
    expect(getJob).not.toHaveBeenCalled()
  })
})

describe('starting a fresh default-path scan writes the same reconnect key', () => {
  it('sets active_job_id the moment the job starts, so an IMMEDIATE reload would still catch it', async () => {
    startScan.mockResolvedValue({ job_id: 'j3' })
    // Never resolves within this test's window — the point is to catch the key while in-flight.
    getJob.mockImplementation(() => new Promise(() => {}))

    const c = await mountSignedIn()
    const discoverTab = byText(c, '[role="tab"]', /Discover/)
    await act(async () => { discoverTab?.click() }); await flush()
    await act(async () => { byText(c, 'button', /Re-scan all sources/)?.click() }); await flush()
    const dialog = c.querySelector('[role="dialog"]')
    await gotoStep(dialog, act, 3)
    const start = dialog.querySelector('button[data-wizard-forward]')
    await act(async () => { start?.click() }); await flush()

    expect(startScan).toHaveBeenCalled()
    expect(sessionStorage.getItem('active_job_id')).toBe('j3')
  })
})
