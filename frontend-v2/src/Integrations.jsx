import { useState, useCallback, useEffect, useRef } from 'react'
import { getConfig } from './api.js'
import { SIM } from './sim.js'
import { googleUserInfo } from './googleIdentity.js'
import SourceDrawer from './SourceDrawer.jsx'
import FileDrawer from './FileDrawer.jsx'
import FolderPicker from './FolderPicker.jsx'
import ScanScopeWizard from './ScanScopeWizard.jsx'
// Single source of truth for the SharePoint/Graph scopes, so this sign-in path and SharePoint.jsx
// can never request different permissions than IT consented to (read-only; see that module).
import { SP_SCOPES } from './sharepointScopes.js'
import { signInForScopes, MsalNotReady, MsalNotConfigured } from './msalClient.js'
import { friendlyAuthError } from './authErrors.js'

// Azure client/tenant come from /config at runtime now (getSpAuth in sharepointScopes.js), so a
// deployment is pointed at a tenant with an env var and no rebuild; VITE_AZURE_* is the fallback.
const GD_SCOPES = 'https://www.googleapis.com/auth/drive.readonly https://www.googleapis.com/auth/drive.file'

// iOS-style switch for the scan-time options (PII scan, Durable scan).
function ScanSwitch({ on, onToggle, label, title }) {
  return (
    <button type="button" role="switch" aria-checked={on} aria-label={label} onClick={onToggle} title={title}
      style={{ display: 'inline-flex', alignItems: 'center', gap: 9, cursor: 'pointer', font: 'inherit',
               border: '1px solid var(--line)', background: 'var(--surface)', color: 'inherit',
               borderRadius: 999, padding: '5px 13px 5px 7px' }}>
      <span aria-hidden="true" style={{ position: 'relative', width: 36, height: 20, borderRadius: 10,
            background: on ? '#6D28D9' : '#c6c6cf', transition: 'background .15s', flexShrink: 0 }}>
        <span style={{ position: 'absolute', top: 2, left: on ? 18 : 2, width: 16, height: 16, borderRadius: '50%',
              background: '#fff', transition: 'left .15s', boxShadow: '0 1px 2px rgba(0,0,0,.35)' }} />
      </span>
      <span style={{ fontSize: 13, fontWeight: 600, whiteSpace: 'nowrap' }}>{label}</span>
    </button>
  )
}

function GoogleG() {
  return (
    <svg width="15" height="15" viewBox="0 0 48 48" aria-hidden="true" style={{ flexShrink: 0 }}>
      <path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9 3.6l6.7-6.7C35.9 2.6 30.4 0 24 0 14.6 0 6.5 5.4 2.6 13.2l7.8 6.1C12.3 13.2 17.6 9.5 24 9.5z" />
      <path fill="#4285F4" d="M46.1 24.6c0-1.6-.1-3.1-.4-4.6H24v9.1h12.4c-.5 2.9-2.1 5.3-4.6 7l7.1 5.5c4.2-3.9 6.2-9.6 6.2-17z" />
      <path fill="#FBBC05" d="M10.4 28.3a14.5 14.5 0 0 1 0-8.6l-7.8-6.1a24 24 0 0 0 0 20.8l7.8-6.1z" />
      <path fill="#34A853" d="M24 48c6.5 0 11.9-2.1 15.9-5.8l-7.1-5.5c-2 1.3-4.5 2.1-8.8 2.1-6.4 0-11.7-3.7-13.6-9.8l-7.8 6.1C6.5 42.6 14.6 48 24 48z" />
    </svg>
  )
}
function MsLogo() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true" style={{ flexShrink: 0 }}>
      <rect x="2"    y="2"    width="9.2" height="9.2" fill="#F25022" />
      <rect x="12.8" y="2"    width="9.2" height="9.2" fill="#7FBA00" />
      <rect x="2"    y="12.8" width="9.2" height="9.2" fill="#00A4EF" />
      <rect x="12.8" y="12.8" width="9.2" height="9.2" fill="#FFB900" />
    </svg>
  )
}

