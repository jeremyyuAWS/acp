import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'

// api.js short-circuits to canned data when SIM is on; these are about the real fetch path.
vi.mock('./sim.js', async (o) => ({ ...(await o()), SIM: false }))

const { getRubric, setGoogleToken, clearAllTokens, SESSION_EXPIRED } = await import('./api.js')

// A Response-alike with header lookup (case-insensitive) and a json body.
const resp = (status, headers = {}) => {
  const h = new Map(Object.entries(headers).map(([k, v]) => [k.toLowerCase(), v]))
  return {
    ok: status < 400, status, statusText: '', url: 'http://localhost:8077/rubric',
    headers: { get: (k) => (h.has(k.toLowerCase()) ? h.get(k.toLowerCase()) : null) },
    json: async () => ({ detail: 'x' }),
  }
}

let events, lastInit
beforeEach(() => {
  clearAllTokens()
  events = []
  window.addEventListener('acp:session-expired', (e) => events.push(e))
  lastInit = null
})
afterEach(() => { vi.unstubAllGlobals(); clearAllTokens() })

describe('a GATE 401 signs the user out; a ROUTE 401 does not', () => {
  it('GATE 401 (X-Acp-Auth: session) → dispatches session-expired', async () => {
    setGoogleToken('tok')
    vi.stubGlobal('fetch', () => Promise.resolve(resp(401, { 'X-Acp-Auth': 'session' })))
    await expect(getRubric()).rejects.toThrow(SESSION_EXPIRED)
    expect(events.length).toBe(1)
  })

  it('ROUTE 401 (no marker) → NO session-expired, and the bearer survives', async () => {
    setGoogleToken('tok')
    vi.stubGlobal('fetch', (_u, init) => {
      lastInit = init
      return Promise.resolve(resp(401))            // a route refusing for its own reason
    })
    await expect(getRubric()).rejects.toThrow()     // still an error...
    expect(events.length).toBe(0)                   // ...but NOT a session expiry

    // the token was not cleared: the next call still carries the Authorization bearer
    vi.stubGlobal('fetch', (_u, init) => { lastInit = init; return Promise.resolve(resp(200)) })
    await getRubric().catch(() => {})
    expect(lastInit.headers['Authorization']).toBe('Bearer tok')
  })
})
