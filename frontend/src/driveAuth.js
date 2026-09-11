// Shared GIS silent-refresh so a long-running scan can keep its Drive token fresh
// (ADR 0014). GIS access tokens expire ~1h; while a scan runs longer than that, the
// backend worker's snapshot token would go stale and the tail of the scan would 401.
// refreshDriveToken() silently re-mints an access token (no popup while the Google
// session is valid) and updates sessionStorage; App pushes it to the running scan.
//
// Lazily inits ONE token client, independent of the GoogleDrive/Integrations picker
// components (which own their own). No-op (rejects) without VITE_GOOGLE_CLIENT_ID or
// before the GIS script has loaded — every caller treats it as best-effort.
const CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID || ''
const SCOPES = 'https://www.googleapis.com/auth/drive.readonly https://www.googleapis.com/auth/drive.file'

let client = null
let pending = null

function ensureClient() {
  if (client) return client
  if (!CLIENT_ID || !window.google?.accounts?.oauth2) return null
  client = window.google.accounts.oauth2.initTokenClient({
    client_id: CLIENT_ID,
    scope: SCOPES,
    callback: (resp) => {
      const p = pending
      pending = null
      if (!p) return
      if (resp.error) { p.reject(new Error(resp.error_description || resp.error)); return }
      try { sessionStorage.setItem('gd_token', resp.access_token) } catch { /* ignore */ }
      p.resolve(resp.access_token)
    },
  })
  return client
}

export function refreshDriveToken() {
  return new Promise((resolve, reject) => {
    const c = ensureClient()
    if (!c) { reject(new Error('GIS not ready')); return }
    const timer = setTimeout(() => {
      if (pending) { pending = null; reject(new Error('drive token refresh timed out')) }
    }, 30000)
    pending = {
      resolve: (tok) => { clearTimeout(timer); resolve(tok) },
      reject: (err) => { clearTimeout(timer); reject(err) },
    }
    c.requestAccessToken({ prompt: '' })   // silent while the Google session is valid
  })
}

// Explicit user action: request the same scopes as the Drive connection picker.
export function reconnectDriveForRelease() {
  return new Promise((resolve, reject) => {
    if (!CLIENT_ID || !window.google?.accounts?.oauth2) {
      reject(new Error('Google Drive sign-in is not ready. Reload this page and try again.')); return
    }
    let settled = false
    const finish = (error, token) => {
      if (settled) return
      settled = true; clearTimeout(timer)
      if (error) reject(error)
      else resolve(token)
    }
    const timer = setTimeout(() => finish(new Error('Google Drive sign-in timed out. Try reconnecting again.')), 60000)
    let releaseClient
    try { releaseClient = window.google.accounts.oauth2.initTokenClient({
      client_id: CLIENT_ID,
      scope: 'https://www.googleapis.com/auth/drive.readonly https://www.googleapis.com/auth/drive.file',
      callback: response => {
        if (response.error || !response.access_token) {
          finish(new Error('Google Drive access was not granted. Your saved release is unchanged.')); return
        }
        const hasScopes = window.google.accounts.oauth2.hasGrantedAllScopes
        const required = SCOPES.split(' ')
        const granted = typeof hasScopes === 'function' ? hasScopes(response, ...required) : required.every(scope => String(response.scope || '').split(' ').includes(scope))
        if (!granted) {
          finish(new Error('Allow Google Drive file access to resume delivery.')); return
        }
        finish(null, response.access_token)
      },
      error_callback: () => finish(new Error('Google Drive sign-in was cancelled or could not open. Try reconnecting again.')),
    }) } catch { finish(new Error('Google Drive sign-in could not open. Try reconnecting again.')); return }
    try { releaseClient.requestAccessToken({ prompt: 'consent' }) }
    catch { finish(new Error('Google Drive sign-in could not open. Try reconnecting again.')) }
  })
}
