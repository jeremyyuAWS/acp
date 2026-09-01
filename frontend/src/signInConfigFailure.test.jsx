import { act } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import SignIn from './SignIn.jsx'
// Imported from the REAL module: the mock below replaces ./api.js for the component tests, so this
// constant is read via a separate specifier that the mock does not intercept.
const { CONFIG_TIMEOUT_MS } = await vi.importActual('./api.js')

// The sign-in screen's failure modes, which is where /config's absence of a timeout showed up:
// SignIn is the only surface gated entirely on that one request.
//
// Two distinct defects are pinned here.
//
// 1. A HUNG /config left the screen on "Loading…" forever. There was no timeout, and a hung fetch
//    never rejects, so the caller's .catch could not help. Fixed in api.js with AbortSignal.timeout;
//    what this file asserts is the consequence — a rejection now produces a screen with a way out.
//
// 2. Any failed /config fell through to `setCfg({ auth: 'demo' })`, which renders the persona cards.
//    On a real deployment that offered invented accounts ("explore a role — demo") because a request
//    failed, with nothing saying the server was unreachable. Being unable to read the config is not
//    the same fact as the config saying "demo", and the two no longer share a screen.
const getConfig = vi.fn()
const setLangfuseBase = vi.fn()
vi.mock('./api.js', () => ({ getConfig: (...a) => getConfig(...a), setLangfuseBase: (...a) => setLangfuseBase(...a) }))

afterEach(unmountAll)
globalThis.IS_REACT_ACT_ENVIRONMENT = true

let root, container
beforeEach(() => { getConfig.mockReset(); setLangfuseBase.mockReset(); ({ root, container } = createTestRoot()) })

const render = async () => { await act(async () => root.render(<SignIn onSignedIn={vi.fn()} />)) }
const btn = (t) => [...container.querySelectorAll('button')].find((b) => b.textContent.includes(t))

describe('/config carries a timeout', () => {
  // SOURCE-level, deliberately. The behaviour — a hung request becoming a rejection — cannot be
  // observed without a real hung socket, and the guard is one argument that can be dropped in a
  // refactor with every other test still green. That is exactly the shape this repo asserts against
  // the source (see remediateWiring.test.jsx), because the failure it prevents is invisible.
  const api = readFileSync(join(dirname(fileURLToPath(import.meta.url)), 'api.js'), 'utf8')

  it('the /config fetch passes an abort signal, so a hang cannot outlive the timeout', () => {
    const call = /fetch\(`\$\{BASE\}\/config`[^)]*\)/.exec(api)
    expect(call, '/config fetch not found in api.js').toBeTruthy()
    expect(call[0]).toMatch(/signal:\s*AbortSignal\.timeout\(CONFIG_TIMEOUT_MS\)/)
  })

  it('the timeout is a real, bounded number', () => {
    expect(CONFIG_TIMEOUT_MS).toBeGreaterThan(1000)     // not so tight it fails a slow-but-fine link
    expect(CONFIG_TIMEOUT_MS).toBeLessThanOrEqual(15000) // not so loose the user gives up first
  })
})

describe('SignIn when /config cannot be read', () => {
  it('says the server is unreachable instead of sitting on "Loading…"', async () => {
    getConfig.mockRejectedValue(new Error('Failed to fetch'))
    await render()
    expect(container.textContent).toContain('Can’t reach the server')
    expect(container.textContent).not.toContain('Loading…')
    // Announced, not merely coloured — this replaces a screen a screen-reader user could not
    // distinguish from a slow load.
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('Can’t reach the server')
  })

  it('does NOT offer demo personas on a real deployment because a request failed', async () => {
    // The specific dishonesty this replaces: invented accounts presented as sign-in options.
    getConfig.mockRejectedValue(new Error('Failed to fetch'))
    await render()
    expect(container.textContent).not.toContain('explore a role')
    expect(container.querySelectorAll('.personacard').length).toBe(0)
  })

  it('names a timeout as a timeout, so a stall is not reported as a hard failure', async () => {
    const e = new Error('signal timed out'); e.name = 'TimeoutError'
    getConfig.mockRejectedValue(e)
    await render()
    expect(container.textContent).toContain('did not respond in time')
  })

  it('offers a retry that actually re-reads the config, and recovers on success', async () => {
    getConfig.mockRejectedValue(new Error('Failed to fetch'))
    await render()
    expect(btn('Try again')).toBeTruthy()
    // Counted as "more than before", not an exact total. Mounting this component reads the config
    // twice in this harness — measured, and identical on the pre-change component, so it is the
    // harness rather than anything here. The claim under test is that pressing Retry issues a
    // FRESH read, which an exact-count assertion would only obscure.
    const before = getConfig.mock.calls.length
    getConfig.mockResolvedValue({ auth: 'gis', google_client_id: 'x' })
    await act(async () => btn('Try again').click())
    expect(getConfig.mock.calls.length).toBeGreaterThan(before)
    // Recovered into the real sign-in screen — no reload required.
    expect(container.textContent).not.toContain('Can’t reach the server')
    expect(btn('Sign in with Google')).toBeTruthy()
  })

  it('still shows the personas when the config genuinely SAYS demo', async () => {
    // The guard on the fix: SIM builds resolve auth:'demo' without a network call, and that path is
    // untouched. Only the failure path changed.
    getConfig.mockResolvedValue({ auth: 'demo' })
    await render()
    expect(container.textContent).toContain('explore a role')
    expect(container.textContent).not.toContain('Can’t reach the server')
  })
})
