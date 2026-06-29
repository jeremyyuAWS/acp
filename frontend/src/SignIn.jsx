import { useEffect, useState } from 'react'
import { getConfig } from './api.js'
import { PERSONAS } from './sim.js'
import Logo from './Logo.jsx'

const initials = (n) => n.split(' ').map((x) => x[0]).join('').slice(0, 2)

function timeAgoShort(iso) {
  if (!iso) return null
  const secs = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (secs < 60) return 'just now'
  const mins = Math.floor(secs / 60)
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.floor(hrs / 24)
  return `${days}d ago`
}

function BuildStamp() {
  const [, setTick] = useState(0)
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 60_000)
    return () => clearInterval(id)
  }, [])
  const iso = typeof __BUILD_TIME__ !== 'undefined' ? __BUILD_TIME__ : null
  const ver = typeof __BUILD_VERSION__ !== 'undefined' ? __BUILD_VERSION__ : null
  if (!ver && !iso) return null
  const stamp = iso ? new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit' }) : null
  return (
    <p style={{ margin: '10px 0 0', fontSize: 11, color: '#b0a8b4', textAlign: 'center', letterSpacing: 0.2 }}
       title={stamp ? `Built ${stamp}` : undefined}>
      {ver && <span>v{ver}</span>}
      {ver && iso && <span style={{ margin: '0 5px' }}>·</span>}
      {iso && <span>{stamp}</span>}
      {iso && <span style={{ margin: '0 5px' }}>·</span>}
      {iso && <span>{timeAgoShort(iso)}</span>}
    </p>
  )
}

function GoogleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
      <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
      <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
      <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l3.66-2.84z"/>
      <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
    </svg>
  )
}

function LockIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
         strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
      <path d="M7 11V7a5 5 0 0 1 10 0v4" />
    </svg>
  )
}

export default function SignIn({ onSignedIn }) {
  const [cfg, setCfg] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  useEffect(() => {
    getConfig().then(setCfg).catch(() => setCfg({ auth: 'demo' }))
  }, [])

  const signInWithGoogle = () => {
    if (!window.google?.accounts?.oauth2) {
      setErr('Google Identity Services not loaded — please refresh.')
      return
    }
    setBusy(true)
    setErr('')
    const client = window.google.accounts.oauth2.initTokenClient({
      client_id: cfg.google_client_id,
      scope: 'email profile https://www.googleapis.com/auth/drive.readonly https://www.googleapis.com/auth/drive.file',
      callback: async (resp) => {
        setBusy(false)
        if (resp.error) { setErr(resp.error_description || resp.error); return }
        try {
          const me = await fetch('https://www.googleapis.com/oauth2/v2/userinfo', {
            headers: { Authorization: 'Bearer ' + resp.access_token },
          }).then((r) => r.json())
          onSignedIn({
            id: me.email,
            name: me.name || me.email,
            email: me.email,
            photo: me.picture,
            token: resp.access_token,
            role: 'Compliance Officer',
            sso: 'Google',
            scope: { label: 'Full estate · all departments', departments: 'all' },
            allow: ['overview', 'integrations', 'discover', 'assess', 'remediate', 'publish', 'monitor', 'settings', 'upload'],
          })
        } catch {
          setErr('Could not retrieve your Google profile — please try again.')
        }
      },
    })
    client.requestAccessToken()
  }

  if (!cfg) {
    return (
      <div className="signin">
        <div className="signin-card wide">
          <Logo big />
          <p className="signin-sub">Loading…</p>
        </div>
      </div>
    )
  }

  if (cfg.auth === 'gis') {
    return (
      <div className="signin">
        <div className="signin-card wide">
          <Logo big />
          <p className="signin-sub">Accessibility Platform</p>
          {err && <p style={{ color: 'var(--red, #dc2626)', fontSize: 13, margin: '8px 0 0' }}>{err}</p>}
          <div className="ssorow" style={{ marginTop: 24 }}>
            <button className="ssobtn google-sso" onClick={signInWithGoogle} disabled={busy}>
              <GoogleIcon />
              {busy ? 'Signing in…' : 'Sign in with Google'}
            </button>
          </div>
          <p className="muted signin-foot" style={{ marginTop: 20 }}>
            Authorized accounts only · documents never retained
          </p>
          <BuildStamp />
        </div>
      </div>
    )
  }

  // Demo mode — persona picker
  const def = PERSONAS.find((p) => p.id === 'compliance') || PERSONAS[0]
  return (
    <div className="signin">
      <div className="signin-card wide">
        <Logo big />
        <p className="signin-sub">Accessibility Platform</p>

        <div className="ssorow">
          <button className="ssobtn" onClick={() => onSignedIn(def)}>
            <LockIcon /> Sign in with SSO
          </button>
        </div>

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
        <BuildStamp />
      </div>
    </div>
  )
}
