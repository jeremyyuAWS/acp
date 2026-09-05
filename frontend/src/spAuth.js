// Shared MSAL silent-refresh so a long-running scan can keep its SharePoint token fresh.
// MSAL access tokens expire ~1h; while a scan runs longer, the backend worker's snapshot
// token goes stale. refreshSPToken() silently re-acquires one (no popup while the MSAL
// session is valid) and updates sessionStorage; App pushes it to the running scan.
//
// Mirrors driveAuth.js for GIS. One lazy MSAL instance, independent of the SharePoint
// component which owns its own. No-op (rejects) without VITE_AZURE_CLIENT_ID or before
// the MSAL script loads — every caller treats it as best-effort.
const CLIENT_ID = import.meta.env.VITE_AZURE_CLIENT_ID || ''
const TENANT    = import.meta.env.VITE_AZURE_TENANT_ID  || 'common'
const SCOPES    = ['Files.ReadWrite.All', 'Sites.ReadWrite.All', 'User.Read']

let _instance = null
let _initPromise = null

async function ensureInstance() {
  if (_instance) return _instance
  if (!CLIENT_ID || !window.msal) return null
  if (_initPromise) return _initPromise
  _initPromise = (async () => {
    const inst = new window.msal.PublicClientApplication({
      auth: { clientId: CLIENT_ID, authority: `https://login.microsoftonline.com/${TENANT}`, redirectUri: window.location.origin },
      cache: { cacheLocation: 'sessionStorage', storeAuthStateInCookie: false },
    })
    await inst.initialize()
    // Resolve any pending redirect without side-effects (no redirect in flight — best-effort).
    await inst.handleRedirectPromise().catch(() => {})
    _instance = inst
    return inst
  })()
  return _initPromise
}

export async function refreshSPToken() {
  const inst = await ensureInstance()
  if (!inst) throw new Error('MSAL not ready')
  const account = inst.getActiveAccount() || inst.getAllAccounts()[0]
  if (!account) throw new Error('no active Microsoft account')
  const tok = await inst.acquireTokenSilent({ scopes: SCOPES, account })
    .catch(() => inst.acquireTokenPopup({ scopes: SCOPES, account }))
  try { sessionStorage.setItem('sp_token', tok.accessToken) } catch { /* ignore */ }
  return tok.accessToken
}
