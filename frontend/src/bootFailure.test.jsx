import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { createTestRoot, unmountAll } from './testRoots.js'

globalThis.__BUILD_TIME__ = '2026-08-01T00:00:00.000Z'
globalThis.__BUILD_VERSION__ = '2026.8.1'

// What happens when the boot chain does not come back.
//
// Two separate defects, both the shape found in /config on 2026-09-01 (a production dependency
// stalled for ~2 minutes; /readyz timed out while /healthz stayed green).
//
// 1. HANGS WERE UNBOUNDED. `getWorkspaceBootstrap` and the `getScan` awaited into its .then are the
//    only exits from the signed-in loading screen — one .finally on one chain. A request that hangs
//    never settles, so .then/.catch/.finally never run and "Loading your workspace…" renders
//    forever. There is no timer and no retry anywhere in that effect. Bounded now, so a stall
//    becomes a rejection the UI can act on.
//
// 2. THE REJECTION WAS SWALLOWED, AND MISREPORTED. The chain's `.catch(() => {})` discarded the
//    error, `.finally` flipped `loaded`, and the user was shown EmptyState — "No assessment has run
//    yet" — for an estate that might hold a thousand documents. A request that failed and an account
//    with nothing in it are different facts; they no longer share a screen.

function deferred() {
  let resolve, reject
  const promise = new Promise((res, rej) => { resolve = res; reject = rej })
  promise.catch(() => {})   // pre-attached: keeps a rejection from surfacing as unhandled
  return { promise, resolve, reject }
}

let scanDeferred, bootstrapDeferred
const getScan = vi.fn(() => scanDeferred.promise)
const getWorkspaceBootstrap = vi.fn(() => bootstrapDeferred.promise)

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
  getJob: vi.fn(),
}))

const { default: App } = await import('./App.jsx')
const { BOOT_TIMEOUT_MS, SCAN_READ_TIMEOUT_MS, SCAN_UNAVAILABLE } = await vi.importActual('./api.js')

const okBootstrap = () => ({
  me: { email: 'demo@example.com', is_scope_owner: true, is_admin: true },
  scan_id: null, scan_status: null, revision: 0, overview: null, scans: [], active_job: {},
})

afterEach(() => { unmountAll(); sessionStorage.clear() })
beforeEach(() => {
  sessionStorage.clear()
  getScan.mockClear(); getWorkspaceBootstrap.mockClear()
  scanDeferred = deferred(); bootstrapDeferred = deferred()
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

describe('the boot chain reports a failure instead of inventing an empty estate', () => {
  it('says the workspace could not be loaded, not "no assessment has run yet"', async () => {
    const c = await mountSignedIn()
    await act(async () => { bootstrapDeferred.reject(new Error('Failed to fetch')) })
    await flush()
    expect(c.textContent).toMatch(/Couldn’t load your workspace/)
    expect(c.textContent).toMatch(/Failed to fetch/)
    // The specific misreport this replaces: a failed read shown as an empty account.
    expect(c.textContent).not.toMatch(/No assessment has run yet/)
    expect(c.querySelector('[role="alert"]')).toBeTruthy()
  })

  it('names a timeout as a timeout', async () => {
    const c = await mountSignedIn()
    const e = new Error('signal timed out'); e.name = 'TimeoutError'
    await act(async () => { bootstrapDeferred.reject(e) })
    await flush()
    expect(c.textContent).toMatch(/did not respond in time/)
  })

  it('offers a retry that re-runs the boot chain and recovers', async () => {
    const c = await mountSignedIn()
    await act(async () => { bootstrapDeferred.reject(new Error('Failed to fetch')) })
    await flush()
    const before = getWorkspaceBootstrap.mock.calls.length
    const retry = byText(c, 'button', /Try again/)
    expect(retry).toBeTruthy()
    bootstrapDeferred = deferred()                       // the re-read gets a fresh promise
    await act(async () => { retry.click() })
    await flush()
    expect(getWorkspaceBootstrap.mock.calls.length).toBeGreaterThan(before)
    await act(async () => { bootstrapDeferred.resolve(okBootstrap()) })
    await flush()
    expect(c.textContent).not.toMatch(/Couldn’t load your workspace/)
  })

  it('leaves a 404 on the scan to its OWN recovery, which knows how to pick another scan', async () => {
    // acp:scan-unavailable already has a handler that recovers to a different scan. Showing the
    // generic boot error over it would replace a working recovery with a dead end.
    const c = await mountSignedIn()
    await act(async () => { bootstrapDeferred.reject(new Error(SCAN_UNAVAILABLE)) })
    await flush()
    expect(c.textContent).not.toMatch(/Couldn’t load your workspace/)
  })
})

describe('the boot reads are bounded', () => {
  // SOURCE-level: a hang needs a real stalled socket to observe, and each guard is one argument a
  // refactor could drop with every other test still green.
  const api = readFileSync(join(dirname(fileURLToPath(import.meta.url)), 'api.js'), 'utf8')
  const call = (re) => { const m = re.exec(api); expect(m, `not found: ${re}`).toBeTruthy(); return m[0] }

  it('/workspace/bootstrap — the only exit from the loading screen — carries a timeout', () => {
    expect(call(/bootFetch\(`\$\{BASE\}\/workspace\/bootstrap`[^)]*\)/)).toContain('bootFetch')
  })

  it('/healthz carries one too, because it is the RESCUE path', () => {
    // backendDown starts null, so the banner and its Retry render only once a probe answers. A hung
    // /healthz disables the very control that reports the outage.
    expect(call(/bootFetch\(`\$\{BASE\}\/healthz`\)/)).toContain('bootFetch')
  })

  it('getScan is bounded, but on a LONGER ceiling than the light reads', () => {
    // Anchored on `}).then(` — the init object contains its own `})` inside headers(), which a
    // lazier pattern stops at and then reports a missing signal that is actually there.
    const m = /fetch\(`\$\{BASE\}\/scans\/\$\{id\}`,[\s\S]{0,400}?\}\)\.then\(/.exec(api)
    expect(m).toBeTruthy()
    expect(m[0]).toMatch(/signal:\s*AbortSignal\.timeout\(SCAN_READ_TIMEOUT_MS\)/)
    // It is a genuinely heavy query on a large estate. A ceiling that turns working-but-slow into
    // broken would be a worse bug than the hang, so this ordering is the point, not an accident.
    expect(SCAN_READ_TIMEOUT_MS).toBeGreaterThan(BOOT_TIMEOUT_MS)
    expect(BOOT_TIMEOUT_MS).toBeGreaterThan(1000)
    expect(SCAN_READ_TIMEOUT_MS).toBeLessThanOrEqual(60000)
  })

  it('leaves reads that gate nothing alone — the scope is the whole justification', () => {
    // getMe supplements an identity already set synchronously by signIn(); it gates no screen and
    // fails open. Timing out every read in this file would break long uploads and scan enqueues.
    expect(/export const getMe = [^\n]*\bfetch\(/.test(api)).toBe(true)
    expect(/export const getMe = [^\n]*bootFetch\(/.test(api)).toBe(false)
  })
})
