import { PERSONAS } from './sim.js'
import Logo from './Logo.jsx'

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
  const def = PERSONAS[0]
  return (
    <div className="signin">
      <div className="signin-card wide">
        <Logo big />
        <p className="signin-sub"><b style={{ color: 'var(--ink)', fontWeight: 600 }}>Aria</b> · accessibility compliance</p>

        <div className="ssorow">
          {SSO.map((s) => (
            <button key={s.name} className="ssobtn" onClick={() => onSignedIn(def)}>{s.icon} Sign in with {s.name}</button>
          ))}
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
      </div>
    </div>
  )
}
