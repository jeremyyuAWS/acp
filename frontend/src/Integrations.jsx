import { useState, useEffect, useRef } from 'react'
import { getConfig, listFolders, listSpFolders, getScanLocations, setScanLocations } from './api.js'
import { SIM } from './sim.js'
import { googleUserInfo } from './googleIdentity.js'
import SourceDrawer from './SourceDrawer.jsx'
import FileDrawer from './FileDrawer.jsx'
import { filesForSource, inventoryFacts, fmtSize, sourceKeys } from './sourceOps.js'
// Single source of truth for the SharePoint/Graph scopes, so this sign-in path and SharePoint.jsx
// can never request different permissions than IT consented to (read-only; see that module).
import { SP_SCOPES, getMicrosoftTenants } from './sharepointScopes.js'
import { signInForScopes, MsalNotReady, MsalNotConfigured } from './msalClient.js'
import { friendlyAuthError } from './authErrors.js'

// Azure client/tenant come from /config at runtime now (getSpAuth in sharepointScopes.js), so a
// deployment is pointed at a tenant with an env var and no rebuild; VITE_AZURE_* is the fallback.
const GD_SCOPES = 'https://www.googleapis.com/auth/drive.readonly https://www.googleapis.com/auth/drive.file'

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

function OneDriveMark() {
  // Official OneDrive cloud mark (full colour), shown on a white tile like the Drive logo above.
  return (
    <svg viewBox="-154.5063 -164.9805 1339.0546 989.883" width="26" height="26" aria-hidden="true">
      <path fill="#0364B8" d="M622.292 445.338l212.613-203.327C790.741 69.804 615.338-33.996 443.13 10.168a321.9 321.9 0 00-188.92 134.837c3.29-.083 368.082 300.333 368.082 300.333z" />
      <path fill="#0078D4" d="M392.776 183.283l-.01.035A256.233 256.233 0 00257.5 144.921c-1.104 0-2.189.07-3.29.083C112.063 146.765-1.74 263.424.02 405.567a257.389 257.389 0 0046.244 144.04l318.528-39.894 244.21-196.915z" />
      <path fill="#1490DF" d="M834.905 242.012c-4.674-.312-9.37-.528-14.123-.528a208.464 208.464 0 00-82.93 17.117l-.006-.022-128.844 54.22 142.041 175.456 253.934 61.728c54.8-101.732 16.752-228.625-84.98-283.424a209.23 209.23 0 00-85.09-24.546z" />
      <path fill="#28A8EA" d="M46.264 549.607C94.36 618.757 173.27 659.967 257.5 659.922h563.281c76.946.022 147.691-42.202 184.195-109.937L609.001 312.798z" />
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
  onedrive: <Tile bg="#fff"><OneDriveMark /></Tile>,
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

// A provider link is navigation, not an ACP management action. Prefer the exact HTTPS URL a
// connector supplies; otherwise use the provider's signed-in landing page. Never interpolate an
// item id into a guessed tenant URL — Microsoft site ids are compound identifiers, not web hosts.
export function sourceManagementDestination(source = {}) {
  const exact = source.management_url || source.web_url || source.webUrl || source.site_url
  if (typeof exact === 'string' && /^https:\/\//i.test(exact)) {
    return { url: exact, label: source.providerType === 'sharepoint' || source.type === 'sharepoint'
      ? 'Open SharePoint' : source.type === 'google_drive' ? 'Open Google Drive' : 'Open OneDrive' }
  }
  if (source.type === 'google_drive') return { url: 'https://drive.google.com/drive/my-drive', label: 'Open Google Drive' }
  if (source.providerType === 'sharepoint' || source.type === 'sharepoint') {
    return { url: 'https://www.microsoft365.com/launch/sharepoint', label: 'Open SharePoint' }
  }
  if (source.type === 'onedrive') return { url: 'https://www.microsoft365.com/launch/onedrive', label: 'Open OneDrive' }
  return null
}

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

// The picker is shared with Discover — the SAME component, so "choose exactly what to scan"
// cannot mean two different things in two places. Its header comment used to claim this file
// already used it; it did not, which is why the Sources tab promised to "manage the locations
// ACP scans" and then offered no way to choose one.
import FolderPicker from './FolderPicker.jsx'

// Which source key a card's locations are stored under. Drive and SharePoint/OneDrive are the
// two sources with a folder hierarchy to narrow; a local corpus has no picker.
const LOC_KEY = (type) => (type === 'google_drive' ? 'drive'
  : (type === 'sharepoint' || type === 'onedrive') ? 'sharepoint' : null)

export default function Integrations({ sources, files = [], scans = [], onScan, busy, hasDriveToken, hasSPToken, onConnect,
                                       scanId = null, onOpenAssess = null,
                                       openSourceKey = null, onOpenSourceHandled = null }) {
  const [selSrc,      setSelSrc]      = useState(null)
  const [selSrcInitialTab, setSelSrcInitialTab] = useState('Overview')
  const [selFile,     setSelFile]     = useState(null)

  // A redirect FROM elsewhere (today: the Discover completion card's "what changed since your
  // last scan" link) — `openSourceKey` is the raw scan-source string (run.source: 'local',
  // 'drive', 'sharepoint', a SharePoint site id, …), not a source object, so it goes through the
  // same `sourceKeys` matching SourceDrawer's own data (runsForSource/filesForSource) already
  // uses — a second, ad-hoc string comparison here is exactly how the OneDrive/'sharepoint' vs
  // 'sp-root' mismatch this file's header comment describes would happen again. Opens straight to
  // the Activity tab, where the real cross-scan diff (getInventoryDiff) actually lives — a normal
  // "Manage" click below still opens on Overview.
  useEffect(() => {
    if (!openSourceKey) return
    const key = String(openSourceKey).toLowerCase()
    const match = (sources || []).find((s) => sourceKeys(s).includes(key))
    // Found live 2026-08-29: onOpenSourceHandled used to fire unconditionally, so a key that
    // matched nothing (sources not loaded yet when this ran, or the connector was
    // disconnected/reconfigured since the scan that redirected here) got silently marked
    // "handled" — clearing App.jsx's pendingSourceOpen with the drawer never opening and no
    // way to tell the click did anything. Only clear it on an actual match; leaving it pending
    // on a miss means a later mount of this component (sources having since loaded) gets one
    // more real chance, and a fresh onOpenSource() call for a different key still overwrites
    // it regardless, so a permanent miss can never block a future valid redirect.
    if (match) {
      setSelSrcInitialTab('Activity')
      setSelSrc(match)
      onOpenSourceHandled?.()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openSourceKey])
  // Every OTHER way of opening the drawer (Manage / View files / Details, below) is a direct
  // click on a specific card — it always means Overview, never a stale Activity tab left over
  // from an earlier redirect.
  const openSrc = (s) => { setSelSrcInitialTab('Overview'); setSelSrc(s) }
  const [gdConnecting, setGdConnecting] = useState(false)
  const [gdError,      setGdError]      = useState('')
  const [spConnecting, setSpConnecting] = useState(false)
  const [spError,      setSpError]      = useState('')
  const [googleClientId, setGoogleClientId] = useState('')
  // Every SharePoint/OneDrive tenant this deployment can connect to (multi-tenant SharePoint) —
  // one entry for a single-tenant deployment (today's default), more once a second Entra app
  // registration is configured (ACP_AZURE_CLIENT_ID_2/ACP_AZURE_TENANT_ID_2). spTenantKey is which
  // one the connect button targets; the picker below only renders when there is a real choice.
  const [microsoftTenants, setMicrosoftTenants] = useState([])
  const [spTenantKey, setSpTenantKey] = useState('')
  const availRef = useRef(null)
  const gdTokenClientRef = useRef(null)

  useEffect(() => {
    getConfig().then((c) => { if (c?.google_client_id) setGoogleClientId(c.google_client_id) }).catch(() => {})
    getMicrosoftTenants().then((t) => {
      setMicrosoftTenants(t)
      // Default to whichever tenant is already connected (sp_tenant_key), so re-opening this tab
      // doesn't silently reset the picker to "primary" out from under an existing connection.
      const stored = sessionStorage.getItem('sp_tenant_key')
      setSpTenantKey((stored && t.some((x) => x.key === stored)) ? stored : (t[0]?.key || ''))
    }).catch(() => {})
  }, [])

  const driveBackend   = sources.find((s) => s.type === 'google_drive')
  // The OneDrive card is a hard-coded CONNECTABLE row (`sp-root`) carrying nothing but an id, a
  // type and a name. Its backend row arrives under type 'onedrive' OR 'sharepoint' — Graph serves
  // both from one connection — and nothing here looked for either, so the card had no user, no
  // file count and no schedule. That is where `undefined · 0 docs · agent: undefined` in the
  // drawer came from: not an empty estate, a source row nobody joined to the card.
  const spBackend      = sources.find((s) => s.type === 'onedrive' || s.type === 'sharepoint')

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
      // spTenantKey selects WHICH configured tenant to sign into — 'primary' (or the only entry)
      // when this deployment has just one, same as before multi-tenant SharePoint existed.
      const { account, accessToken } = await signInForScopes(SP_SCOPES, spTenantKey)
      sessionStorage.setItem('sp_token', accessToken)
      sessionStorage.setItem('sp_account', JSON.stringify(account))
      // Recorded so a reload knows which tenant is connected (picker default above) and so the
      // connected-source card below can label it — otherwise "OneDrive" alone is ambiguous the
      // moment a second tenant exists to confuse it with.
      sessionStorage.setItem('sp_tenant_key', spTenantKey || '')
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
  //
  // Locations are a property of the CONNECTION, loaded once for the tab. `null` while loading is
  // deliberately distinct from `{}`: "we do not know yet" must not render as "scans everything",
  // which is the reassuring reading and the wrong one.
  const [locs, setLocs] = useState(null)
  const [pickFor, setPickFor] = useState(null)   // the source whose picker is open
  useEffect(() => {
    let alive = true
    getScanLocations().then((r) => alive && setLocs(r.locations || {})).catch(() => alive && setLocs({}))
    return () => { alive = false }
  }, [])

  // Exclusions live under a reserved `_exclude` key in the same stored map, so one GET carries
  // the whole scope. Read through a helper because "no exclusions" and "source not configured"
  // must both come back as [] rather than undefined — a chip list that renders `undefined.map`
  // takes the Sources tab down.
  const exclFor = (key) => ((locs || {})._exclude || {})[key] || []

  const saveLocations = (src, folders, exclude = []) => {
    const key = LOC_KEY(src.type)
    if (!key) return
    setLocs((s) => ({ ...(s || {}), [key]: folders,
                      _exclude: { ...((s || {})._exclude || {}), [key]: exclude } }))
    setScanLocations(key, folders, exclude).catch(() => {
      // Put it back rather than leave the card asserting a scope the server does not have. A
      // card that claims a narrowing the next scan will not apply is worse than a failed save.
      getScanLocations().then((r) => setLocs(r.locations || {})).catch(() => {})
    })
    setPickFor(null)
  }

  // Every "New scan" button here just calls `onScan`, which App wires to `requestScan` — the
  // universal gate that opens the app-level ScanReviewModal (scope + behavior review) before any
  // scan runs. This tab used to own that modal; it now shares the one App renders for every entry
  // point, so Discover / Overview / single-file / browse-panel scans can no longer bypass it.
  //   • page-level "New scan" → onScan('all')   (every connected source)
  //   • a card's "New scan"   → onScan('drive' | 'sharepoint')   (that source)
  // A card's scan arg maps its connector type to the backend source doScan resolves against.
  const cardScanArg = (src) => (src.type === 'google_drive' ? 'drive' : 'sharepoint')

  // NOT gated on a cloud token. `onScan('all')` reaches App.doScan, which resolves 'all' to the
  // backend's `local` source whenever no Drive/SharePoint token is present — the path a local
  // corpus deployment runs on, and the one the Playwright pipeline spec drives. Gating on tokens
  // alone disabled a scan the app was perfectly able to run.
  //
  // That was survivable while Discover carried its own ungated "Re-scan all sources" button. Since
  // 2026-09-02 (UI-simplification PRD) this is the ONLY scan entry point in the product, so a
  // disabled button here is a dead end with nothing to route around it. Scope is still reviewed
  // before anything runs: the button opens the app-level gate, it does not start a scan.
  //
  // `busy` is the whole condition — one scan at a time is a real constraint (the backend rejects a
  // second discovery on the same source), a missing cloud token is not.

  // The connected connectable sources (Drive / OneDrive) — the ones a scan can actually run against.
  // Card fields win over the backend row's, so the OneDrive card keeps its id/type/name (the
  // logo and the scan argument key off `type`) while inheriting user, file count, access and
  // schedule from the row that actually knows them.
  const connectedSources = CONNECTABLE.filter((s) => (s.type === 'google_drive' ? hasDriveToken : hasSPToken))
    .map((s) => {
      if (s.type === 'google_drive') return hasDriveToken ? (driveBackend || s) : s
      return spBackend ? { ...spBackend, ...s, providerType: spBackend.type } : s
    })

  // One dominant health state per source — never more than one badge (see plan §4).
  const healthState = (h) => {
    if (!h) return { key: 'none', label: 'Not yet scanned' }
    if (h.status === 'healthy') return { key: 'ok', label: 'Healthy' }
    return { key: 'attn', label: 'Needs attention',
      sub: `${h.totalErr} file${h.totalErr !== 1 ? 's' : ''} couldn’t be accessed in recent scans` }
  }
  const HEALTH_STATE = {
    ok:   ['var(--success-fg)', 'var(--success-bg)'],
    attn: ['var(--error-fg-strong)', '#FCEBEB'],
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
          <button disabled={busy} onClick={() => onScan('all')}>
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
              // The connected tenant's own label, appended only when more than one is configured
              // — a single-tenant deployment (still every deployment today) sees no change here,
              // since "OneDrive" alone was never ambiguous until a second tenant existed to
              // confuse it with.
              const connectedTenant = !isGdrive && microsoftTenants.length > 1
                ? microsoftTenants.find((t) => t.key === sessionStorage.getItem('sp_tenant_key'))
                : null
              const title     = src.name && src.name !== typeLabel ? `${typeLabel} — ${src.name}`
                : connectedTenant ? `${typeLabel} — ${connectedTenant.label}` : typeLabel
              const store     = isGdrive ? 'Drive' : 'OneDrive'
              const lastRun   = lastCompletedRun(scans, src.type)
              const lastScan  = lastScanLabel(scans, src.type)
              const health    = healthState(sourceHealth(scans, src.type))
              const [hfg, hbg] = HEALTH_STATE[health.key]
              const err       = isGdrive ? gdError : spError
              // Inventory the card can prove: the file rows ACP holds for THIS source, not the
              // store's own total. `src.files` above is what the connector reports it contains;
              // this is what ACP has actually seen. Both are shown, labelled differently, because
              // a gap between them is a scope fact worth noticing rather than a rounding error.
              const inv       = inventoryFacts(filesForSource(files, src))
              const providerDestination = sourceManagementDestination(src)
              return (
                <div className="srccard srccard--on" key={src.id}>
                  <div className="srccard-logo" aria-hidden="true">{LOGO[src.type] || LOGO.web}</div>

                  <div className="srccard-body">
                    <div className="srccard-name">{title}</div>
                    <div className="srccard-meta">
                      {src.user && <span>{src.user}</span>}
                      <span className="srccard-count">
                        {src.files != null ? `${src.files.toLocaleString()} in ${store}` : `— in ${store}`}
                        {lastRun && lastRun.files != null && ` · ${lastRun.files.toLocaleString()} in last scan`}
                      </span>
                      <span>{lastScan ? `Last scanned ${lastScan}` : 'Not yet scanned'}</span>
                    </div>
                    {/* What Discovery found, in the order an operator reads it: how much, then
                        when, then what went wrong. A source with no completed run says so and
                        says why the count is empty — "Healthy · 0 files" with no explanation is
                        the line that makes a working connection look broken. */}
                    {inv.documents > 0 ? (
                      <div className="srccard-inv muted">
                        {inv.documents.toLocaleString()} discovered
                        {inv.bytesKb != null && ` · ${fmtSize(inv.bytesKb)}`}
                        {inv.owners != null && ` · ${inv.owners.toLocaleString()} owner${inv.owners === 1 ? '' : 's'}`}
                        {inv.departments != null && ` · ${inv.departments.toLocaleString()} department${inv.departments === 1 ? '' : 's'}`}
                      </div>
                    ) : !lastRun ? (
                      <div className="srccard-inv muted">
                        No discovery completed — ACP has access, but the source has not yet been inventoried.
                      </div>
                    ) : null}
                    {lastRun && (lastRun.error || 0) > 0 && (
                      <div className="srccard-inv muted">
                        {Number(lastRun.error).toLocaleString()} file{lastRun.error === 1 ? '' : 's'} could not be read in the last run
                      </div>
                    )}
                    {/* SCANNED LOCATIONS — the control this page's own subtitle promises
                        ("Manage the locations ACP scans and monitors") and did not have. It sits
                        on the card rather than behind a scan because it is configuration: a thing
                        decided once about a source, not re-chosen every run. Stated in both
                        directions — "Entire Drive" is rendered as loudly as a narrowing, because
                        a row that appears only when narrowed teaches a reader to read its absence
                        as "everything", and it is absent on every source that never set one. */}
                    {LOC_KEY(src.type) && (
                      <div className="srccard-inv" style={{ display: 'flex', gap: 6, flexWrap: 'wrap',
                                                            alignItems: 'center', marginTop: 4 }}>
                        <span className="muted">Scans:</span>
                        {locs === null ? <span className="muted">…</span>
                          : (locs[LOC_KEY(src.type)] || []).length === 0 ? (
                            <span>Entire {store}</span>
                          ) : (locs[LOC_KEY(src.type)] || []).map((f) => (
                            <span key={f.id} style={{ display: 'inline-flex', alignItems: 'center', gap: 4,
                              fontSize: 11.5, background: '#F1EFF3', border: '1px solid var(--line)',
                              borderRadius: 999, padding: '2px 8px' }}>📁 {f.name}</span>
                          ))}
                        {/* Carve-outs beside the inclusions, never on their own screen: "HR" and
                            "HR except Archive" are different scopes and the card is where someone
                            checks what a count covered. */}
                        {exclFor(LOC_KEY(src.type)).map((f) => (
                          <span key={f.id} style={{ display: 'inline-flex', alignItems: 'center', gap: 4,
                            fontSize: 11.5, background: '#FBF0F0', border: '1px solid var(--line)',
                            borderRadius: 999, padding: '2px 8px' }}>🚫 except {f.name}</span>
                        ))}
                        <button className="linklike" style={{ fontSize: 12 }}
                                onClick={() => setPickFor(src)}>Edit</button>
                      </div>
                    )}
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
                    <button disabled={busy} onClick={() => onScan(cardScanArg(src))}>
                      {busy ? 'Scanning…' : lastRun ? 'New scan' : 'Run first discovery'}
                    </button>
                    {providerDestination && <a className="ghost small" href={providerDestination.url}
                      target="_blank" rel="noopener noreferrer"
                      aria-label={`${providerDestination.label} in a new tab`}
                      style={{ display: 'inline-flex', alignItems: 'center', textDecoration: 'none' }}>
                      {providerDestination.label} ↗
                    </a>}
                    <button className="ghost small" onClick={() => openSrc(src)}>Manage</button>
                    <details className="srccard-ovf">
                      <summary aria-label="More actions" title="More actions">⋯</summary>
                      <div className="srccard-ovf-menu">
                        <button type="button" onClick={() => openSrc(src)}>View files</button>
                        <button type="button" onClick={() => openSrc(src)}>Details</button>
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
                  {/* Only rendered once a second tenant is actually configured
                      (ACP_AZURE_CLIENT_ID_2/ACP_AZURE_TENANT_ID_2) — a single-tenant deployment
                      (every deployment today) sees no picker and no behaviour change. */}
                  {!isGdrive && microsoftTenants.length > 1 && (
                    <label className="srccard-tenantpick muted" style={{ display: 'flex',
                      alignItems: 'center', gap: 6, fontSize: 12, marginTop: 6 }}>
                      Tenant:
                      <select value={spTenantKey} disabled={isConnecting}
                              onChange={(e) => setSpTenantKey(e.target.value)}>
                        {microsoftTenants.map((t) => (
                          <option key={t.key} value={t.key}>{t.label}</option>
                        ))}
                      </select>
                    </label>
                  )}
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

      {/* The drawer resolves its own file rows (sourceOps.filesForSource): a card id is not a file
          row's `source` key — `sp-root` never matched `sharepoint` — and filtering here on
          `f.source === selSrc.id` is what handed it an empty list to call "0 docs". */}
      {selSrc  && <SourceDrawer source={selSrc} files={files} scans={scans} busy={busy}
                                initialTab={selSrcInitialTab}
                                onScan={(src) => onScan(cardScanArg(src))}
                                onOpenAssess={onOpenAssess}
                                onClose={() => setSelSrc(null)}  onPickFile={setSelFile} />}
      {/* One picker component for both sources — the lister is what differs. Drive drills through
          GET /folders; OneDrive/SharePoint through GET /sharepoint/folders, whose ids already
          carry their driveId because a Graph item id is unique only within its drive. */}
      {pickFor && (
        <FolderPicker
          title={`Folders to scan in ${pickFor.name || 'this source'}`}
          rootName={LOC_KEY(pickFor.type) === 'drive' ? 'My Drive' : 'OneDrive'}
          lister={LOC_KEY(pickFor.type) === 'drive'
            ? listFolders
            : (parent) => listSpFolders(parent)}
          initial={(locs || {})[LOC_KEY(pickFor.type)] || []}
          initialExclude={exclFor(LOC_KEY(pickFor.type))}
          onConfirm={(folders, exclude) => saveLocations(pickFor, folders, exclude)}
          onClose={() => setPickFor(null)} />
      )}
      {selFile && <FileDrawer   file={selFile}   onClose={() => setSelFile(null)} scanId={scanId} />}
    </>
  )
}
