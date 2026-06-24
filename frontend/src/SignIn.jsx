import { useState, useRef } from 'react'
import { PERSONAS } from './sim.js'
import Logo from './Logo.jsx'

const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID || ''
const AZURE_CLIENT_ID  = import.meta.env.VITE_AZURE_CLIENT_ID  || ''
const AZURE_TENANT     = import.meta.env.VITE_AZURE_TENANT_ID  || 'common'
const GD_SCOPES = 'https://www.googleapis.com/auth/drive.readonly https://www.googleapis.com/auth/drive.file'
const SP_SCOPES = ['Files.Read', 'Files.ReadWrite', 'User.Read']

function GoogleG() {
  return (
    <svg width="17" height="17" viewBox="0 0 48 48" aria-hidden="true">
      <path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9 3.6l6.7-6.7C35.9 2.6 30.4 0 24 0 14.6 0 6.5 5.4 2.6 13.2l7.8 6.1C12.3 13.2 17.6 9.5 24 9.5z" />
      <path fill="#4285F4" d="M46.1 24.6c0-1.6-.1-3.1-.4-4.6H24v9.1h12.4c-.5 2.9-2.1 5.3-4.6 7l7.1 5.5c4.2-3.9 6.2-9.6 6.2-17z" />
      <path fill="#FBBC05" d="M10.4 28.3a14.5 14.5 0 0 1 0-8.6l-7.8-6.1a24 24 0 0 0 0 20.8l7.8-6.1z" />
      <path fill="#34A853" d="M24 48c6.5 0 11.9-2.1 15.9-5.8l-7.1-5.5c-2 1.3-4.5 2.1-8.8 2.1-6.4 0-11.7-3.7-13.6-9.8l-7.8 6.1C6.5 42.6 14.6 48 24 48z" />
    </svg>
  )
}
const MsLogo = () => <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true"><rect x="2" y="2" width="9.2" height="9.2" fill="#F25022" /><rect x="12.8" y="2" width="9.2" height="9.2" fill="#7FBA00" /><rect x="2" y="12.8" width="9.2" height="9.2" fill="#00A4EF" /><rect x="12.8" y="12.8" width="9.2" height="9.2" fill="#FFB900" /></svg>
const OktaLogo = () => <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9" fill="none" stroke="#007DC1" strokeWidth="5.5" /></svg>

const SSO = [{ name: 'Google', icon: <GoogleG /> }, { name: 'Microsoft', icon: <MsLogo /> }, { name: 'Okta', icon: <OktaLogo /> }]
const initials = (n) => n.split(' ').map((x) => x[0]).join('').slice(0, 2)

