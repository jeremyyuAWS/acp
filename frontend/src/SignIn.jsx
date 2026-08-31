import { useEffect, useState } from 'react'
import { getConfig, setLangfuseBase } from './api.js'
import { PERSONAS } from './sim.js'
import Logo from './Logo.jsx'
import { googleUserInfo } from './googleIdentity.js'
import { SP_SCOPES } from './sharepointScopes.js'
import { signInForScopes, MsalNotReady, MsalNotConfigured } from './msalClient.js'
import { friendlyAuthError } from './authErrors.js'

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
  // Prefer the full git-derived CalVer (with the daily .N counter) from /config, which
  // is public pre-auth; the date-only __BUILD_VERSION__ bundle tag is the instant fallback.
  const [ver, setVer] = useState(typeof __BUILD_VERSION__ !== 'undefined' ? __BUILD_VERSION__ : null)
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 60_000)
    getConfig().then((c) => { if (c?.version) setVer(c.version) }).catch(() => { /* keep fallback */ })
    return () => clearInterval(id)
  }, [])
  const iso = typeof __BUILD_TIME__ !== 'undefined' ? __BUILD_TIME__ : null
  if (!ver && !iso) return null
  const stamp = iso ? new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit', timeZoneName: 'short' }) : null
  // The version's date + ordinal are stamped in Pacific time (deploy.sh BUILD_TZ), while `stamp`
  // renders the build instant in the VIEWER's zone. They agree for a Pacific viewer — the team
  // and the customer — and the "PT" tag explains the disagreement for anyone else. It used to say
  // UTC, which made an 8:06 PM PDT build read "v2026.7.10.11 UTC · Jul 9, 2026, 8:06 PM PDT".
  return (
    <p style={{ margin: '10px 0 0', fontSize: 11, color: '#b0a8b4', textAlign: 'center', letterSpacing: 0.2 }}
       title={stamp ? `Version dated in Pacific time · built ${stamp} (your local time)` : undefined}>
      {ver && <span>v{ver}<span style={{ opacity: 0.7 }}>{' '}PT</span></span>}
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

function MsLogo() {
  return (
    <svg width="18" height="18" viewBox="0 0 21 21" aria-hidden="true">
      <rect x="1"  y="1"  width="9" height="9" fill="#f25022" />
      <rect x="11" y="1"  width="9" height="9" fill="#7fba00" />
      <rect x="1"  y="11" width="9" height="9" fill="#00a4ef" />
      <rect x="11" y="11" width="9" height="9" fill="#ffb900" />
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

// `notice` explains why this screen appeared. On a first visit it is null and nothing renders.
// After a 401 it carries the reason, because a user dropped back to sign-in mid-review with no
// explanation cannot tell an expired token from an app that lost their work.
export default function SignIn({ onSignedIn, notice = null }) {
  const [cfg, setCfg] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const isStaging = window.location.hostname.includes('staging')

  useEffect(() => {
    getConfig().then((c) => { setCfg(c); setLangfuseBase(c?.langfuse_trace_base) }).catch(() => setCfg({ auth: 'demo' }))
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
          // Throws on a non-ok response or a payload with no email, which is what makes the
          // catch below reachable. It was already written and already correct; nothing ever
          // threw, so a failed lookup signed the user in with `id: undefined` instead.
          const me = await googleUserInfo(resp.access_token)
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
        } catch (e) {
          // Google's own reason, not a generic retry prompt: an expired token and a missing
          // profile scope need different actions from the person reading this.
          setErr(e?.message || 'Could not retrieve your Google profile — please try again.')
        }
      },
    })
    // ASK FOR THE CHOOSER. Without an explicit prompt, a browser with one signed-in Google
    // session goes straight through on that account — which is correct for a refresh and wrong
    // for a sign-in, because it is the one moment the user is choosing WHO to be. It also made
    // "use my other Google account with my work Microsoft account" impossible without a second
    // Chrome profile.
    //
    // Only at SIGN-IN. driveAuth.refreshDriveToken deliberately keeps `prompt: ''` — a token
    // refresh mid-scan must never put a chooser in front of someone, and re-picking an account
    // there would swap the Drive under a running scan.
    client.requestAccessToken({ prompt: 'select_account' })
  }

  // Sign in with Microsoft (Entra) — mirrors the Google button, and additionally captures a
  // SharePoint/OneDrive delegated token so the connected source is ready the moment the user is in.
  // The account signed in here becomes the ACP identity, so it must be on the allowlist (or an
  // allowed domain) exactly like a Google sign-in.
  const signInWithMicrosoft = async () => {
    setBusy(true); setErr('')
    try {
      // One shared, resilient MSAL client (msalClient.js): single instance, and it self-clears a
      // stuck `interaction_in_progress` lock so a fumbled popup doesn't wedge every later attempt.
      const { account, accessToken } = await signInForScopes(SP_SCOPES)
      sessionStorage.setItem('sp_token', accessToken)
      sessionStorage.setItem('sp_account', JSON.stringify(account))
      const email = account.username || ''
      onSignedIn({
        id: email, name: account.name || email, email,
        // The delegated token doubles as the ACP API bearer (App.jsx routes it to setMsToken by
        // sso), so the backend can authenticate this Microsoft user — without it every call 401s.
        token: accessToken,
        role: 'Compliance Officer', sso: 'Microsoft',
        scope: { label: 'Full estate · all departments', departments: 'all' },
        allow: ['overview', 'integrations', 'discover', 'assess', 'remediate', 'publish', 'monitor', 'settings', 'upload'],
      })
    } catch (e) {
      if (e instanceof MsalNotReady) setErr('Microsoft sign-in isn’t ready yet — please refresh.')
      else if (e instanceof MsalNotConfigured) setErr('SharePoint sign-in isn’t configured for this deployment.')
      else setErr(friendlyAuthError(e))
    } finally {
      setBusy(false)
    }
  }

  if (!cfg) {
    return (
      <div className="signin">
        <div className="signin-card wide">
          {isStaging && (
            <div style={{ margin: '-24px -28px 20px', padding: '14px 0 10px',
                          background: '#B45309', textAlign: 'center', borderRadius: '8px 8px 0 0' }}>
              <div style={{ fontSize: 22, fontWeight: 800, letterSpacing: '0.12em',
                            textTransform: 'uppercase', color: '#fff', lineHeight: 1 }}>
                Staging
              </div>
              <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.75)', marginTop: 3 }}>
                not production
              </div>
            </div>
          )}
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
          {isStaging && (
            <div style={{ margin: '-24px -28px 20px', padding: '14px 0 10px',
                          background: '#B45309', textAlign: 'center', borderRadius: '8px 8px 0 0' }}>
              <div style={{ fontSize: 22, fontWeight: 800, letterSpacing: '0.12em',
                            textTransform: 'uppercase', color: '#fff', lineHeight: 1 }}>
                Staging
              </div>
              <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.75)', marginTop: 3 }}>
                not production
              </div>
            </div>
          )}
          <Logo big />
          <p className="signin-sub">Accessibility Platform</p>
          {notice && (
            <p role="status" aria-live="polite" className="signin-notice"
               style={{ fontSize: 13, margin: '10px 0 0', padding: '10px 12px', borderRadius: 8,
                        background: '#FFF4E5', color: '#7A4A00', border: '1px solid #F0C77E' }}>
              {notice}
            </p>
          )}
          {err && <p role="alert" style={{ color: 'var(--red, #dc2626)', fontSize: 13, margin: '8px 0 0' }}>{err}</p>}
          <div className="ssorow" style={{ marginTop: 24 }}>
            <button className="ssobtn google-sso" onClick={signInWithGoogle} disabled={busy}>
              <GoogleIcon />
              {busy ? 'Signing in…' : 'Sign in with Google'}
            </button>
            {(cfg.azure_client_id || import.meta.env.VITE_AZURE_CLIENT_ID) && (
              <button className="ssobtn ms-sso" onClick={signInWithMicrosoft} disabled={busy}>
                <MsLogo />
                {busy ? 'Signing in…' : 'Sign in with Microsoft'}
              </button>
            )}
          </div>
          <p className="muted signin-foot" style={{ marginTop: 20 }}>
            Authorized accounts only · Discovery reads metadata only
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
        {isStaging && (
          <div style={{ marginBottom: 8, display: 'flex', justifyContent: 'center' }}>
            <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.08em',
                           textTransform: 'uppercase', padding: '3px 10px', borderRadius: 20,
                           background: '#FFF4E5', color: '#B45309', border: '1px solid #F0C77E' }}>
              Staging
            </span>
          </div>
        )}
        <Logo big />
        <p className="signin-sub">Accessibility Platform</p>
        {notice && (
          <p role="status" aria-live="polite" className="signin-notice"
             style={{ fontSize: 13, margin: '10px 0 0', padding: '10px 12px', borderRadius: 8,
                      background: '#FFF4E5', color: '#7A4A00', border: '1px solid #F0C77E' }}>
            {notice}
          </p>
        )}

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

        <p className="muted signin-foot">SSO &amp; role-based access · Review recommendations before applying changes</p>
        <BuildStamp />
      </div>
    </div>
  )
}