function DriveMark() {
  return (
    <svg viewBox="0 0 87 78" width="24" height="24" aria-hidden="true">
      <path fill="#0066da" d="m6.6 66.85 3.85 6.65c.8 1.4 1.95 2.5 3.3 3.3l13.75-23.8h-27.5c0 1.55.4 3.1 1.2 4.5z" />
      <path fill="#00ac47" d="m43.65 25-13.75-23.8c-1.35.8-2.5 1.9-3.3 3.3l-25.4 44a9 9 0 0 0-1.2 4.5h27.5z" />
      <path fill="#ea4335" d="m73.55 76.8c1.35-.8 2.5-1.9 3.3-3.3l1.6-2.75 7.65-13.25c.8-1.4 1.2-2.95 1.2-4.5h-27.5l5.85 11.5z" />
      <path fill="#00832d" d="m43.65 25 13.75-23.8c-1.35-.8-2.9-1.2-4.5-1.2h-18.5c-1.6 0-3.15.45-4.5 1.2z" />
      <path fill="#2684fc" d="m59.8 53h-32.3l-13.75 23.8c1.35.8 2.9 1.2 4.5 1.2h50.8c1.6 0 3.15-.45 4.5-1.2z" />
      <path fill="#ffba00" d="m73.4 26.5-12.7-22c-.8-1.4-1.95-2.5-3.3-3.3l-13.75 23.8 16.15 28h27.45c0-1.55-.4-3.1-1.2-4.5z" />
    </svg>
  )
}

const Tile = ({ bg, children }) => (
  <span style={{ width: 40, height: 40, borderRadius: 10, background: bg, display: 'inline-flex',
    alignItems: 'center', justifyContent: 'center', color: '#fff', flex: '0 0 auto' }}>
    {children}
  </span>
)
const G = (d) => (
  <svg viewBox="0 0 24 24" width="21" height="21" fill="none" stroke="#fff" strokeWidth="2"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d={d} />
  </svg>
)

const LOGO = {
  google_drive: <Tile bg="#fff"><DriveMark /></Tile>,
  onedrive: <Tile bg="#0364B8">{G('M7 18a4 4 0 0 1 0-8 5 5 0 0 1 9.6-1.5A3.5 3.5 0 0 1 19 18z')}</Tile>,
  sharepoint: <Tile bg="#036C70"><b style={{ fontSize: 15 }}>S</b></Tile>,
  confluence: <Tile bg="#1868DB"><b style={{ fontSize: 15 }}>C</b></Tile>,
  box: <Tile bg="#0061D5"><b style={{ fontSize: 12 }}>box</b></Tile>,
  web: <Tile bg="#5F6B7A">{G('M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18M3 12h18M12 3c2.5 2.5 2.5 15.5 0 18M12 3c-2.5 2.5-2.5 15.5 0 18')}</Tile>,
}

// Always-present connectable sources — shown in connect or scan state
const CONNECTABLE = [
  { id: '_gdrive', type: 'google_drive', name: 'Google Drive' },
  { id: 'sp-root', type: 'onedrive',     name: 'OneDrive'     },
]

const FUTURE = [
  { name: 'SharePoint',  logo: <Tile bg="#036C70"><b style={{ fontSize: 15 }}>S</b></Tile> },
  { name: 'File Shares', logo: <Tile bg="#E8A400">{G('M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z')}</Tile> },
  { name: 'S3 / Blob',   logo: <Tile bg="#2E72C9"><b style={{ fontSize: 12 }}>S3</b></Tile> },
]

// Most-recent completed scan for a source, formatted like "Jun 26, 7:55 AM".
// Maps the connector type to the scan_runs.source value.
function lastScanLabel(scans, type) {
  const src = type === 'google_drive' ? 'drive' : type === 'onedrive' ? 'sharepoint' : null
  if (!src) return null
  let latest = null
  for (const s of scans || []) {
    if (s.source === src && s.completed_at && (!latest || s.completed_at > latest)) latest = s.completed_at
  }
  if (!latest) return null
  const d = new Date(latest)
  if (isNaN(d.getTime())) return null
  return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
}

