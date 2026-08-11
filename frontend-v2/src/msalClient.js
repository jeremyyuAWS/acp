// One shared MSAL client for the whole SPA, plus a sign-in that survives the two failure modes
// testers hit most (see aka.ms/msaljs/browser-errors):
//
//   1. `interaction_in_progress` — MSAL keeps an interaction lock in web storage while a popup or
//      redirect is open. A popup that is closed, blocked, or double-clicked can leave that lock set,
//      and then EVERY later sign-in throws, permanently, until storage is cleared by hand. MSAL
//      exposes no API to release it, so we remove the lock key directly and retry once.
//   2. A fresh `new PublicClientApplication()` on every click — the old shape, duplicated in SignIn
//      and Integrations. Two instances racing the same storage is itself a way to strand the lock
//      above. Here there is exactly one instance per (clientId, tenant), created and initialized once.
//
// Both entry points (the login screen and the Integrations connect card) call signInForScopes, so
// they can never drift apart or fight each other over interaction state.
import { getSpAuth } from './sharepointScopes.js'

// Distinct from an MSAL sign-in failure: the library script hasn't loaded, or the deployment has no
// Entra client id. Callers map these to their own copy rather than showing a raw MSAL string.
export class MsalNotReady extends Error {}
export class MsalNotConfigured extends Error {}

let _instancePromise = null
let _key = null

// One instance per (clientId, tenant): created once, initialize() awaited once, and any interrupted
// redirect resolved. Re-resolves only if the runtime config points at a different app/tenant.
async function getInstance() {
  if (!window.msal) throw new MsalNotReady('MSAL not loaded')
  const { clientId, tenant } = await getSpAuth()
  if (!clientId) throw new MsalNotConfigured('No Entra client id')
  const key = `${clientId}@${tenant}`
  if (_instancePromise && _key === key) return _instancePromise
  _key = key
  _instancePromise = (async () => {
    const inst = new window.msal.PublicClientApplication({
      auth: { clientId, authority: `https://login.microsoftonline.com/${tenant}`, redirectUri: window.location.origin },
      cache: { cacheLocation: 'sessionStorage', storeAuthStateInCookie: false },
    })
    await inst.initialize()
    await inst.handleRedirectPromise().catch(() => { /* no redirect pending, or already handled */ })
    return inst
  })()
  return _instancePromise
}

// Release a stuck interaction lock. Scoped to the keys that carry it, across whichever web store the
// cache lives in — so we clear the wedge without wiping an in-progress Google token or anything else.
function clearStuckInteraction() {
  try {
    for (const store of [window.sessionStorage, window.localStorage]) {
      for (const k of Object.keys(store)) {
        if (k.includes('interaction.status')) store.removeItem(k)
      }
    }
  } catch { /* storage blocked — nothing we can clear, let the original error surface */ }
}

// Sign in and return { account, accessToken } for the given scopes. Retries exactly once, after
// clearing a stale interaction lock, so one testerʼs fumbled popup doesn't wedge every later attempt.
// Any other MSAL error (user_cancelled, popup_window_error, …) propagates unchanged for the caller
// to phrase.
export async function signInForScopes(scopes) {
  const attempt = async () => {
    const inst = await getInstance()
    const res = await inst.loginPopup({ scopes })
    inst.setActiveAccount(res.account)
    const tok = await inst.acquireTokenSilent({ scopes, account: res.account })
      .catch(() => inst.acquireTokenPopup({ scopes }))
    return { account: res.account, accessToken: tok.accessToken }
  }
  try {
    return await attempt()
  } catch (e) {
    if (e?.errorCode === 'interaction_in_progress') {
      clearStuckInteraction()
      return await attempt()
    }
    throw e
  }
}
