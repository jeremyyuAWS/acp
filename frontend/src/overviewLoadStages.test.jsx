/**
 * App.jsx's initial-load effect used to run listScans -> getScan/getActiveScan as one fully
 * sequential chain behind a single static "Loading your workspace…" message the whole way
 * through — reported live 2026-08-29 as an unexplained hang with nothing to show for it. Fixed
 * by parallelizing getScan/getActiveScan and adding a stage-specific `loadStage` message
 * (EmptyState.jsx's Loading component).
 *
 * The workspace-bootstrap redesign (#960/#962, backend) went a step further: GET
 * /workspace/bootstrap now answers what listScans + getActiveScan used to (the scan-picker
 * list, the picked default scan's id, and the active-job summary) in ONE request, so there is
 * no longer anything to parallelize AT THAT STEP — getActiveScan is not called at all from this
 * effect any more. getScan(scanId) — the one genuinely heavy call, still needed for the full
 * file/finding payload other tabs read — is the only thing left gating `loaded`.
 *
 * These tests prove: the stage text still changes: reconnectJob stays fire-and-forget and never
 * blocks the load; bootstrap's active_job is used for reconnectScan instead of a separate
 * getActiveScan call; and the bootstrap's `overview` field reaches the loading screen as its
 * preview line before getScan resolves.
 *
 * Stale-while-revalidate went a step further still: when the Overview tab (the default view) has
 * a cached snapshot to show, it no longer shows a "Loading your latest scan…" spinner with a
 * one-line preview underneath at all — OverviewPreviewCard renders real aggregate tiles in its
 * place, swapped for the full Overview the instant getScan resolves. The stage-text mechanism
 * itself is unchanged and still gates every OTHER tab (and Overview before any snapshot exists),
 * so the test below that exercises it uses a bootstrap response with no `overview` snapshot to
 * isolate that behavior from the preview card's.
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
let scanDeferred, bootstrapDeferred
const getScan = vi.fn(() => scanDeferred.promise)
const getWorkspaceBootstrap = vi.fn(() => bootstrapDeferred.promise)
const reconnectScanCalls = []

vi.mock('./api.js', async (importActual) => ({
  ...(await importActual()),
  getConfig: vi.fn(async () => ({ auth: 'demo' })),
  getRubric: vi.fn(async () => ({ target: 'WCAG 2.1 AA', hash: 'abcdef0123' })),
  getSources: vi.fn(async () => []),
  getWorkspaceBootstrap,
  getSettings: vi.fn(async () => ({ scan_scope: '' })),
  updateSettings: vi.fn(async () => ({ scan_scope: '' })),
  getScan,
  getDecisions: vi.fn(async () => ({})),
  startScanQueued: vi.fn(async () => { throw new Error('not used by this test') }),
  startScan: vi.fn(),
  getJob,
}))

const { default: App } = await import('./App.jsx')

const defaultBootstrap = () => ({
  me: { email: 'demo@example.com', is_scope_owner: true, is_admin: true },
  scan_id: 's1', scan_status: 'done', revision: 0,
  overview: { estate: { discovered: 3 }, documents: { certifiable: 2 } },
  scans: [{ id: 's1', completed_at: '2026-08-29T04:00:00Z', files: 3 }],
  active_job: {},
})

afterEach(() => { unmountAll(); sessionStorage.clear() })
beforeEach(() => {
  sessionStorage.clear()
  getJob.mockReset()
  getScan.mockClear(); getWorkspaceBootstrap.mockClear()
  reconnectScanCalls.length = 0
  scanDeferred = deferred()
  bootstrapDeferred = deferred()
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
  it('shows the bootstrap stage message while the one request is in flight', async () => {
    const c = await mountSignedIn()
    expect(c.textContent).toMatch(/Loading your workspace/)
  })

  it('shows the scan-specific stage message once bootstrap resolves with a default scan '
     + 'but no cached snapshot yet', async () => {
    const c = await mountSignedIn()
    await act(async () => {
      bootstrapDeferred.resolve({ ...defaultBootstrap(), overview: null })
      await Promise.resolve()
    })
    await flush()
    expect(c.textContent).toMatch(/Loading your latest scan/)
  })

  it('renders the aggregate preview card — not the bare loading screen — the instant bootstrap\'s '
     + 'overview snapshot arrives, while getScan is still in flight', async () => {
    const c = await mountSignedIn()
    await act(async () => { bootstrapDeferred.resolve(defaultBootstrap()); await Promise.resolve() })
    await flush()
    expect(c.textContent).not.toMatch(/Loading your latest scan/)
    expect(c.textContent).toMatch(/loading full detail/)
    expect(c.textContent).toContain('3')   // estate.discovered
    expect(c.textContent).toContain('2')   // documents.certifiable
  })

  it('calls getWorkspaceBootstrap once, then getScan for the picked default scan — no separate '
     + 'getActiveScan call any more', async () => {
    await mountSignedIn()
    await act(async () => { bootstrapDeferred.resolve(defaultBootstrap()); await Promise.resolve() })
    await flush()
    expect(getWorkspaceBootstrap).toHaveBeenCalledTimes(1)
    expect(getScan).toHaveBeenCalledTimes(1)
    expect(getScan).toHaveBeenCalledWith('s1')
  })

  it('finishes loading (swaps the preview card for the full Overview) once getScan resolves', async () => {
    const c = await mountSignedIn()
    await act(async () => { bootstrapDeferred.resolve(defaultBootstrap()); await Promise.resolve() })
    await flush()
    expect(c.textContent).toMatch(/loading full detail/)

    await act(async () => {
      scanDeferred.resolve({ run: { id: 's1', status: 'done', files: 3 }, files: [] })
      await Promise.resolve()
    })
    await flush()

    expect(c.textContent).not.toMatch(/Loading your latest scan/)
    expect(c.textContent).not.toMatch(/Loading your workspace/)
    expect(c.textContent).not.toMatch(/loading full detail/)
  })

  it('a pending reconnectJob never blocks the workspace from loading, even if its poll never '
     + 'resolves — it owns its own busy UI, not this loading screen\'s', async () => {
    sessionStorage.setItem('active_job_id', 'j1')
    getJob.mockReturnValue(new Promise(() => {}))   // never resolves — the exact regression risk

    const c = await mountSignedIn()
    await act(async () => { bootstrapDeferred.resolve(defaultBootstrap()); await Promise.resolve() })
    await flush()
    await act(async () => {
      scanDeferred.resolve({ run: { id: 's1', status: 'done', files: 3 }, files: [] })
      await Promise.resolve()
    })
    await flush()

    expect(c.textContent).not.toMatch(/Loading your latest scan/)
    expect(c.textContent).not.toMatch(/Loading your workspace/)
  })

  it('finishes loading straight to the empty state when bootstrap has no default scan — '
     + 'active_job already came back as part of bootstrap, so there is nothing left to await', async () => {
    const c = await mountSignedIn()
    await act(async () => {
      bootstrapDeferred.resolve({ me: { email: 'demo@example.com' }, scan_id: null,
                                  scan_status: null, revision: null, overview: null,
                                  scans: [], active_job: {} })
      await Promise.resolve()
    })
    await flush()
    expect(c.textContent).not.toMatch(/Loading your workspace/)
    expect(c.textContent).toMatch(/No assessment has run yet/)
    expect(getScan).not.toHaveBeenCalled()
  })
})
