import { useEffect, useState } from 'react'
import { getMe, getConfig, setDriveToken } from './api'

function GoogleG() {
  return (
    <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
      <path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9 3.6l6.7-6.7C35.9 2.6 30.4 0 24 0 14.6 0 6.5 5.4 2.6 13.2l7.8 6.1C12.3 13.2 17.6 9.5 24 9.5z" />
      <path fill="#4285F4" d="M46.1 24.6c0-1.6-.1-3.1-.4-4.6H24v9.1h12.4c-.5 2.9-2.1 5.3-4.6 7l7.1 5.5c4.2-3.9 6.2-9.6 6.2-17z" />
      <path fill="#FBBC05" d="M10.4 28.3a14.5 14.5 0 0 1 0-8.6l-7.8-6.1a24 24 0 0 0 0 20.8l7.8-6.1z" />
      <path fill="#34A853" d="M24 48c6.5 0 11.9-2.1 15.9-5.8l-7.1-5.5c-2 1.3-4.5 2.1-8.8 2.1-6.4 0-11.7-3.7-13.6-9.8l-7.8 6.1C6.5 42.6 14.6 48 24 48z" />
    </svg>
  )
}

export default function SignIn({ onSignedIn }) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [clientId, setClientId] = useState(null)  // set => real GIS; null => demo identity

  useEffect(() => { getConfig().then((c) => setClientId(c.google_client_id || null)).catch(() => {}) }, [])

  const finish = async () => onSignedIn(await getMe())

  // Demo mode: the server is already connected to a Google account (baked ADC).
  const demoSignIn = async () => {
    setBusy(true); setErr(null)
    try { await finish() }
    catch (e) { setErr(`sign-in failed — connect a Google account first (${e})`) }
    finally { setBusy(false) }
  }

  // GIS mode: pop the Google consent, get a drive.readonly access token, then resolve
  // identity server-side via that token.
  const gisSignIn = () => {
    setErr(null)
    const oauth2 = window.google?.accounts?.oauth2
    if (!oauth2) { setErr('Google sign-in is still loading — try again in a moment'); return }
    setBusy(true)
    oauth2.initTokenClient({
      client_id: clientId,
      scope: 'https://www.googleapis.com/auth/drive.readonly',
      callback: async (resp) => {
        try {
          if (resp.error || !resp.access_token) throw new Error(resp.error || 'no access token')
          setDriveToken(resp.access_token)
          await finish()
        } catch (e) { setErr(`sign-in failed (${e})`) }
        finally { setBusy(false) }
      },
    }).requestAccessToken()
  }

  return (
    <div className="signin">
      <div className="signin-card">
        <span className="logo big">
          <span className="word">mova</span>
          <span className="io"><span>io</span></span>
        </span>
        <p className="signin-sub">accessibility compliance</p>
        <button className="gbtn" disabled={busy} onClick={clientId ? gisSignIn : demoSignIn}>
          <GoogleG /> {busy ? 'signing in…' : 'Sign in with Google'}
        </button>
        {err && <div className="err">{err}</div>}
        <p className="muted signin-foot">Scans run read-only · your documents are never retained</p>
      </div>
    </div>
  )
}
