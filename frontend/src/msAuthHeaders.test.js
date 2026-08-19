import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'

// api.js short-circuits to canned data whenever SIM is on, and SIM defaults ON under vitest. These
// tests are about the REAL fetch path (what headers go over the wire), so turn it off for this
// module only.
vi.mock('./sim.js', async (importOriginal) => ({ ...(await importOriginal()), SIM: false }))

const { setGoogleToken, setMsToken, clearAllTokens, getRubric } = await import('./api.js')

// A Microsoft sign-in must send an Authorization bearer the backend can verify — tagged with
// X-Auth-Provider so the gate checks it against Graph, not Google. Without both, #239's Microsoft
// login has no accepted credential and every call 401s ("session expired") the instant the user is in.
let lastInit
beforeEach(() => {
  clearAllTokens()
  lastInit = null
  vi.stubGlobal('fetch', (_url, init) => { lastInit = init; return Promise.resolve({ ok: true, status: 200, json: async () => ({}) }) })
})
afterEach(() => { vi.unstubAllGlobals(); clearAllTokens() })

describe('API bearer carries the right identity per provider', () => {
  it('a Microsoft sign-in sends Bearer + X-Auth-Provider: microsoft', async () => {
    setMsToken('ms-tok')
    await getRubric()
    expect(lastInit.headers['Authorization']).toBe('Bearer ms-tok')
    expect(lastInit.headers['X-Auth-Provider']).toBe('microsoft')
  })

  it('a Google sign-in sends Bearer and NO provider header (path unchanged)', async () => {
    setGoogleToken('g-tok')
    await getRubric()
    expect(lastInit.headers['Authorization']).toBe('Bearer g-tok')
    expect(lastInit.headers['X-Auth-Provider']).toBeUndefined()
  })

  it('Google wins when both are set — no ambiguous double-auth', async () => {
    setGoogleToken('g-tok'); setMsToken('ms-tok')
    await getRubric()
    expect(lastInit.headers['Authorization']).toBe('Bearer g-tok')
    expect(lastInit.headers['X-Auth-Provider']).toBeUndefined()
  })

  it('clearAllTokens drops the Microsoft bearer too', async () => {
    setMsToken('ms-tok'); clearAllTokens()
    await getRubric()
    expect(lastInit.headers['Authorization']).toBeUndefined()
    expect(lastInit.headers['X-Auth-Provider']).toBeUndefined()
  })
})