// Most-recent completed scan RUN object for a source (not just its date) — used for the
// truthful "N in last scan" count line, which reads the run's post-filter `files`.
function lastCompletedRun(scans, type) {
  const src = type === 'google_drive' ? 'drive' : type === 'onedrive' ? 'sharepoint' : null
  if (!src) return null
  let latest = null
  for (const s of scans || []) {
    if (s.source === src && s.completed_at && (!latest || s.completed_at > latest.completed_at)) latest = s
  }
  return latest
}

// Per-source health: this source's own recent scan history (up to its last 5 completed
// scans) — error rate (files the engine couldn't open/parse) + avg compliance score.
// A source with a rising error rate usually means a connector/permissions problem, not
// a document problem — worth surfacing separately from the per-file "could not open" flags.
function sourceHealth(scans, type) {
  const src = type === 'google_drive' ? 'drive' : type === 'onedrive' ? 'sharepoint' : null
  if (!src) return null
  const recent = (scans || [])
    .filter((s) => s.source === src && s.completed_at)
    .sort((a, b) => (b.completed_at > a.completed_at ? 1 : -1))
    .slice(0, 5)
  if (!recent.length) return null
  const totalFiles = recent.reduce((a, s) => a + (s.files || 0), 0)
  const totalErr = recent.reduce((a, s) => a + (s.error || 0), 0)
  const scored = recent.filter((s) => s.avg_score != null)
  const avgScore = scored.length ? Math.round(scored.reduce((a, s) => a + s.avg_score, 0) / scored.length) : null
  const errRate = totalFiles ? totalErr / totalFiles : 0
  const status = errRate >= 0.15 ? 'unhealthy' : errRate > 0 ? 'degraded' : 'healthy'
  return { status, errRate, totalErr, totalFiles, avgScore, scansCounted: recent.length }
}

// ── Main component ─────────────────────────────────────────────────────────────

