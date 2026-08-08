import { useEffect, useState, useMemo, useCallback, useRef, lazy, Suspense } from 'react'
import HitlBell from './HitlBell.jsx'
import { refreshDriveToken } from './driveAuth.js'
import PrivateAiBadge from './PrivateAiBadge.jsx'
import { getSources, getRubric, getConfig, listScans, getScan, getActiveScan, startScan, startScanQueued, cancelScan, getJob, setDriveToken, setSPToken, setGoogleToken, clearAllTokens, getDecisions, saveDecisionsBatch, refreshScanDriveToken, SESSION_EXPIRED } from './api'
import { SIM } from './sim.js'
import { setPersona, recommendFor } from './sim.js'
import { loadDelegations } from './OwnerDelegate.jsx'
import { loadRolePrivileges } from './RolePrivilege.jsx'
import { loadFileTypeConfig } from './FileTypeConfig.jsx'
import { annotate, loadPublished } from './ontology.js'
import { RuleBreakdown } from './Transparency.jsx'
import Logo from './Logo.jsx'
import ChatWidget from './ChatWidget.jsx'
// Lazy: KnowledgeGraph statically imports all of d3 (~250 kB min) — the only heavy
// dep not already behind a dynamic import. Loading it on tab entry keeps d3 out of
// the main chunk entirely.
const KnowledgeGraph = lazy(() => import('./KnowledgeGraph.jsx'))
import SignIn from './SignIn.jsx'
import Settings from './Settings.jsx'
import Monitor from './Monitor.jsx'
import Publish from './Publish.jsx'
import Overview from './Overview.jsx'
import AssessRunner from './AssessRunner.jsx'
import CoverageScorecard from './CoverageScorecard.jsx'
import ConfidenceDashboard from './ConfidenceDashboard.jsx'
import AccessibilityStatus from './AccessibilityStatus.jsx'
import RiskScore from './RiskScore.jsx'
import Integrations from './Integrations.jsx'
import Discover from './Discover.jsx'
import Dashboard from './Dashboard.jsx'
import Remediate from './Remediate.jsx'
import EmptyState, { Loading } from './EmptyState.jsx'
import ErrorBoundary from './ErrorBoundary.jsx'
import { applyScopeConfig } from './activeScope.js'
import A11ySelfCheck from './A11ySelfCheck.jsx'
import { scanPhaseLine, NARRATION_STEPS } from './phaseNarration.js'
import { useScanRefetch } from './scanRefetch.js'

// Self-scan overlay: on in dev, or on the deployed demo via ?a11y
const SHOW_A11Y = import.meta.env.DEV || (typeof location !== 'undefined' && new URLSearchParams(location.search).has('a11y'))

// step=0 → utility tab (no number); step>0 → workflow step with numbered badge
const TABS = [
  ['overview',      'Overview',      'at a glance',         0],
  ['integrations',  'Integrations',  'connect sources',     0],
  ['discover',      'Discover',      'inventory · classify', 1],
  ['assess',        'Assess',        'score vs WCAG',       2],
  ['remediate',     'Remediate',     'fix issues',          3],
  ['publish',       'Publish',       'certify',             4],
  ['monitor',       'Monitor',       'track compliance',    5],
  ['graph',         'Knowledge Graph', 'explore findings',   0],
]