export default function SignIn({ onSignedIn }) {
  const [gdLoading, setGdLoading] = useState(false)
  const [spLoading, setSpLoading] = useState(false)
  const [gdError,   setGdError]   = useState('')
  const [spError,   setSpError]   = useState('')
  const tokenClientRef = useRef(null)

  const def = PERSONAS.find((p) => p.id === 'compliance') || PERSONAS[0]

  const connectGoogleDrive = () => {
    if (!GOOGLE_CLIENT_ID) { setGdError('Add VITE_GOOGLE_CLIENT_ID to frontend/.env and restart the dev server.'); return }
    if (!window.google?.accounts?.oauth2) { setGdError('Google Identity Services not loaded yet — try again in a moment.'); return }
    setGdLoading(true); setGdError('')
    if (!tokenClientRef.current) {
      tokenClientRef.current = window.google.accounts.oauth2.initTokenClient({
        client_id: GOOGLE_CLIENT_ID,
        scope: GD_SCOPES + ' https://www.googleapis.com/auth/userinfo.profile email',
        callback: async (resp) => {
          if (resp.error) { setGdLoading(false); setGdError(resp.error); return }
          try {
            sessionStorage.setItem('gd_token', resp.access_token)
            const me = await fetch('https://www.googleapis.com/oauth2/v2/userinfo', {
              headers: { Authorization: 'Bearer ' + resp.access_token },
            }).then((r) => r.json()).catch(() => ({}))
            onSignedIn({
              id: 'gdrive-user',
              name: me.name || 'Google User',
              role: 'Document Owner',
              email: me.email || '',
              sso: 'Google',
              scope: { label: 'My Google Drive · personal' },
            })
          } catch { setGdLoading(false); setGdError('Could not fetch Google profile.') }
        },
      })
    }
    tokenClientRef.current.requestAccessToken()
  }

  const connectSharePoint = async () => {
    if (!AZURE_CLIENT_ID) { setSpError('Add VITE_AZURE_CLIENT_ID to frontend/.env and restart the dev server.'); return }
    if (!window.msal) { setSpError('MSAL not loaded yet — try again in a moment.'); return }
    setSpLoading(true); setSpError('')
    try {
      const cfg = {
        auth: { clientId: AZURE_CLIENT_ID, authority: `https://login.microsoftonline.com/${AZURE_TENANT}`, redirectUri: window.location.origin },
        cache: { cacheLocation: 'sessionStorage', storeAuthStateInCookie: false },
      }
      const instance = new window.msal.PublicClientApplication(cfg)
      await instance.initialize()
      const loginResult = await instance.loginPopup({ scopes: SP_SCOPES })
      instance.setActiveAccount(loginResult.account)
      const tokenResult = await instance.acquireTokenSilent({ scopes: SP_SCOPES, account: loginResult.account })
        .catch(() => instance.acquireTokenPopup({ scopes: SP_SCOPES }))
      sessionStorage.setItem('sp_token', tokenResult.accessToken)
      sessionStorage.setItem('sp_account', JSON.stringify(loginResult.account))
      onSignedIn({
        id: 'sp-user',
        name: loginResult.account.name || 'Microsoft User',
        role: 'Document Owner',
        email: loginResult.account.username || '',
        sso: 'Microsoft',
        scope: { label: 'My OneDrive · SharePoint' },
      })
    } catch (e) {
      setSpLoading(false)
      setSpError(e.errorCode === 'user_cancelled' ? 'Sign-in cancelled.' : (e.message || 'Connection failed.'))
    }
  }

  return (
    <div className="signin">
      <div className="signin-card wide">
        <Logo big />
        <p className="signin-sub">Accessibility Platform</p>

        <div className="ssorow">
          <button className="ssobtn" onClick={connectGoogleDrive} disabled={gdLoading}>
            <GoogleG /> {gdLoading ? 'Connecting…' : 'Sign in with Google'}
          </button>
          <button className="ssobtn" onClick={connectSharePoint} disabled={spLoading}>
            <MsLogo /> {spLoading ? 'Connecting…' : 'Sign in with Microsoft'}
          </button>
          <button className="ssobtn" onClick={() => onSignedIn(def)}>
            <OktaLogo /> Sign in with Okta
          </button>
        </div>
        {gdError && <p style={{ fontSize: 12, color: '#A32D2D', margin: '-10px 0 6px', textAlign: 'center' }}>{gdError}</p>}
        {spError && <p style={{ fontSize: 12, color: '#A32D2D', margin: '-10px 0 6px', textAlign: 'center' }}>{spError}</p>}

        <div className="signin-or"><span>or explore a role — demo</span></div>

        <div className="personas">
          {PERSONAS.map((p) => (
            <button key={p.id} className="personacard" onClick={() => onSignedIn(p)}>
              <span className="pavatar">{initials(p.name)}</span>
              <span className="pmain">
                <span className="pname">{p.name} <span className="muted prole">· {p.role}</span></span>
                <span className="pscope muted">{p.scope.label}</span>
              </span>
              <span className="psso muted">via {p.sso}</span>
            </button>
          ))}
        </div>

        <p className="muted signin-foot">SSO &amp; role-based access · scans run read-only · documents never retained</p>
      </div>
    </div>
  )
}