export default function Integrations({ sources, files = [], scans = [], onScan, busy, hasDriveToken, hasSPToken, onConnect,
                                       deepScan = true, setDeepScan, queuedScan = false, setQueuedScan,
                                       excludeRemediated = true, setExcludeRemediated,
                                       incremental = true, setIncremental, scanId = null }) {
  const [selSrc,      setSelSrc]      = useState(null)
  const [selFile,     setSelFile]     = useState(null)
  const [pickerSrc,   setPickerSrc]   = useState(null)
  const [gdConnecting, setGdConnecting] = useState(false)
  const [gdError,      setGdError]      = useState('')
  const [spConnecting, setSpConnecting] = useState(false)
  const [spError,      setSpError]      = useState('')
  const [googleClientId, setGoogleClientId] = useState('')
  const [scanModalOpen, setScanModalOpen] = useState(false)
  // Which connected sources the review modal opened against (page-level "New scan" → all connected;
  // a card's "New scan" → just that one), and which of them are ticked inside the modal.
  const [modalTargets, setModalTargets] = useState([])
  const [pickedIds,    setPickedIds]    = useState([])
  const availRef = useRef(null)
  const gdTokenClientRef = useRef(null)

  useEffect(() => {
    getConfig().then((c) => { if (c?.google_client_id) setGoogleClientId(c.google_client_id) }).catch(() => {})
  }, [])

  const driveBackend   = sources.find((s) => s.type === 'google_drive')

  // ── OAuth connect ────────────────────────────────────────────────────────────

  const connectGoogle = () => {
    if (!googleClientId) { setGdError('Google client ID not configured — set ACP_GOOGLE_CLIENT_ID at deploy time.'); return }
    if (!window.google?.accounts?.oauth2) { setGdError('Google Identity Services not loaded yet — try again.'); return }
    setGdConnecting(true); setGdError('')
    gdTokenClientRef.current = null  // reset so we pick up any client_id change
    if (!gdTokenClientRef.current) {
      gdTokenClientRef.current = window.google.accounts.oauth2.initTokenClient({
        client_id: googleClientId,
        scope: GD_SCOPES + ' https://www.googleapis.com/auth/userinfo.profile email',
        callback: async (resp) => {
          if (resp.error) { setGdConnecting(false); setGdError(resp.error_description || resp.error); return }
          try {
            // `.catch(() => ({}))` here meant a failed lookup connected the account as '' — an
            // empty tenant key, which is not a smaller version of the right answer.
            const me = await googleUserInfo(resp.access_token)
            onConnect('google', me.email, resp.access_token)
          } catch (e) {
            setGdError(e?.message || 'Connected to Google, but could not read the account email.')
          }
          setGdConnecting(false)
        },
      })
    }
    gdTokenClientRef.current.requestAccessToken()
  }

  const connectMicrosoft = async () => {
    setSpConnecting(true); setSpError('')
    try {
      // Shared, resilient MSAL client (msalClient.js) — same one the login screen uses, so the two
      // never race over interaction state, and a stuck `interaction_in_progress` lock self-clears.
      const { account, accessToken } = await signInForScopes(SP_SCOPES)
      sessionStorage.setItem('sp_token', accessToken)
      sessionStorage.setItem('sp_account', JSON.stringify(account))
      onConnect('microsoft', account.username || '', accessToken)
    } catch (e) {
      if (e instanceof MsalNotReady) setSpError('MSAL not loaded yet — try again.')
      else if (e instanceof MsalNotConfigured) setSpError('SharePoint sign-in isn’t configured for this deployment.')
      else setSpError(friendlyAuthError(e))
    } finally {
      setSpConnecting(false)
    }
  }

  // ── Scan dispatch ────────────────────────────────────────────────────────────

  const handleScan = (srcId) => {
    if (SIM) { onScan(srcId === '_gdrive' ? 'drive' : srcId); return }
    if (srcId === 'sp-root') { onScan('sharepoint'); return }
    // Drive — open folder picker so user can narrow the scan
    setPickerSrc(driveBackend || { type: 'google_drive', name: 'My Drive', id: 'root' })
  }

  const handlePickerScan = (folder) => {
    setPickerSrc(null)
    onScan('drive', folder)
  }

  const canScanAll = SIM || hasDriveToken || hasSPToken

  // The connected connectable sources (Drive / OneDrive) — the ones a scan can actually run against.
  const connectedSources = CONNECTABLE.filter((s) => (s.type === 'google_drive' ? hasDriveToken : hasSPToken))
    .map((s) => (s.type === 'google_drive' && hasDriveToken ? (driveBackend || s) : s))

  // The scan dispatch the "Scan all sources" button used to run inline. It now runs only after the
  // scope wizard's "Start scan" confirms scope — so every scan from here has a confirmed scope.
  const runTheScan = () => {
    if (SIM) { onScan('all'); return }
    if (hasDriveToken) { handleScan('_gdrive'); return }
    if (hasSPToken)    { onScan('sharepoint'); return }
  }

  // Open the single gated review modal. `targets` are the connected sources it offers; every one is
  // ticked by default. Both the page-level "New scan" and each card's "New scan" route through here.
  const openScanModal = (targets) => {
    const list = targets && targets.length ? targets : connectedSources
    setModalTargets(list)
    setPickedIds(list.map((s) => s.id))
    setScanModalOpen(true)
  }

  // The modal's confirm. Uses the chosen source: one source → the per-source dispatch (Drive still
  // opens its folder picker); >1 or none → the "scan everything connected" path. Reuses handleScan /
  // runTheScan so the OAuth/SIM branches stay in one place.
  const runChosenScan = () => {
    const chosen = modalTargets.filter((s) => pickedIds.includes(s.id))
    if (chosen.length === 1) {
      const t = chosen[0]
      if (SIM) { onScan(t.type === 'google_drive' ? 'drive' : 'sharepoint'); return }
      handleScan(t.id)
      return
    }
    runTheScan()
  }

  // The connected sources the modal is currently offering, filtered to the ticked ones.
  const chosenSources = modalTargets.filter((s) => pickedIds.includes(s.id))
  const estCount = (chosenSources.length ? chosenSources : connectedSources)
    .reduce((a, s) => a + (s.files || 0), 0)
  const estWhere = chosenSources.length === 1
    ? (chosenSources[0].type === 'google_drive' ? 'Google Drive' : 'OneDrive')
    : `${(chosenSources.length || connectedSources.length)} sources`

  // One dominant health state per source — never more than one badge (see plan §4).
  const healthState = (h) => {
    if (!h) return { key: 'none', label: 'Not yet scanned' }
    if (h.status === 'healthy') return { key: 'ok', label: 'Healthy' }
    return { key: 'attn', label: 'Needs attention',
      sub: `${h.totalErr} file${h.totalErr !== 1 ? 's' : ''} couldn’t be accessed in recent scans` }
  }
  const HEALTH_STATE = {
    ok:   ['#3B6D11', '#E7F0DC'],
    attn: ['#A32D2D', '#FCEBEB'],
    none: ['var(--muted)', 'var(--line)'],
  }

  return (
    <>
      {/* ── Page header ─────────────────────────────────────────────────────── */}
      <div className="estatebar">
        <div>
          <b style={{ fontSize: 20 }}>Content Sources</b>
          <div className="muted" style={{ marginTop: 4 }}>
            Manage the locations ACP scans and monitors.
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <button type="button" className="ghost small"
                  onClick={() => availRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })}>
            + Connect source
          </button>
          <button disabled={busy || !canScanAll} onClick={() => openScanModal(connectedSources)}>
            {busy ? 'scanning…' : 'New scan'}
          </button>
        </div>
      </div>

      {/* ── Connected sources — one status card each ────────────────────────── */}
      {connectedSources.length > 0 && (
        <section style={{ marginBottom: 24 }}>
          <div className="intsec-head muted">CONNECTED SOURCES ({connectedSources.length})</div>
          <div className="intsources">
            {connectedSources.map((src) => {
              const isGdrive  = src.type === 'google_drive'
              const typeLabel = isGdrive ? 'Google Drive' : 'OneDrive'
              const title     = src.name && src.name !== typeLabel ? `${typeLabel} — ${src.name}` : typeLabel
              const store     = isGdrive ? 'Drive' : 'OneDrive'
              const lastRun   = lastCompletedRun(scans, src.type)
              const lastScan  = lastScanLabel(scans, src.type)
              const health    = healthState(sourceHealth(scans, src.type))
              const [hfg, hbg] = HEALTH_STATE[health.key]
              const err       = isGdrive ? gdError : spError
              return (
                <div className="srccard srccard--on" key={src.id}>
                  <div className="srccard-logo" aria-hidden="true">{LOGO[src.type] || LOGO.web}</div>

                  <div className="srccard-body">
                    <div className="srccard-name">{title}</div>
                    <div className="srccard-meta">
                      {src.user && <span>{src.user}</span>}
                      {src.folder && <span>folder: {src.folder}</span>}
                      <span className="srccard-count">
                        {src.files != null ? `${src.files.toLocaleString()} in ${store}` : `— in ${store}`}
                        {lastRun && lastRun.files != null && ` · ${lastRun.files.toLocaleString()} in last scan`}
                      </span>
                      <span>{lastScan ? `Last scanned ${lastScan}` : 'Not yet scanned'}</span>
                    </div>
                    <div style={{ marginTop: 6 }}>
                      <span className="srccard-health" style={{ background: hbg, color: hfg }}>{health.label}</span>
                      {health.sub && <div className="srccard-health-sub muted">{health.sub}</div>}
                    </div>
                    <details className="srccard-conn">
                      <summary>Connection details</summary>
                      <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
                        <span className="pulsedot" aria-hidden="true" /> Connected · read-only access
                      </div>
                    </details>
                    {err && <div className="srccard-err">{err}</div>}
                  </div>

                  <div className="srccard-actions">
                    <button disabled={busy} onClick={() => openScanModal([src])}>
                      {busy ? 'Scanning…' : 'New scan'}
                    </button>
                    <button className="ghost small" onClick={() => setSelSrc(src)}>Manage</button>
                    <details className="srccard-ovf">
                      <summary aria-label="More actions" title="More actions">⋯</summary>
                      <div className="srccard-ovf-menu">
                        <button type="button" onClick={() => setSelSrc(src)}>View files</button>
                        <button type="button" onClick={() => setSelSrc(src)}>Details</button>
                      </div>
                    </details>
                  </div>
                </div>
              )
            })}
          </div>
        </section>
      )}

      {/* ── Available sources — connectable, not yet connected ──────────────── */}
      <section ref={availRef}>
        <div className="intsec-head muted">AVAILABLE SOURCES</div>
        <div className="intsources">
          {CONNECTABLE.filter((s) => !(s.type === 'google_drive' ? hasDriveToken : hasSPToken)).map((s) => {
            const isGdrive     = s.type === 'google_drive'
            const isConnecting = isGdrive ? gdConnecting : spConnecting
            const error        = isGdrive ? gdError : spError
            const desc         = isGdrive
              ? 'Scan Google Drive files for WCAG accessibility issues'
              : 'Scan OneDrive & SharePoint for accessibility issues'
            return (
              <div className="srccard" key={s.id}>
                <div className="srccard-logo" aria-hidden="true">{LOGO[s.type] || LOGO.web}</div>
                <div className="srccard-body">
                  <div className="srccard-name">{s.name}</div>
                  <div className="srccard-desc">{desc}</div>
                  {error && <div className="srccard-err">{error}</div>}
                </div>
                <div className="srccard-actions">
                  <button className="srccard-connect" disabled={isConnecting}
                          onClick={isGdrive ? connectGoogle : connectMicrosoft}>
                    {isConnecting
                      ? 'Connecting…'
                      : isGdrive
                        ? <><GoogleG /> Connect Google Drive</>
                        : <><MsLogo /> Connect Microsoft</>}
                  </button>
                </div>
              </div>
            )
          })}
        </div>
        {/* The far-future connectors — a compact muted line, not big disabled cards. */}
        <div className="intsoon-line muted">
          More sources coming soon: {FUTURE.map((f) => f.name).join(' · ')}
        </div>
      </section>

      {/* ── The single gated "New scan" review modal ────────────────────────── */}
      {scanModalOpen && (
        <div role="dialog" aria-modal="true" aria-label="New scan"
             onClick={() => setScanModalOpen(false)}
             style={{ position: 'fixed', inset: 0, zIndex: 1000, background: 'rgba(0,0,0,.45)',
                      display: 'flex', alignItems: 'flex-start', justifyContent: 'center', padding: '6vh 16px' }}>
          <div onClick={(e) => e.stopPropagation()}
               style={{ background: 'var(--surface, #fff)', color: 'inherit', borderRadius: 12,
                        width: 'min(620px, 100%)', maxHeight: '88vh', overflowY: 'auto',
                        boxShadow: '0 12px 40px rgba(0,0,0,.3)', padding: '16px 18px' }}>
            <div style={{ display: 'flex', alignItems: 'center', marginBottom: 8 }}>
              <h3 style={{ margin: 0, fontSize: 16 }}>New scan</h3>
              <button className="ghost small" aria-label="Close" onClick={() => setScanModalOpen(false)}
                      style={{ marginLeft: 'auto' }}>×</button>
            </div>

            {/* 1. Sources included */}
            <div className="scanmodal-sec">
              <div className="scanmodal-head">Sources included</div>
              {modalTargets.length === 0 ? (
                <div className="muted" style={{ fontSize: 13 }}>All connected sources will be scanned.</div>
              ) : modalTargets.length === 1 ? (
                <div style={{ fontSize: 13, display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span className="pulsedot" aria-hidden="true" />
                  {modalTargets[0].type === 'google_drive' ? 'Google Drive' : 'OneDrive'}
                  {modalTargets[0].user ? ` — ${modalTargets[0].user}` : ''}
                </div>
              ) : (
                modalTargets.map((s) => (
                  <label key={s.id} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, margin: '4px 0' }}>
                    <input type="checkbox" checked={pickedIds.includes(s.id)}
                           onChange={(e) => setPickedIds((ids) => e.target.checked
                             ? [...ids, s.id] : ids.filter((x) => x !== s.id))} />
                    {s.type === 'google_drive' ? 'Google Drive' : 'OneDrive'}{s.user ? ` — ${s.user}` : ''}
                  </label>
                ))
              )}
            </div>

            {/* 2. Scan behavior — the four toggles moved out of the toolbar */}
            <div className="scanmodal-sec">
              <div className="scanmodal-head">Scan behavior</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                {setDeepScan && (
                  <ScanSwitch on={deepScan} onToggle={() => setDeepScan(v => !v)} label="PII scan"
                    title={deepScan
                      ? 'PII scan also looks for sensitive data (SSNs, credit cards, emails) in your documents — a bit slower on large PDF sets. Turn off for a fast, accessibility-only scan.'
                      : 'Off — Fast scan (accessibility only). Turn on to also detect sensitive data (PII).'} />
                )}
                {setQueuedScan && (
                  <ScanSwitch on={queuedScan} onToggle={() => setQueuedScan(v => !v)} label="Durable scan"
                    title={queuedScan
                      ? 'Durable scan — runs in the background queue: keeps going if you close the tab AND survives server restarts, with parallel downloads for large libraries (recommended). Turn off for a quick one-off scan in this browser session.'
                      : 'Off — Quick scan in this browser session: starts instantly, streams live per-file progress, best for spot-checking a few files. Turn on for a durable background scan that survives restarts and handles very large libraries.'} />
                )}
                {setExcludeRemediated && (
                  <ScanSwitch on={excludeRemediated} onToggle={() => setExcludeRemediated(v => !v)} label="Skip Remediated/"
                    title={excludeRemediated
                      ? 'On — skips the Remediated/ folder ACP writes fixed copies to, so they don’t get re-discovered and flagged as new documents needing attention. Turn off to also audit that folder.'
                      : 'Off — the Remediated/ folder (ACP’s own output) is scanned like any other folder. Turn on to skip it and avoid a re-discovery feedback loop.'} />
                )}
                {setIncremental && (
                  <ScanSwitch on={incremental} onToggle={() => setIncremental(v => !v)} label="Incremental scan"
                    title={incremental
                      ? 'On — a file byte-identical to one already scored under the current rubric is copied forward instead of re-analysed (ADR 0011). Turn off to force a fresh re-analysis of every file (e.g. after a manual rubric edit, or if you don’t trust the cache).'
                      : 'Off — Fresh scan: every file is re-downloaded and re-analysed, even ones that haven’t changed. Turn on for the normal, much faster incremental behavior.'} />
                )}
              </div>
            </div>

            {/* 3. Formats & WCAG criteria + estimate + the confirm/cancel footer */}
            <div className="scanmodal-sec">
              <div className="scanmodal-head">Formats &amp; WCAG criteria</div>
              <div className="scanmodal-est muted">
                ~{estCount.toLocaleString()} documents in {estWhere}
                <span style={{ display: 'block', fontSize: 11 }}>
                  Discovered count — the actual scanned total may be lower after dedup, scope and unsupported-type filtering.
                </span>
              </div>
              <ScanScopeWizard showStartButton
                onStartScan={(o) => { setScanModalOpen(false); if (!o?.cancel) runChosenScan() }} />
            </div>
          </div>
        </div>
      )}

      {pickerSrc && !busy && (
        <FolderPicker onScan={handlePickerScan} onClose={() => setPickerSrc(null)} />
      )}

      {selSrc  && <SourceDrawer source={selSrc}  files={files.filter((f) => f.source === selSrc.id)}
                                onClose={() => setSelSrc(null)}  onPickFile={setSelFile} />}
      {selFile && <FileDrawer   file={selFile}   onClose={() => setSelFile(null)} scanId={scanId} />}
    </>
  )
}