function timeAgo(iso) {
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

function fmtStamp(iso) {
  if (!iso) return null
  // timeZoneName: 'short' stamps the viewer's zone (e.g. "PDT" / "CDT") so cross-timezone
  // viewers (you in PT, Deva in CT) can tell at a glance it's THEIR local time.
  return new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit', timeZoneName: 'short' })
}

function progressText(p) {
  if (!p) return ''
  const m = {
    queued: 'Queued…', connecting: 'Connecting to source…', discovering: 'Discovering files…',
    reading: `Reading files · ${p.files_done}/${p.files_found}`,
    tagging: 'mova Agent classifying & tagging documents…',
    analysing: `Analysing documents · ${p.files_done}/${p.files_found}`,
    // NB: 'scoring' here is the scan compiling per-document results, NOT the WCAG
    // assessment — that runs on the Assess tab. Label it as such to avoid conflation.
    scoring: 'Compiling results…', done: 'Complete', error: 'Error',
  }
  let s = m[p.phase] ?? p.phase
  if (p.current && (p.phase === 'reading' || p.phase === 'analysing')) s += ` · ${p.current}`
  // Queued scans don't stream per-file progress, so reassure the user it's alive
  // by showing elapsed time on the long worker-pool phase.
  if (p.elapsed != null) s += ` · still working (${p.elapsed}s)`
  return s
}

// Overall scan progress (0–100) across every phase, so the bar only reaches 100%
// when the scan is actually done — not when the read phase finishes (tagging,
// analysing and scoring still follow). The read phase spans 12→84%, scaled by the
// real per-file count; the post-read phases fill the remainder.
const PHASE_PCT = { queued: 2, connecting: 5, discovering: 9, reading: 12, tagging: 88, analysing: 92, scoring: 97, done: 100, error: 100 }


function progressPct(p) {
  if (!p) return 0
  if (typeof p.pct === 'number') return p.pct   // explicit (e.g. queued per-file count)
  if (p.phase === 'reading' && p.files_found) {
    const frac = Math.min(1, (p.files_done || 0) / p.files_found)
    return Math.round(12 + frac * (84 - 12))
  }
  return PHASE_PCT[p.phase] ?? 6
}

// Honest progress for a queued/fan-out scan, derived from the scan row's REAL per-file counter
// (scan_runs.files_done / files, bumped as each file's per-file job lands) — never a timer or a
// synthetic decay curve. While files remain, the estate is being analysed; once every file is in,
// the finalize pass (per-document score + estate aggregate) runs. `current` is deliberately left
// unset: the fan-out analyses files in parallel across workers, so no single "file N is in flight
// right now" is knowable — the truthful signal is the count, not a made-up filename.
function queuedProgress(g, elapsed) {
  const run = g && g.run
  const total = (run && run.files) || 0
  const done = (run && run.files_done) || 0
  if (!total) return { phase: 'discovering', elapsed }        // estate not listed yet
  const phase = done < total ? 'analysing' : 'scoring'
  const pct = Math.round(12 + Math.min(1, done / total) * (95 - 12))
  return { phase, files_found: total, files_done: done, current: null, elapsed, pct }
}

// Shown on results views (Overview / Dashboard / Monitor) until the user runs Assess —
// scores, trends and dashboards only appear after an explicit assessment.
function AssessGate({ onGo }) {
  return (
    <section className="panel" style={{ textAlign: 'center', padding: '52px 24px' }}>
      <div style={{ fontSize: 30, marginBottom: 10 }}>📋</div>
      <h2 style={{ margin: '0 0 6px' }}>Run the assessment to see results</h2>
      <p className="muted" style={{ maxWidth: 480, margin: '0 auto 20px', lineHeight: 1.55 }}>
        This estate has been discovered but not yet assessed against WCAG 2.1. Running <b>Assess</b>
        opens each file and scores it; compliance scores, trends and dashboards appear here once it
        completes.
      </p>
      <button onClick={onGo}>Go to Assess →</button>
    </section>
  )
}

// Per-user/per-session "fresh start": wipe activity caches so no scan results, published
// files, assess/remediation progress, scores, or upload history from a prior session or
// user survive. Config (roles, file-types, delegations) is intentionally left alone.
const ACTIVITY_LS = ['mova_ontology_v1', 'mova_drive_scores', 'mova_drive_archive', 'mova_upload_history']
function clearActivityStorage() {
  try {
    Object.keys(sessionStorage).filter((k) => k.startsWith('acp-')).forEach((k) => sessionStorage.removeItem(k))
    ACTIVITY_LS.forEach((k) => localStorage.removeItem(k))
  } catch { /* storage unavailable — ignore */ }
}

export default function App() {
  const [me, setMe] = useState(null)
  // Why the user is looking at the sign-in screen. null on a first visit; set when a 401
  // bounced them out mid-session, so SignIn can say so rather than appear for no reason.
  const [signedOutReason, setSignedOutReason] = useState(null)
  const [rubric, setRubric] = useState(null)
  const [sources, setSources] = useState([])
  const [scan, setScan] = useState(null)
  const [justAssessed, setJustAssessed] = useState(null) // scan id assessed this session (optimistic)
  const [assessPhase, setAssessPhase] = useState('idle') // AssessRunner phase: idle | running | done
  const [scanLoading, setScanLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [view, setView] = useState('overview')
  const [decisions, setDecisions] = useState({})
  const [triage, setTriage] = useState({})              // per-scan triage, lifted from Remediate for time-travel
  const savedDecRef = useRef({ scanId: null, decisions: {}, triage: {} })  // last-persisted snapshot
  const hydratingRef = useRef(false)                    // suppress the save effect during hydration
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [scanList, setScanList] = useState([])
  const [delta, setDelta] = useState(null)
  const [deltaKey, setDeltaKey] = useState(0)
  const [progress, setProgress] = useState(null)
  const [loaded, setLoaded] = useState(false)
  const [certifiedDocs, setCertifiedDocs] = useState([])
  const [publishedFiles, setPublishedFiles] = useState([])
  const [hasDriveToken, setHasDriveToken] = useState(() => !!sessionStorage.getItem('gd_token'))

  // ADR 0014 — keep a long-running scan's Drive token fresh. GIS access tokens expire ~1h;
  // while a scan is running we silently re-mint one every 20min and push it to the backend
  // so scans that outlast the token don't 401 on their tail. Best-effort; no-op without GIS.
  useEffect(() => {
    if (!hasDriveToken) return
    const iv = setInterval(async () => {
      try {
        const a = await getActiveScan()
        if (!a?.id) return
        await refreshDriveToken()
        await refreshScanDriveToken(a.id)
      } catch { /* best-effort keep-alive */ }
    }, 20 * 60 * 1000)
    return () => clearInterval(iv)
  }, [hasDriveToken])
  const [hasSPToken, setHasSPToken] = useState(() => !!sessionStorage.getItem('sp_token'))
  const [delegations, setDelegations] = useState(loadDelegations)
  const [fileTypeConfig, setFileTypeConfig] = useState(loadFileTypeConfig)
  const [rolePrivileges, setRolePrivileges] = useState(loadRolePrivileges)
  const [ontology, setOntology] = useState(loadPublished)
  const [aiEnabled, setAiEnabled] = useState(true)
  const [hitlCount, setHitlCount] = useState(0)  // pending HITL items, reported up from Remediate for the nav badge
  const [queuedScan, setQueuedScan] = useState(true)   // durable fan-out queue by default; "This session" is the opt-out
  const [deepScan, setDeepScan] = useState(false)      // off by default → Fast scan; opt in to PII scan via the switch
  const [excludeRemediated, setExcludeRemediated] = useState(true)  // on by default — skip re-discovering ACP's own Remediated/ output
  const [incremental, setIncremental] = useState(true)  // ADR 0011 — skip re-analysing byte-identical files already scored under the same rubric
  // The in-flight durable scan's id — what the banner's Stop button cancels. null when
  // no queued scan is being polled (sync scans finish in-request and can't be stopped).
  const [liveScanId, setLiveScanId] = useState(null)
  const [tick, setTick] = useState(0)                  // bumped every minute to keep timeAgo labels fresh
  const [platformVersion, setPlatformVersion] = useState(null)  // full git-derived CalVer from /config (with the daily .N)
  // Bumped once if /config reports a scope different from activeScope.js's fallback. React cannot
  // observe a module-level binding, so this is what makes the server-driven scope actually reach
  // the rendered denominators instead of sitting in a variable nothing re-reads.
  const [, setScopeTick] = useState(0)
  // Set when the scan this tab is holding cannot be loaded for this account (per-scan 404 —
  // see api.SCAN_UNAVAILABLE). Shape: { scanId, reason, recoveredTo|null, recovered:boolean }.
  // Rendered as an alert, because the alternative — which is what shipped — is an empty score.
  const [scanUnavailable, setScanUnavailable] = useState(null)
  const recoveringRef = useRef(false)      // one recovery at a time; getScan() below can 404 too

  useEffect(() => {
    const t = setInterval(() => setTick((n) => n + 1), 60_000)
    return () => clearInterval(t)
  }, [])

  // Pull the authoritative CalVer once (works pre-auth — /config is public) so the build
  // stamp + header show the full version with the daily counter, not the date-only bundle tag.
  useEffect(() => {
    getConfig().then((c) => {
      if (c?.version) setPlatformVersion(c.version)
      // Adopt the scope the SERVER is gating on. activeScope.js ships a fallback preset so the
      // first paint is never blank, but the bundle's copy is a guess until this lands — the
      // backend's `scan_scope` setting is the only authority. `scopeTick` exists solely to
      // re-render after the module's live bindings change: React cannot observe a module
      // variable, so without it the UI would keep rendering the fallback's arithmetic and the
      // fetch would be pointless. Bumped only when something actually changed.
      if (applyScopeConfig(c)) setScopeTick((n) => n + 1)
    }).catch(() => { /* keep the build-time fallback */ })
  }, [])

  useEffect(() => {
    const onExpired = (e) => {
      clearAllTokens()
      sessionStorage.removeItem('gd_token')
      sessionStorage.removeItem('sp_token')
      setHasDriveToken(false)
      setHasSPToken(false)
      // Carry the reason to the sign-in screen. Dropping the user back to sign-in with no
      // explanation, mid-review, reads as the app having lost their work.
      setSignedOutReason(e?.detail?.reason || SESSION_EXPIRED)
      setMe(null)
    }
    window.addEventListener('acp:session-expired', onExpired)
    return () => window.removeEventListener('acp:session-expired', onExpired)
  }, [])

  // Refetch the scan when a remediation or a deferred assessment announces that the server's
  // file_records changed — see scanRefetch.js for which events and why.
  useScanRefetch(scan?.run?.id, setScan)

  // Publish writes back per file; refetching once per click would fire dozens of
  // times on "Publish all", so debounce — one getScan after the burst settles
  // makes published_at the durable source of the checkmarks (they survive tab
  // switches instead of living only in Publish's local state).
  const pubRefetchTimer = useRef(null)
  const schedulePublishRefetch = () => {
    clearTimeout(pubRefetchTimer.current)
    pubRefetchTimer.current = setTimeout(() => {
      const sid = scan?.run?.id
      if (sid) getScan(sid).then(setScan).catch(() => {})
    }, 800)
  }

  useEffect(() => {
    if (!me) return
    getRubric().then(setRubric).catch(() => {})
    getSources().then(setSources).catch(() => {})
    listScans()
      .then(async (l) => {
        setScanList(l); if (l.length) setScan(await getScan(l[0].id))
        // If a scan is still running (e.g. user reloaded mid-scan), resume tracking it.
        try { const a = await getActiveScan(); if (a && a.id) reconnectScan(a.id) } catch { /* ignore */ }
      })
      .catch(() => {})
      .finally(() => setLoaded(true))
  }, [me])

  // Annotate the corpus with the published business ontology (adds `.ont`: label,
  // priority, matched rule, weighted score) so the live workflow is ontology-aware.
  // Kept above the early return below to satisfy the rules of hooks.
  // Attach the per-file remediation recommendation. In SIM the sim builder already sets it;
  // for a REAL backend scan the files arrive without it, so compute it here — otherwise
  // `remediable` is empty and server-side remediation finds nothing to do.
  const files = useMemo(() => annotate(scan?.files ?? [], ontology).map((f) => (f.rec ? f : { ...f, rec: recommendFor(f) })), [scan, ontology])

  // Real accounts that get elevated privileges on source connect (never shown in demo list)
  const PRIV_PROFILE = {
    id: 'jeremy-yu', name: 'Jeremy Yu', role: 'Compliance Officer & Admin',
    scope: { label: 'Full estate · all departments', departments: 'all' },
    allow: ['overview', 'integrations', 'discover', 'assess', 'remediate', 'publish', 'monitor', 'settings'],
  }
  const PRIVILEGED = { 'jeremyyu.movate@gmail.com': PRIV_PROFILE }

  // Everything that belongs to ONE scan, cleared in one place.
  //
  // Three call sites used to reset overlapping-but-different subsets of this, and each missed
  // something the others cleared: sign-in reset all of it, time-travel reset `decisions` and
  // `certifiedDocs` but not `triage`, and a NEW SCAN reset none of it — it relied entirely on
  // the hydration effect, which only covers decisions/triage and only once the fetch lands.
  //
  // What that cost, concretely: `publishedFiles` gates the Publish and Monitor steps of the
  // progress rail (`publish: publishedFiles.length > 0`). Publish a document, then re-scan, and
  // the NEW scan opened with Publish and Monitor already ticked — on the strength of files
  // published against the previous one.
  //
  // `triage` matters more than it used to. Marking a single file in-scope excludes every
  // unmarked file from remediation, so showing another scan's scope marks — even for the
  // hydration round-trip — is now materially misleading, not just untidy.
  //
  // NOT reset here, deliberately: `assessPhase` and `justAssessed`. Both already self-correct
  // and clearing them would flash the Overview's gated panels off and back on. AssessRunner is
  // keyed on `run.id`, so it remounts per scan and re-emits `onPhase` from that run's own saved
  // state; and `justAssessed` is compared by id (`justAssessed === run?.id`), so a value left
  // over from another scan can never match. Add to this function only what does NOT self-correct.
  const resetScanScopedState = () => {
    setDecisions({}); setTriage({})
    setCertifiedDocs([]); setPublishedFiles([])
  }

  const signIn = (p) => {
    // Fresh per user: if a DIFFERENT user signs in (or first sign-in), wipe activity caches
    // so nothing — published files, assess/remediation results, scores — carries over.
    try {
      if (localStorage.getItem('mova_last_user') !== p.email) {
        clearActivityStorage()
        localStorage.setItem('mova_last_user', p.email || '')
      }
    } catch { /* ignore */ }
    setSignedOutReason(null)    // the sign-in worked; the expiry notice must not outlive it
    setScanUnavailable(null)    // ditto: a new session's scan list is about to be re-read
    if (p.token) {
      setGoogleToken(p.token)   // API Bearer auth
      setDriveToken(p.token)    // Same token has Drive scopes — no separate connect needed
      setHasDriveToken(true)
    } else {
      const gdToken = sessionStorage.getItem('gd_token')
      if (gdToken) { setDriveToken(gdToken); setHasDriveToken(true) }
    }
    const sp = sessionStorage.getItem('sp_token')
    if (sp) { setSPToken(sp); setHasSPToken(true) }
    // Reset ALL downstream state so the new session starts blank — including the pieces the
    // old reset missed (triage, the assess-completion phase, the optimistic-assess flag, and
    // the localStorage-backed published/ontology), so no tab shows legacy data on first view.
    setPersona(p); setScan(null); setScanList([]); setLoaded(false)
    resetScanScopedState()
    // Sign-in additionally resets what a scan change deliberately leaves alone: a new session
    // has no assessment in flight to report a phase for.
    setAssessPhase('idle'); setJustAssessed(null)
    setOntology(loadPublished())
    setSettingsOpen(false); setView((p.allow || ['overview'])[0])
    setMe({ email: p.email, name: p.name, role: p.role, scope: p.scope?.label, allow: p.allow || [] })
  }

  // Called from Integrations when a source OAuth succeeds
  const handleConnect = (provider, email, token) => {
    const priv = PRIVILEGED[email?.toLowerCase()]
    if (provider === 'google') {
      sessionStorage.setItem('gd_token', token)
      setDriveToken(token); setHasDriveToken(true)
      if (priv) setMe((m) => ({ ...m, ...priv, email, scope: priv.scope?.label }))
      getSources().then(setSources).catch(() => {})
    } else if (provider === 'microsoft') {
      sessionStorage.setItem('sp_token', token)
      setSPToken(token); setHasSPToken(true)
      if (priv) setMe((m) => ({ ...m, ...priv, email, sso: 'Microsoft', scope: priv.scope?.label }))
    }
  }

  // Time-travel: when the active scan changes, hydrate THAT scan's saved decisions.
  // These hooks MUST sit above the `!me` early return — React requires every hook to
  // run unconditionally on every render, or the hook count changes and the tree crashes.
  useEffect(() => {
    const sid = scan?.run?.id
    if (!sid || sid === savedDecRef.current.scanId) return
    let cancelled = false
    getDecisions(sid).then((d) => {
      if (cancelled) return
      const dec = {}, tri = {}
      Object.entries(d || {}).forEach(([file, m]) => {
        if (m.action) { try { dec[file] = JSON.parse(m.action) } catch { /* ignore */ } }
        if (m.triage) tri[file] = m.triage
      })
      hydratingRef.current = true
      savedDecRef.current = { scanId: sid, decisions: dec, triage: tri }
      setDecisions(dec); setTriage(tri)
    }).catch(() => {
      hydratingRef.current = true
      savedDecRef.current = { scanId: sid, decisions: {}, triage: {} }
      setDecisions({}); setTriage({})
    })
    return () => { cancelled = true }
  }, [scan?.run?.id]) // eslint-disable-line react-hooks/exhaustive-deps

  // Persist decision/triage changes to the active scan (skips hydration writes).
  useEffect(() => {
    if (hydratingRef.current) { hydratingRef.current = false; return }
    const sid = savedDecRef.current.scanId
    if (!sid || sid !== scan?.run?.id) return
    const prev = savedDecRef.current
    const items = []
    new Set([...Object.keys(prev.decisions), ...Object.keys(decisions)]).forEach((f) => {
      if (JSON.stringify(prev.decisions[f]) !== JSON.stringify(decisions[f])) items.push({ file: f, kind: 'action', value: decisions[f] ?? null })
    })
    new Set([...Object.keys(prev.triage), ...Object.keys(triage)]).forEach((f) => {
      if (prev.triage[f] !== triage[f]) items.push({ file: f, kind: 'triage', value: triage[f] ?? null })
    })
    if (items.length) saveDecisionsBatch(sid, items).catch(() => {})
    savedDecRef.current = { scanId: sid, decisions: { ...decisions }, triage: { ...triage } }
  }, [decisions, triage]) // eslint-disable-line react-hooks/exhaustive-deps

  // A per-scan request 404'd (api.js dispatches this before any caller's .catch can eat it).
  // Say so, then move the user to a scan they CAN load — an unexplained empty score is the
  // failure this replaces, and retrying an id that will never resolve only prolongs it.
  useEffect(() => {
    const onUnavailable = async (e) => {
      const badId = e?.detail?.scanId || null
      // Ignore a 404 for some OTHER scan than the one on screen: a stale poll from a tab the
      // user has already navigated away from must not evict the scan they are reading.
      const current = scan?.run?.id || null
      if (badId && current && badId !== current) return
      if (recoveringRef.current) return
      recoveringRef.current = true
      setScanUnavailable({ scanId: badId, reason: e?.detail?.reason || '', recoveredTo: null, recovered: false })
      try {
        let list = []
        try { list = await listScans() } catch { list = [] }
        setScanList(list)
        const next = list.find((s) => s.id !== badId) || null
        if (next) {
          // getScan can itself 404 (a scan deleted between the list and this read). The
          // recoveringRef guard above stops that from re-entering; the catch leaves the alert
          // standing with recovered:false, which is the honest outcome.
          const loaded = await getScan(next.id)
          setScan(loaded); resetScanScopedState(); setView('overview')
          setScanUnavailable({ scanId: badId, reason: e?.detail?.reason || '', recoveredTo: next.id, recovered: true })
        } else {
          // Nothing of their own to fall back to. Clear the dead scan and send them to the one
          // action that can produce one, rather than leaving a scored-looking empty dashboard.
          setScan(null); resetScanScopedState()
          setScanUnavailable({ scanId: badId, reason: e?.detail?.reason || '', recoveredTo: null, recovered: true })
          setView((v) => (me?.allow && !me.allow.includes('discover') ? v : 'discover'))
        }
      } finally {
        recoveringRef.current = false
      }
    }
    window.addEventListener('acp:scan-unavailable', onUnavailable)
    return () => window.removeEventListener('acp:scan-unavailable', onUnavailable)
  }, [scan?.run?.id, me?.allow]) // eslint-disable-line react-hooks/exhaustive-deps

  if (!me) return <SignIn onSignedIn={signIn} notice={signedOutReason} />   // SignIn's own BuildStamp shows the full CalVer

  const switchScan = async (id) => {
    if (id === scan?.run?.id) return
    setScanLoading(true)
    try {
      setScan(await getScan(id))
      // Cleared BEFORE the hydration effect refills decisions/triage for the scan being opened,
      // so the gap between the two never shows the previous scan's marks as if they were this
      // one's. The prior scan keeps its own copy — decisions and triage are persisted per scan
      // server-side and re-fetched on every switch, which is what makes time-travel lossless
      // even for a run nobody finished.
      resetScanScopedState()
    } catch { /* leave current scan */ } finally { setScanLoading(false) }
  }

  const doScan = async (source, folder = null) => {
    if (busy) return                              // a scan/assessment is already running — don't launch another
    setBusy(true); setErr(null); setProgress({ phase: 'queued' })
    const prevAvg = scan?.run?.avg_score
    // SIM: sim functions handle any source string synthetically.
    // Real: map to a backend-valid source based on what tokens are present.
    const wantDrive = source === 'drive' || source === 'all'
    const wantSP = source === 'sharepoint'
    const apiSource = SIM ? source : (
      wantSP && hasSPToken ? 'sharepoint' :
      wantDrive && hasDriveToken ? 'drive' :
      'local'
    )
    try {
      let fresh
      if (queuedScan) {
        // Durable path: enqueue a scan job, then poll until the scan is persisted.
        const { scan_id, workers, worker_tier_alive } = await startScanQueued(apiSource, folder, aiEnabled, deepScan, excludeRemediated, incremental)
        // Split topology (#113): the API's local pool is 0 by design — the standalone worker
        // container's heartbeat is what proves the queue is manned.
        if (!SIM && !workers && !worker_tier_alive) throw new Error('no workers available — the worker service looks down; check Monitor')
        setLiveScanId(scan_id)
        const t0 = Date.now()
        let misses = 0
        for (let i = 0; i < 600 && !fresh; i++) {        // up to ~10 min for large estates
          await new Promise((r) => setTimeout(r, 1000))
          // Fan-out scans create the row early with status 'running' and bump files_done as each
          // per-file job lands, so we can show the REAL count ("Analysing documents · 3/5") off
          // the scan row itself — no fabricated phase, no timer-driven bar.
          const elapsed = Math.round((Date.now() - t0) / 1000)
          let g = null
          try { g = await getScan(scan_id); misses = 0 } catch { g = null; misses++ }
          // A deploy mid-scan drops this tab's identity; the owner-scoped lookup then 404s
          // FOREVER (found live 2026-07-11: silent console spam, banner wedged on
          // "Connecting…"). Persistent misses → say what happened instead of spinning.
          if (misses >= 8) {
            window.dispatchEvent(new CustomEvent('acp:session-expired', { detail: { reason:
              'The app was updated and this tab’s session ended. Sign in again — your scan kept running server-side and will be here when you return.' } }))
            return
          }
          setProgress(g ? queuedProgress(g, elapsed) : { phase: 'connecting', elapsed })
          if (g && g.run && g.run.status !== 'running') fresh = g
        }
        if (!fresh) throw new Error('scan still processing — watch it finish in the Monitor queue')
      } else {
        const { job_id } = await startScan(apiSource, folder, aiEnabled, deepScan, excludeRemediated, incremental)
        let job
        do {
          await new Promise((r) => setTimeout(r, 350))
          job = await getJob(job_id)
          setProgress(job)
        } while (!job.done)
        if (job.error) throw new Error(job.error)
        fresh = await getScan(job.scan_id)
      }
      setScan(fresh)
      // A re-scan is a new run, so nothing from the last one carries into it. The previous scan
      // is NOT lost — it stays in scan_runs and stays selectable in Time-travel, with its own
      // decisions and triage, however far through the workflow it got.
      resetScanScopedState()
      setScanList(await listScans())
      const newAvg = fresh.run.avg_score
      if (prevAvg != null && newAvg != null && newAvg !== prevAvg) { setDelta(newAvg - prevAvg); setDeltaKey((k) => k + 1) }
      // Guide the user into the workflow: land on Discover (step 1) after a scan.
      setView(me?.allow && !me.allow.includes('discover') ? 'overview' : 'discover')
    } catch (e) { setErr(`scan failed: ${e}`) } finally { setBusy(false); setProgress(null); setLiveScanId(null) }
  }

  // Reconnect to an in-flight scan after a page reload — the durable fan-out keeps
  // running server-side, so we just resume polling until it finishes.
  const reconnectScan = async (scan_id) => {
    setBusy(true); setProgress({ phase: 'connecting', elapsed: 0 }); setLiveScanId(scan_id)
    const t0 = Date.now()
    let fresh
    try {
      let misses = 0
      for (let i = 0; i < 600 && !fresh; i++) {
        await new Promise((r) => setTimeout(r, 1500))
        const elapsed = Math.round((Date.now() - t0) / 1000)
        let g = null
        try { g = await getScan(scan_id); misses = 0 } catch { g = null; misses++ }
        // Same deploy-dropped-identity guard as doScan: persistent owner-scoped 404s mean
        // this tab can no longer see its scan — say so instead of spinning forever.
        if (misses >= 8) {
          window.dispatchEvent(new CustomEvent('acp:session-expired', { detail: { reason:
            'The app was updated and this tab’s session ended. Sign in again — your scan kept running server-side and will be here when you return.' } }))
          return
        }
        setProgress(g ? queuedProgress(g, elapsed) : { phase: 'connecting', elapsed })
        if (g && g.run && g.run.status !== 'running') fresh = g
      }
      // Same reset as doScan. Usually a no-op — a reconnect follows a page reload, where React
      // state started empty anyway — but this runs from a startup effect that can land while a
      // different scan is already on screen, and a fourth path that resets a different subset is
      // exactly how the three before it drifted apart.
      if (fresh) { setScan(fresh); resetScanScopedState(); setScanList(await listScans()); setView('overview') }
    } catch { /* best-effort reconnect */ }
    finally { setBusy(false); setProgress(null); setLiveScanId(null) }
  }

  const run = scan?.run

  const trendData = [...scanList].reverse().filter((s) => s.avg_score != null)
    .map((s) => ({ score: s.avg_score, label: s.completed_at ? new Date(s.completed_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) : '' }))
  const trend = trendData.map((d) => d.score)
  const trendDates = trendData.map((d) => d.label)
  // Decisions ratified on the Discover action plan, rolled up by effective action
  // so they can flow into Remediate (queue) and Report (evidence).
  const ratified = files.reduce((acc, f) => {
    const d = decisions[f.file]; if (!d || d.state === 'rejected') return acc
    const action = d.state === 'override' ? d.action : f.rec?.action
    if (!action) return acc
    acc[action] = (acc[action] || 0) + 1; acc.total += 1
    return acc
  }, { auto: 0, assisted: 0, review: 0, archive: 0, keep: 0, manual: 0, total: 0 })
  const placeholder = loaded ? <EmptyState onScan={doScan} busy={busy} hasDriveToken={hasDriveToken} hasSPToken={hasSPToken} /> : <Loading />
  // The scan panel renders inside whichever view is open, so scope its narration to that view
  // when the view is a pipeline step that owns scan phases. The view ids ARE the step names in
  // PHASE_STEP ('discover', 'assess'); anything else is a non-step view and narrates the job.
  const narrationStep = NARRATION_STEPS.has(view) ? view : null
  // Presentation decouple: results views stay blank until the user runs Assess. The flag
  // is persisted on the scan (assessed_at); justAssessed gives an immediate optimistic flip.
  const assessed = !!run?.assessed_at || justAssessed === run?.id
  const assessGate = <AssessGate onGo={() => { setView('assess'); window.scrollTo({ top: 0, behavior: 'smooth' }) }} />
  // Time-travel = viewing any scan other than the latest. Drives the replay banner + the
  // app-wide "replaymode" tint so it's unmistakable you're looking at a past point in time.
  // Time-travel = viewing a PAST scan. "Not the newest entry in the picker" is not the same
  // thing, and the difference is visible: listScans() returns only runs with a completed_at,
  // so a run that is still in flight — or an ADR 0020 Discover-only run, whose status leaves
  // 'running' the moment discovery ends — is absent from scanList entirely and satisfied the
  // old `scanList[0]?.id !== run.id` test. The banner then announced a replay of the NEWEST
  // scan and rendered "viewing the scan from ." with no date, because there was no
  // completed_at to format. Worse than cosmetic: isTimeTravel also drives readOnly on
  // Remediate/Publish/Monitor, so a freshly-discovered estate came up locked.
  // Requiring membership in scanList is what makes this mean "a past scan" — completed_at is
  // then guaranteed present, since that is exactly what listScans() filters on.
  const isTimeTravel = !!(run && scanList.some((s) => s.id === run.id) && scanList[0]?.id !== run.id)


  return (
    <div className={`app${isTimeTravel ? ' replaymode' : ''}`}>
      <a className="skiplink" href="#main-content">Skip to main content</a>
      <header>
        <div className="brand"><Logo /><h1 className="sub">Accessibility Platform</h1>
          {/* The version's DATE is Pacific (deploy.sh BUILD_TZ); fmtStamp renders the build
              instant in the viewer's zone. Tag it so the two never read as contradictory. */}
          <span className="muted" title={`Version dated in Pacific time · built ${fmtStamp(__BUILD_TIME__)} (your local time)`}
                style={{ fontSize: 11, marginLeft: 10, fontFamily: 'ui-monospace, monospace', whiteSpace: 'nowrap' }}>
            {void tick}v{platformVersion || __BUILD_VERSION__} PT · updated {timeAgo(__BUILD_TIME__)}
          </span>
        </div>
        <div className="userbox">
          {me.role && <span className="chip" title={me.scope}>{me.role}</span>}
          {rubric && me.allow?.includes('settings') && <span className="chip">{rubric.target} · rubric {rubric.hash.slice(0, 8)}</span>}
          {/* Global mode (applies across scanning, explanations, and remediation). The
              scan-only options (Deep scan, Queued) live on the Sources tab where you scan. */}
          <PrivateAiBadge aiEnabled={aiEnabled} />
          <HitlBell />
          <button
            className={`ai-toggle${aiEnabled ? ' ai-toggle--on' : ''}`}
            onClick={() => setAiEnabled(v => !v)}
            title={aiEnabled
              ? 'AI is on across the whole platform — it helps explain findings and draft fixes. Click to turn AI off (rules-only mode; AI-dependent fixes route to human review).'
              : 'AI is off — everything runs on the deterministic rules engine only. Click to turn AI back on.'}
            aria-pressed={aiEnabled}>
            {aiEnabled ? '✦ AI on' : '◻ AI off'}
          </button>
          <span className="user">{me.email}</span>
          {me.allow?.includes('settings') && <button className="cogbtn" aria-label="Platform settings" title="Platform settings" onClick={() => setSettingsOpen(true)}>⚙</button>}
          <button className="ghost small" onClick={() => {
            clearAllTokens()
            clearActivityStorage()
            // Hard reload guarantees a 100% fresh in-memory state for whoever signs in next
            // on this browser — no scan, decisions, assess phase, or files survive.
            try { sessionStorage.clear() } catch { /* ignore */ }
            window.location.reload()
          }}>sign out</button>
        </div>
      </header>
      {me.scope && <div className="scopebar"><i className="scopedot" />access scope · <b>{me.scope}</b></div>}

      <nav aria-label="Compliance workflow">
        <div className="tabs" role="tablist" aria-label="Compliance workflow">
          {TABS.filter(([k]) => !me.allow || me.allow.includes(k)).map(([k, label, rg, step]) => {
            const stageDone = {
              discover: !!run,
              assess: assessed,
              remediate: files.some((f) => f.remediated_at || f.drive_write_url),
              publish: (publishedFiles?.length || 0) > 0,
              monitor: (publishedFiles?.length || 0) > 0,
            }
            const done = !!stageDone[k] && view !== k
            // While a scan/assessment is running, lock the OTHER numbered workflow steps: jumping
            // to Assess mid-scan would show the previous scan's data, not the one in flight. The
            // current view + the utility tabs (step 0) stay reachable.
            const locked = busy && step > 0 && view !== k
            return (
              <button key={k} role="tab" aria-selected={view === k}
                      aria-current={view === k ? 'step' : undefined}
                      disabled={locked}
                      title={locked ? 'A scan or assessment is running — this step opens when it finishes' : rg}
                      className={`tab${view === k ? ' on' : ''}${done ? ' done' : ''}${step ? ' stepTab' : ''}${locked ? ' locked' : ''}`}
                      onClick={() => setView(k)}>
                {step > 0 && <span className="stepnum" aria-hidden="true">{done ? '✓' : step}</span>}
                <span className="tablbl">{done && <span className="vh">completed: </span>}{label}</span>
                <span className="rg">{rg}</span>
                {k === 'remediate' && hitlCount > 0 && <span title={`${hitlCount} document${hitlCount !== 1 ? 's' : ''} awaiting your review`} style={{ marginLeft: 6, fontSize: 10.5, fontWeight: 700, minWidth: 16, height: 16, lineHeight: '16px', textAlign: 'center', padding: '0 5px', borderRadius: 9, background: '#B4690E', color: '#fff', display: 'inline-block' }}>{hitlCount}</span>}
              </button>
            )
          })}
        </div>
      </nav>
      <div className="runinfo">
        {scanList.length > 0 && (
          <div className="runinfo-stamp">
            <span className="runinfo-ago" title={fmtStamp(run?.completed_at)}>
              {void tick /* re-render every minute */}
              {timeAgo(run?.completed_at) ?? '—'}
            </span>
            <span className="runinfo-abs">{fmtStamp(run?.completed_at) ?? '—'}</span>
            {run?.source && <span className="runinfo-source">{run.source}</span>}
            {run?.files != null && <span className="muted">{run.files.toLocaleString()} documents</span>}
          </div>
        )}
        {scanList.length > 1 && (
            <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12 }}>
              <span className="muted" title="Time-travel — pick any past scan and every tab, dashboard and score reflects that point in time">🕐 Time-travel:</span>
              <select
                value={scan?.run?.id || ''}
                onChange={(e) => switchScan(e.target.value)}
                disabled={scanLoading || busy}
                aria-label="Select scan run"
                style={{ fontSize: 12, padding: '2px 6px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--surface)', color: 'inherit', cursor: 'pointer' }}
              >
                {scanList.map((s, i) => (
                  <option key={s.id} value={s.id}>
                    {i === 0 ? '★ ' : ''}{new Date(s.completed_at).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}
                    {s.avg_score != null ? ` · ${s.avg_score}/100` : ''}
                    {' · '}{timeAgo(s.completed_at)}{i === 0 ? ' · latest' : ''}
                  </option>
                ))}
              </select>
              {scanLoading && <span className="spinner" />}
            </label>
          )}
          {run && (Object.keys(decisions).length + Object.keys(triage).length) > 0 && (
            <span className="muted" style={{ marginLeft: 12, fontSize: 12, color: '#3B6D11', whiteSpace: 'nowrap' }}
                  title="Your triage + remediation decisions are saved to this scan and restored when you time-travel back to it">
              ✓ {Object.keys(decisions).length + Object.keys(triage).length} decision{(Object.keys(decisions).length + Object.keys(triage).length) !== 1 ? 's' : ''} saved
            </span>
          )}
      </div>

      {isTimeTravel && (
        <div className="ttbanner" role="status">
          {/* fmtStamp returns null for a missing stamp; the guard on isTimeTravel means that
              can no longer happen here, but the fallback stays so a null can never again
              render as a bold empty span followed by a bare period. */}
          <span style={{ fontSize: 13.5 }}>🕐 <b>Time-travel replay</b> — viewing the scan from <b>{fmtStamp(run.completed_at) ?? 'an earlier scan'}</b>{run.avg_score != null ? ` · ${run.avg_score}/100` : ''}. Every tab, the dashboard and your saved decisions reflect this past scan.</span>
          <button className="ttexit" onClick={() => switchScan(scanList[0].id)}>↩ Back to latest</button>
        </div>
      )}

      {err && <div className="err" role="alert">{err}</div>}
      {scanUnavailable && (
        <div className="err" role="alert">
          <span>{scanUnavailable.reason}</span>{' '}
          {scanUnavailable.recoveredTo
            ? <span>Showing your most recent scan instead.</span>
            : scanUnavailable.recovered
              ? <span>You don’t have a scan of your own yet — run one from <b>Discover</b> to get a score.</span>
              : <span>Looking for a scan you can open…</span>}
          <button className="ghost small" style={{ marginLeft: 10 }}
                  onClick={() => setScanUnavailable(null)}>Dismiss</button>
        </div>
      )}
      {busy && progress && (
        <div className="scanprog" role="status" aria-live="polite">
          <div className="scanprogline"><span className="spinner" />
            <span style={{ fontWeight: 700, color: '#BF8C00', marginRight: 6 }}>Scan</span>{progressText(progress)}
            {progress.files_found ? <span className="scancount"> · {progress.files_found.toLocaleString()} files</span> : null}
            {progress.blocked ? <span className="lockwarn"> · 🔒 {progress.blocked} password-protected / couldn’t open</span> : null}
            {/* Stop (found live 2026-07-11: there was no way out of a wedged scan). Cancelling
                kills the outstanding jobs server-side; the poll loop then sees the run leave
                'running' and exits normally. Files already analysed are kept. */}
            {liveScanId && (
              <button className="ghost small" style={{ marginLeft: 'auto' }}
                      title="Stop this scan — files already analysed are kept"
                      onClick={() => cancelScan(liveScanId).catch(() => {})}>■ Stop scan</button>
            )}
          </div>
          <div className="track"><i style={{ width: `${progressPct(progress)}%`, background: '#BF8C00', transition: 'width .3s' }} /></div>
          {/* Narrate the phase the scanner reports, or say nothing. The old line came from a
              timer, so it could never be absent — and it was wrong whenever the timer and the
              phase disagreed. Silence beats a plausible sentence.

              This panel sits ABOVE <main>, so it renders inside whichever step the user is
              looking at — which is how `analysing`'s line ("Extracting text, images and document
              structure…") came to sit under the Discover tab, whose own subtitle is
              "inventory · classify". Pass the step so the narration is scoped to the screen it
              is actually on: on a step that does not own the phase, phaseNarration.js says that
              the work is running and where its output lands, instead of describing work that
              step is not doing. On a non-step view (Overview, Integrations) there is no step to
              scope to, so the line narrates the job — which is what it is. */}
          {scanPhaseLine(progress.phase, { deepScan, step: narrationStep }) && (
            <div className="muted" style={{ marginTop: 6, fontSize: 12 }}>
              {scanPhaseLine(progress.phase, { deepScan, step: narrationStep })}
            </div>
          )}
        </div>
      )}

      <main id="main-content" tabIndex={-1}>
      <ErrorBoundary key={view}>
        {/* onScan/busy/tokens are threaded so Overview can offer the scan-scope editor after a
            scan exists. Before one, `placeholder` (EmptyState → ScanSetup) is the whole screen;
            without these the editor would still be reachable exactly once per workspace. */}
        {view === 'overview' && (run ? (assessed ? <Overview run={run} files={files} trend={trend} trendDates={trendDates} onGo={setView} scanList={scanList} onPickScan={switchScan} me={me} onScan={doScan} busy={busy} hasDriveToken={hasDriveToken} hasSPToken={hasSPToken} /> : assessGate) : placeholder)}

        {view === 'integrations' && <Integrations sources={sources} files={files} scans={scanList} onScan={doScan} busy={busy} hasDriveToken={hasDriveToken} hasSPToken={hasSPToken} onConnect={handleConnect}
          deepScan={deepScan} setDeepScan={setDeepScan} queuedScan={queuedScan} setQueuedScan={setQueuedScan}
          excludeRemediated={excludeRemediated} setExcludeRemediated={setExcludeRemediated}
          incremental={incremental} setIncremental={setIncremental} scanId={run?.id} />}

        {view === 'discover' && <Discover sources={sources} files={files} busy={busy} onScan={doScan} hasDriveToken={hasDriveToken} hasSPToken={hasSPToken} delegations={delegations} fileTypeConfig={fileTypeConfig} onAdvance={() => { setView('assess'); window.scrollTo({ top: 0, behavior: 'smooth' }) }} progress={progress} scanPct={busy ? progressPct(progress) : 0} scanId={run?.id} scope={run?.scope || null} decisions={decisions} setDecisions={setDecisions}
          /* Upload lost its top-level tab in the v2 simplification, but not its capability:
             it is a secondary action inside Discover now, which is where "get files in front
             of ACP" already lives. Dropping it outright would have removed the only way to try
             a single ad-hoc file without wiring a whole source. */
          me={me} onCertified={(e) => setCertifiedDocs((c) => [{ file: e.file, id: c.length + 1 }, ...c].slice(0, 12))} />}

        {view === 'assess' && (run ? (
          <>
            <AssessRunner key={run.id} files={files} runId={run.id} scanBusy={busy} onAssessed={() => setJustAssessed(run.id)} onPhase={setAssessPhase} />
            {/* Gated on assessPhase === 'done', not just `assessed` — `assessed` flips true the
                instant Assess is clicked (before AssessRunner's own progress animation even
                starts), so the results below were popping in fully-populated while the bar
                above still pretended to be working. assessPhase tracks AssessRunner's actual
                idle/running/done state (via onPhase), so results now appear exactly when the
                animation finishes — same instant a real assessment would land. */}
            {assessed && assessPhase === 'done' && <><AccessibilityStatus scanId={run.id} onAction={(state) => { setView(state === 'ready_for_certification' || state === 'certified' ? 'publish' : 'remediate'); window.scrollTo({ top: 0, behavior: 'smooth' }) }} /><ConfidenceDashboard scanId={run.id} /><CoverageScorecard files={files} /><RuleBreakdown scanId={run.id} files={files} /><Dashboard run={run} files={files} trend={trend} delta={delta} deltaKey={deltaKey} scanList={scanList} onPickScan={switchScan} /></>}
            {assessed && assessPhase === 'done' && <RiskScore run={run} files={files} />}
          </>
        ) : placeholder)}

        {view === 'remediate' && (run ? <Remediate run={run} files={files} decisions={decisions} setDecisions={setDecisions} triage={triage} setTriage={setTriage} aiEnabled={aiEnabled} readOnly={isTimeTravel} onRefresh={() => getScan(run.id).then(setScan).catch(() => {})} onHitlCount={setHitlCount} onNavigate={(v) => { setView(v); window.scrollTo({ top: 0, behavior: 'smooth' }) }} /> : placeholder)}

        {view === 'publish' && (run ? <Publish run={run} files={files} certified={certifiedDocs} readOnly={isTimeTravel} triage={triage} onPublish={(file) => { setPublishedFiles((s) => [...s, file]); schedulePublishRefetch() }} me={me} /> : placeholder)}

        {view === 'monitor' && (run ? (assessed ? <Monitor me={me} run={run} scanList={scanList} sources={sources} files={files} ratified={ratified} decisions={decisions} publishedFiles={publishedFiles} readOnly={isTimeTravel} aiEnabled={aiEnabled} onAiToggle={setAiEnabled} busy={busy} progress={progress} scanPct={busy ? progressPct(progress) : 0} /> : assessGate) : placeholder)}


        {/* Standalone Knowledge Graph — was nested inside Assess (findable only after
            scrolling past the score/dashboard); now its own tab so it's directly
            reachable for open-ended exploration, same as Upload. Still needs an
            assessed scan (the graph visualizes WCAG findings), so it shares Monitor's
            gate: assessGate when a scan exists but hasn't been assessed yet. */}
        {view === 'graph' && (run ? (assessed ? <Suspense fallback={<Loading />}><KnowledgeGraph files={files} scanId={run.id} /></Suspense> : assessGate) : placeholder)}

        {/* Guided workflow: a "next step" CTA on each workflow tab once a scan exists.
            'discover' is excluded — it owns a sub-step CTA (Inventory → Classify → Actions → Assess). */}
        {run && ['integrations', 'assess', 'remediate', 'publish'].includes(view) && (() => {
          const flow = ['integrations', 'discover', 'assess', 'remediate', 'publish', 'monitor']
          const label = { discover: '1 · Discover — classify the estate', assess: '2 · Assess — score vs WCAG',
                          remediate: '3 · Remediate — fix the issues', publish: '4 · Publish — certify what passes',
                          monitor: '5 · Monitor — keep it compliant' }
          let nxt = null
          for (let j = flow.indexOf(view) + 1; j < flow.length; j++) {
            if (!me.allow || me.allow.includes(flow[j])) { nxt = flow[j]; break }
          }
          // Same "is this tab's task done" signal the tab stepper uses — the CTA can't
          // advance until the current tab's own work is actually finished.
          const taskDone = {
            integrations: !!run,
            assess: assessed,
            remediate: files.some((f) => f.remediated_at || f.drive_write_url),
            publish: (publishedFiles?.length || 0) > 0,
          }[view]
          return nxt ? (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 12,
                          margin: '20px 0 4px', paddingTop: 14, borderTop: '1px solid var(--line)' }}>
              <span className="muted" style={{ fontSize: 13 }}>
                {taskDone ? 'Done here? Continue →' : 'Finish this step to continue →'}
              </span>
              <button disabled={!taskDone}
                      title={taskDone ? undefined : "Complete this tab's task before moving on"}
                      onClick={() => { setView(nxt); window.scrollTo({ top: 0, behavior: 'smooth' }) }}>{label[nxt]} →</button>
            </div>
          ) : null
        })()}
      </ErrorBoundary>
      </main>

      <ChatWidget files={files} run={run} trend={trend} trendDates={trendDates} me={me} />
      {SHOW_A11Y && <A11ySelfCheck />}
      {/* onOntologyChange / onPrivilegeChange are gone with the Business ontology and Permissions
          panels. The ontology DATA path below is untouched — App still annotates the corpus from
          whatever was last published; only its editor left Settings. */}
      {settingsOpen && me.allow?.includes('settings') && <Settings files={files} onClose={() => setSettingsOpen(false)} onRubricSaved={() => getRubric().then(setRubric)} onDelegationChange={setDelegations} onFileTypeChange={(cfg) => setFileTypeConfig(cfg)} />}
    </div>
  )
}
