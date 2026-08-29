/**
 * App.jsx's initial-load effect (listScans -> getScan/getActiveScan -> reconnectJob/reconnectScan)
 * used to run as one fully sequential chain behind a single static "Loading your workspace…"
 * message the whole way through — reported live 2026-08-29 as an unexplained hang with nothing
 * to show for it. Two independent fixes:
 *
 *   1. getScan(defaultScanId) and getActiveScan() have no data dependency on each other, so they
 *      now run concurrently (Promise.all) instead of one waiting for the other to finish first —
 *      removing one full network round-trip from the critical path.
 *   2. A `loadStage` state now says which step is in flight (EmptyState.jsx's Loading component),
 *      so a genuinely slow step is at least legible instead of a silent spinner.
 *
 * `reconnectJob` (the pending-job-reconnect path) is NOT part of either fix's awaited chain —
 * it owns its own busy/progress UI and can run for as long as the reconnected job takes, so it
 * must stay fire-and-forget exactly as before. These tests prove all three properties: the
 * two calls overlap, the stage text changes, and a slow/never-resolving reconnectJob never
 * blocks the workspace from loading.
 */
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

globalThis.__BUILD_TIME__ = '2026-08-01T00:00:00.000Z'
globalThis.__BUILD_VERSION__ = '2026.8.1'

/** A promise plus its own resolve function, so a test can control exactly when a mock settles. */
function deferred() {
  let resolve
  const promise = new Promise((r) => { resolve = r })
  return { promise, resolve }
}

const getJob = vi.fn()
let scanDeferred, activeScanDeferred
const getScan = vi.fn(() => scanDeferred.promise)
const getActiveScan = vi.fn(() => activeScanDeferred.promise)
const listScans = vi.fn(async () => [{ id: 's1', completed_at: '2026-08-29T04:00:00Z', files: 3 }])

vi.mock('./api.js', async (importActual) => ({
  ...(await importActual()),
  getConfig: vi.fn(async () => ({ auth: 'demo' })),
  getRubric: vi.fn(async () => ({ target: 'WCAG 2.1 AA', hash: 'abcdef0123' })),
  getSources: vi.fn(async () => []),
  listScans,
  getActiveScan,
  getSettings: vi.fn(async () => ({ scan_scope: '' })),
  updateSettings: vi.fn(async () => ({ scan_scope: '' })),
  getScan,
  getDecisions: vi.fn(async () => ({})),
  startScanQueued: vi.fn(async () => { throw new Error('not used by this test') }),
  startScan: vi.fn(),
  getJob,
}))

const { default: App } = await import('./App.jsx')

afterEach(() => { unmountAll(); sessionStorage.clear() })
beforeEach(() => {
  sessionStorage.clear()
  getJob.mockReset()
  getScan.mockClear(); getActiveScan.mockClear(); listScans.mockClear()
  scanDeferred = deferred()
  activeScanDeferred = deferred()
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

describe('the initial-load screen', () => {
  it('shows a stage-specific message, not a static one, while loading the default scan', async () => {
    const c = await mountSignedIn()
    expect(c.textContent).toMatch(/Loading your latest scan/)
  })

  it('calls getScan and getActiveScan concurrently — neither waits for the other to resolve first', async () => {
    await mountSignedIn()
    // Both calls must have fired before EITHER promise resolves — a sequential chain would only
    // have called the first of the two by this point.
    expect(getScan).toHaveBeenCalledTimes(1)
    expect(getActiveScan).toHaveBeenCalledTimes(1)
  })

  it('finishes loading (leaves the loading screen) once both calls resolve', async () => {
    const c = await mountSignedIn()
    expect(c.textContent).toMatch(/Loading your latest scan/)

    await act(async () => {
      scanDeferred.resolve({ run: { id: 's1', status: 'done', files: 3 }, files: [] })
      activeScanDeferred.resolve(null)
      await Promise.resolve()
    })
    await flush()

    expect(c.textContent).not.toMatch(/Loading your latest scan/)
    expect(c.textContent).not.toMatch(/Loading your workspace/)
  })

  it('a pending reconnectJob never blocks the workspace from loading, even if its poll never '
     + 'resolves — it owns its own busy UI, not this loading screen\'s', async () => {
    sessionStorage.setItem('active_job_id', 'j1')
    getJob.mockReturnValue(new Promise(() => {}))   // never resolves — the exact regression risk

    const c = await mountSignedIn()
    await act(async () => {
      scanDeferred.resolve({ run: { id: 's1', status: 'done', files: 3 }, files: [] })
      await Promise.resolve()
    })
    await flush()

    // getActiveScan is skipped entirely on this branch (a pending job and an active scan_runs
    // row are never both real at once), so only getScan gates the load — the workspace still
    // finishes loading despite getJob's promise never settling.
    expect(c.textContent).not.toMatch(/Loading your latest scan/)
    expect(c.textContent).not.toMatch(/Loading your workspace/)
    expect(getActiveScan).not.toHaveBeenCalled()
  })
})
