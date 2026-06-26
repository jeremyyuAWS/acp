import { useState, useCallback, useEffect, useRef } from 'react'
import { listFolders, getConfig } from './api.js'
import { SIM } from './sim.js'
import SourceDrawer from './SourceDrawer.jsx'
import FileDrawer from './FileDrawer.jsx'

const AZURE_CLIENT_ID  = import.meta.env.VITE_AZURE_CLIENT_ID  || ''
const AZURE_TENANT     = import.meta.env.VITE_AZURE_TENANT_ID  || 'common'
const GD_SCOPES = 'https://www.googleapis.com/auth/drive.readonly https://www.googleapis.com/auth/drive.file'
const SP_SCOPES = ['Files.Read', 'Files.ReadWrite', 'User.Read']

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

// ── Folder picker modal ────────────────────────────────────────────────────────

function FolderIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
    </svg>
  )
}

function FolderPicker({ onScan, onClose }) {
  const [stack, setStack] = useState([{ id: 'root', name: 'My Drive' }])
  const [folders, setFolders] = useState([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')
  const current = stack[stack.length - 1]

  const load = useCallback((folderId) => {
    setLoading(true); setErr('')
    listFolders(folderId)
      .then((r) => setFolders(r.folders || []))
      .catch((e) => setErr(e.message || 'Failed to load folders'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load(current.id) }, [current.id, load])

  const enter = (folder) => setStack((s) => [...s, folder])
  const goTo  = (idx)    => setStack((s) => s.slice(0, idx + 1))

  return (
    <div className="setoverlay" onClick={onClose}>
      <div className="setpanel" style={{ maxWidth: 480, width: '100%', padding: '24px 28px 28px' }}
           onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Choose a folder to scan">

        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
          <span style={{ fontSize: 15, fontWeight: 650, letterSpacing: '-0.01em' }}>Choose a folder to scan</span>
          <button className="small ghost" onClick={onClose} aria-label="Close"
                  style={{ lineHeight: 1, padding: '4px 8px', fontSize: 16, marginRight: -4 }}>✕</button>
        </div>

        {/* Breadcrumb */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 12, marginBottom: 10,
                      flexWrap: 'wrap', color: 'var(--muted)', paddingBottom: 10,
                      borderBottom: '1px solid var(--line)' }}>
          {stack.map((f, i) => (
            <span key={f.id} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              {i > 0 && <span>›</span>}
              <button style={{ background: 'none', border: 'none', padding: 0, fontSize: 12,
                cursor: i < stack.length - 1 ? 'pointer' : 'default',
                color: i < stack.length - 1 ? 'var(--accent)' : 'var(--ink)',
                fontWeight: i === stack.length - 1 ? 600 : 400 }}
                onClick={() => i < stack.length - 1 && goTo(i)}>
                {f.name}
              </button>
            </span>
          ))}
        </div>

        {/* Folder list */}
        <div style={{ minHeight: 140, maxHeight: 300, overflowY: 'auto',
                      border: '1px solid var(--line)', borderRadius: 10, marginBottom: 20 }}>
          {loading && (
            <div style={{ padding: '32px 0', textAlign: 'center', color: 'var(--muted)', fontSize: 13 }}>
              Loading…
            </div>
          )}
          {err && (
            <div style={{ padding: '20px 18px', display: 'flex', alignItems: 'flex-start', gap: 10 }}>
              <span style={{ fontSize: 18, lineHeight: 1 }}>⚠️</span>
              <div>
                <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--ink)', marginBottom: 4 }}>
                  Could not load folders
                </div>
                <div style={{ fontSize: 12, color: 'var(--muted)' }}>{err}</div>
              </div>
            </div>
          )}
          {!loading && !err && folders.length === 0 && (
            <div style={{ padding: '32px 0', textAlign: 'center', color: 'var(--muted)', fontSize: 13 }}>
              No subfolders here
            </div>
          )}
          {!loading && !err && folders.map((f, idx) => (
            <button key={f.id} style={{ display: 'flex', alignItems: 'center', gap: 10, width: '100%',
              padding: '11px 18px', background: 'none', border: 'none', cursor: 'pointer',
              textAlign: 'left', fontSize: 13,
              borderBottom: idx < folders.length - 1 ? '1px solid var(--line)' : 'none' }}
              onMouseEnter={(e) => e.currentTarget.style.background = 'var(--hover, rgba(0,0,0,.04))'}
              onMouseLeave={(e) => e.currentTarget.style.background = 'none'}
              onClick={() => enter(f)}>
              <FolderIcon />
              <span style={{ flex: 1, color: 'var(--ink)', fontWeight: 500 }}>{f.name}</span>
              <span style={{ color: 'var(--ink)', fontSize: 15 }}>›</span>
            </button>
          ))}
        </div>

        {/* Recursion note */}
        <div style={{ fontSize: 12.5, color: 'var(--ink)', marginBottom: 14,
                      background: '#F1EFF3', border: '1px solid var(--line)', borderRadius: 8,
                      padding: '9px 12px', display: 'flex', alignItems: 'center', gap: 8, lineHeight: 1.4 }}>
          <span aria-hidden="true" style={{ fontSize: 14 }}>↳</span>
          <span>Scans the chosen folder <strong>and everything inside it</strong> — all subfolders, recursively.</span>
        </div>

        {/* Footer */}
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', flexWrap: 'wrap' }}>
          <button className="ghost small" onClick={() => onScan(null)}>Scan all of My Drive</button>
          <button onClick={() => onScan(current.id === 'root' ? null : current.id)}>
            Scan "{current.name}" + subfolders
          </button>
        </div>
      </div>
    </div>
  )
}

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

// ── Main component ─────────────────────────────────────────────────────────────

export default function Integrations({ sources, files = [], scans = [], onScan, busy, hasDriveToken, hasSPToken, onConnect,
                                       deepScan = true, setDeepScan, queuedScan = false, setQueuedScan }) {
  const [selSrc,      setSelSrc]      = useState(null)
  const [selFile,     setSelFile]     = useState(null)
  const [pickerSrc,   setPickerSrc]   = useState(null)
  const [gdConnecting, setGdConnecting] = useState(false)
  const [gdError,      setGdError]      = useState('')
  const [spConnecting, setSpConnecting] = useState(false)
  const [spError,      setSpError]      = useState('')
  const [googleClientId, setGoogleClientId] = useState('')
  const gdTokenClientRef = useRef(null)

  useEffect(() => {
    getConfig().then((c) => { if (c?.google_client_id) setGoogleClientId(c.google_client_id) }).catch(() => {})
  }, [])

  const driveBackend   = sources.find((s) => s.type === 'google_drive')
  const connectedCount = (hasDriveToken ? 1 : 0) + (hasSPToken ? 1 : 0)
  const total          = sources.reduce((a, s) => a + (s.files || 0), 0)

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
            const me = await fetch('https://www.googleapis.com/oauth2/v2/userinfo', {
              headers: { Authorization: 'Bearer ' + resp.access_token },
            }).then((r) => r.json()).catch(() => ({}))
            onConnect('google', me.email || '', resp.access_token)
          } catch { /* onConnect is best-effort */ }
          setGdConnecting(false)
        },
      })
    }
    gdTokenClientRef.current.requestAccessToken()
  }

  const connectMicrosoft = async () => {
    if (!AZURE_CLIENT_ID) { setSpError('VITE_AZURE_CLIENT_ID not set — add it to frontend/.env.'); return }
    if (!window.msal) { setSpError('MSAL not loaded yet — try again.'); return }
    setSpConnecting(true); setSpError('')
    try {
      const cfg = {
        auth: { clientId: AZURE_CLIENT_ID, authority: `https://login.microsoftonline.com/${AZURE_TENANT}`, redirectUri: window.location.origin },
        cache: { cacheLocation: 'sessionStorage', storeAuthStateInCookie: false },
      }
      const instance = new window.msal.PublicClientApplication(cfg)
      await instance.initialize()
      const loginResult  = await instance.loginPopup({ scopes: SP_SCOPES })
      instance.setActiveAccount(loginResult.account)
      const tokenResult  = await instance.acquireTokenSilent({ scopes: SP_SCOPES, account: loginResult.account })
        .catch(() => instance.acquireTokenPopup({ scopes: SP_SCOPES }))
      sessionStorage.setItem('sp_token', tokenResult.accessToken)
      sessionStorage.setItem('sp_account', JSON.stringify(loginResult.account))
      onConnect('microsoft', loginResult.account.username || '', tokenResult.accessToken)
    } catch (e) {
      setSpError(e.errorCode === 'user_cancelled' ? 'Sign-in cancelled.' : (e.message || 'Connection failed.'))
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

  return (
    <>
      <div className="estatebar">
        <div>
          <b>{connectedCount} source{connectedCount !== 1 ? 's' : ''} connected</b>
          {total > 0 && ` · ${total.toLocaleString()} documents under compliance monitoring`}
          <div className="muted" style={{ marginTop: 2 }}>
            connect a source below, then run a scan — the mova Agent classifies and re-scans continuously
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          {/* Scan-time options — they configure the NEXT scan, so they live here next
              to the Scan button (not in the global header). */}
          {setDeepScan && (
            <button type="button" className={`ai-toggle${deepScan ? ' ai-toggle--on' : ''}`}
              onClick={() => setDeepScan(v => !v)} aria-pressed={deepScan}
              title={deepScan
                ? 'Deep scan also looks for sensitive data (SSNs, credit cards, emails) in your documents. A bit slower on large PDF sets. Click for a faster accessibility-only scan.'
                : 'Fast scan checks accessibility only — no sensitive-data detection. Click to also scan for sensitive data.'}>
              {deepScan ? '🔍 Deep scan' : '◻ Fast scan'}
            </button>
          )}
          {setQueuedScan && (
            <button type="button" className={`ai-toggle${queuedScan ? ' ai-toggle--on' : ''}`}
              onClick={() => setQueuedScan(v => !v)} aria-pressed={queuedScan}
              title={queuedScan
                ? 'Runs this scan in the background queue — it keeps going if you close the tab and handles large libraries reliably (recommended). Click to run it in this browser session instead.'
                : 'Runs this scan in your current browser session (faster to start, but stops if you close the tab). Click to run it in the background queue instead.'}>
              {queuedScan ? '⚡ Background' : '◻ This session'}
            </button>
          )}
          <button disabled={busy || !canScanAll} onClick={() => {
            if (SIM) { onScan('all'); return }
            if (hasDriveToken) { handleScan('_gdrive'); return }
            if (hasSPToken)    { onScan('sharepoint'); return }
          }}>
            {busy ? 'scanning…' : 'Scan all sources'}
          </button>
        </div>
      </div>

      {/* ── Active sources — horizontal cards ─────────────────────────────── */}
      <div className="intsources">
        {CONNECTABLE.map((s) => {
          const isGdrive     = s.type === 'google_drive'
          const connected    = isGdrive ? hasDriveToken : hasSPToken
          const enriched     = isGdrive && hasDriveToken ? (driveBackend || s) : s
          const isConnecting = isGdrive ? gdConnecting : spConnecting
          const error        = isGdrive ? gdError : spError
          const desc         = isGdrive
            ? 'Scan Google Drive files for WCAG accessibility issues'
            : 'Scan OneDrive & SharePoint for accessibility issues'
          const lastScan     = lastScanLabel(scans, s.type)

          return (
            <div className={`srccard${connected ? ' srccard--on' : ''}`} key={s.id}>
              {/* Left: logo */}
              <div className="srccard-logo" aria-hidden="true">{LOGO[s.type] || LOGO.web}</div>

              {/* Middle: name + status */}
              <div className="srccard-body">
                <div className="srccard-name">{enriched.name || s.name}</div>
                {connected ? (
                  <div className="srccard-meta">
                    {enriched.user && <span>{enriched.user}</span>}
                    {enriched.files != null && <span>{enriched.files.toLocaleString()} files</span>}
                    <span>{lastScan ? `last scanned ${lastScan}` : 'not yet scanned'}</span>
                    <span className="srccard-badge">
                      <span className="livedot" aria-hidden="true" />connected · read-only
                    </span>
                  </div>
                ) : (
                  <div className="srccard-desc">{desc}</div>
                )}
                {error && <div className="srccard-err">{error}</div>}
              </div>

              {/* Right: action */}
              <div className="srccard-actions">
                {connected ? (
                  <>
                    <button className="ghost small" onClick={() => setSelSrc(enriched)}>Details</button>
                    <button disabled={busy} onClick={() => handleScan(s.id)}>
                      {busy ? 'Scanning…' : 'Scan'}
                    </button>
                  </>
                ) : (
                  <button className="srccard-connect" disabled={isConnecting}
                          onClick={isGdrive ? connectGoogle : connectMicrosoft}>
                    {isConnecting
                      ? 'Connecting…'
                      : isGdrive
                        ? <><GoogleG /> Connect Google Drive</>
                        : <><MsLogo /> Connect Microsoft</>}
                  </button>
                )}
              </div>
            </div>
          )
        })}
      </div>

      {/* ── Coming-soon sources — small chips ─────────────────────────────── */}
      <div className="intsoon">
        {FUTURE.map((s) => (
          <div className="soonchip" key={s.name} aria-hidden="true">
            {s.logo}
            <span className="soonchip-name">{s.name}</span>
            <span className="soonchip-tag">coming soon</span>
          </div>
        ))}
      </div>

      {pickerSrc && !busy && (
        <FolderPicker onScan={handlePickerScan} onClose={() => setPickerSrc(null)} />
      )}

      {selSrc  && <SourceDrawer source={selSrc}  files={files.filter((f) => f.source === selSrc.id)}
                                onClose={() => setSelSrc(null)}  onPickFile={setSelFile} />}
      {selFile && <FileDrawer   file={selFile}   onClose={() => setSelFile(null)} />}
    </>
  )
}
