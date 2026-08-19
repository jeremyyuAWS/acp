import { describe, it, expect, vi, beforeEach } from 'vitest'

// A stand-in for the MSAL v3 global (window.msal). loginPopup can be told to throw a given errorCode
// on its first call so we can drive the `interaction_in_progress` recovery path deterministically.
function makeMsal({ failFirstWith } = {}) {
  const ctorCalls = { n: 0 }
  let logins = 0
  class PublicClientApplication {
    constructor() { ctorCalls.n++ }
    initialize() { return Promise.resolve() }
    handleRedirectPromise() { return Promise.resolve(null) }
    setActiveAccount() {}
    loginPopup() {
      logins++
      if (failFirstWith && logins === 1) {
        const e = new Error('blocked'); e.errorCode = failFirstWith; return Promise.reject(e)
      }
      return Promise.resolve({ account: { username: 'jeremy_acp@fgxlxj.onmicrosoft.com', name: 'Jeremy' } })
    }
    acquireTokenSilent() { return Promise.resolve({ accessToken: 'TOK' }) }
    acquireTokenPopup() { return Promise.resolve({ accessToken: 'TOK' }) }
  }
  return { PublicClientApplication, ctorCalls }
}

const okAuth = () => ({ getSpAuth: () => Promise.resolve({ clientId: 'cid', tenant: 'common' }) })

describe('signInForScopes — resilient shared MSAL client', () => {
  beforeEach(() => { vi.resetModules(); window.sessionStorage.clear(); window.localStorage.clear(); delete window.msal })

  it('returns the account + access token on the happy path', async () => {
    vi.doMock('./sharepointScopes.js', okAuth)
    window.msal = makeMsal()
    const { signInForScopes } = await import('./msalClient.js')
    const r = await signInForScopes(['User.Read'])
    expect(r.accessToken).toBe('TOK')
    expect(r.account.username).toBe('jeremy_acp@fgxlxj.onmicrosoft.com')
  })

  it('self-heals interaction_in_progress: clears the stuck lock and retries once', async () => {
    vi.doMock('./sharepointScopes.js', okAuth)
    window.msal = makeMsal({ failFirstWith: 'interaction_in_progress' })
    // A lock left behind by an earlier fumbled popup — the exact wedge testers were hitting.
    window.sessionStorage.setItem('msal.cid.interaction.status', 'interaction_in_progress')
    const { signInForScopes } = await import('./msalClient.js')
    const r = await signInForScopes(['User.Read'])
    expect(r.accessToken).toBe('TOK')                                              // recovered, not thrown
    expect(window.sessionStorage.getItem('msal.cid.interaction.status')).toBeNull() // lock released
  })

  it('does not swallow other errors — user_cancelled propagates unchanged', async () => {
    vi.doMock('./sharepointScopes.js', okAuth)
    window.msal = makeMsal({ failFirstWith: 'user_cancelled' })
    const { signInForScopes } = await import('./msalClient.js')
    await expect(signInForScopes(['User.Read'])).rejects.toMatchObject({ errorCode: 'user_cancelled' })
  })

  it('creates exactly one PublicClientApplication across repeated sign-ins (no per-click instance)', async () => {
    vi.doMock('./sharepointScopes.js', okAuth)
    const msal = makeMsal()
    window.msal = msal
    const { signInForScopes } = await import('./msalClient.js')
    await signInForScopes(['User.Read'])
    await signInForScopes(['User.Read'])
    expect(msal.ctorCalls.n).toBe(1)
  })

  it('throws MsalNotReady when the MSAL script has not loaded', async () => {
    vi.doMock('./sharepointScopes.js', okAuth)
    // window.msal deliberately absent
    const { signInForScopes, MsalNotReady } = await import('./msalClient.js')
    await expect(signInForScopes(['User.Read'])).rejects.toBeInstanceOf(MsalNotReady)
  })

  it('throws MsalNotConfigured when no Entra client id is configured', async () => {
    vi.doMock('./sharepointScopes.js', () => ({ getSpAuth: () => Promise.resolve({ clientId: '', tenant: 'common' }) }))
    window.msal = makeMsal()
    const { signInForScopes, MsalNotConfigured } = await import('./msalClient.js')
    await expect(signInForScopes(['User.Read'])).rejects.toBeInstanceOf(MsalNotConfigured)
  })
})
