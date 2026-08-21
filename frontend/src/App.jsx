import { useEffect, useState, useMemo, useCallback, useRef, lazy, Suspense } from 'react'
import HitlBell from './HitlBell.jsx'
import { assessmentLine, outcomesFromRun, outcomeChips } from './assessmentProgress.js'
import LiveAssessmentLive from './LiveAssessmentLive.jsx'
import ProcessingDetails from './ProcessingDetails.jsx'
import ScopeFunnel from './ScopeFunnel.jsx'
import { armNotifyOnComplete, notifyScanComplete, notificationsSupported, notifyPermission } from './scanNotify.js'
import { refreshDriveToken } from './driveAuth.js'
import PrivateAiBadge from './PrivateAiBadge.jsx'
import { getSources, getRubric, getConfig, getMe, getCapability, listScans, getScan, getActiveScan, startScan, startScanQueued, cancelScan, getJob, setDriveToken, setSPToken, setGoogleToken, setMsToken, clearAllTokens, getDecisions, saveDecisionsBatch, refreshScanDriveToken, getScanLocations, SESSION_EXPIRED } from './api'
import { SIM } from './sim.js'
import { setPersona, recommendFor } from './sim.js'
import { loadDelegations } from './OwnerDelegate.jsx'
import { loadRolePrivileges } from './RolePrivilege.jsx'
import { loadFileTypeConfig, visibleForFileTypes } from './FileTypeConfig.jsx'
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
import AssessSetup from './AssessSetup.jsx'
import AssessFileFindings from './AssessFileFindings.jsx'
import { inventorySnapshot } from './discoverRunTime.js'
import AssessSummary from './AssessSummary.jsx'
import AssessWorklist from './AssessWorklist.jsx'
import { documentRows } from './assessMetrics.js'
import RunDetails from './RunDetails.jsx'
import Integrations from './Integrations.jsx'
import Discover from './Discover.jsx'
import Dashboard from './Dashboard.jsx'
import { CAPABILITY_FALLBACK, ASSESSMENT_FALLBACK } from './capability.js'
import Remediate from './Remediate.jsx'
import EmptyState, { Loading } from './EmptyState.jsx'
import ScanReviewModal from './ScanReviewModal.jsx'
import ErrorBoundary from './ErrorBoundary.jsx'
import { applyScopeConfig } from './activeScope.js'
import A11ySelfCheck from './A11ySelfCheck.jsx'
import { scanPhaseLine, NARRATION_STEPS, activityLine } from './phaseNarration.js'
import { useScanRefetch } from './scanRefetch.js'
import { pickDefaultScan } from './defaultScan.js'

// Self-scan overlay: on in dev, or on the deployed demo via ?a11y
const SHOW_A11Y = import.meta.env.DEV || (typeof location !== 'undefined' && new URLSearchParams(location.search).has('a11y'))

// step=0 → utility tab (no number); step>0 → workflow step with numbered badge
const TABS = [
  ['overview',      'Overview',      'at a glance',         0],
  ['integrations',  'Sources',       'connect sources',     0],
  ['discover',      'Discover',      'inventory · classify', 1],
  ['assess',        'Assess',        'score vs WCAG',       2],
  ['remediate',     'Remediate',     'fix issues',          3],
  ['publish',       'Release',       'approve & deploy',    4],
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
  // viewers (you in PT, a teammate in CT) can tell at a glance it's THEIR local time.
  return new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit', timeZoneName: 'short' })
}

function progressText(p) {
  if (!p) return ''
  // The two long, per-file phases now show the OUTCOME-oriented line — how much is done (with saved
  // results), how fast, how long left — instead of "Reading files · 145/250 · one-filename". Multiple
  // files are processed at once, so a single in-flight filename is not the honest signal; the count is
  // (see assessmentProgress.js). The earlier phases keep their plain status label.
  if ((p.phase === 'reading' || p.phase === 'analysing') && p.files_found) {
    return assessmentLine(p)
  }
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

// Semantic colours for the live outcome chips (passed / need-review / failed / processing). Kept as a
// small style map so the chip row needs no new CSS and reads the same in light contexts.
const OCHIP_STYLE = {
  ok: { color: '#2F7D51', background: '#E6F2EA' },
  warn: { color: '#9A6011', background: '#F7EDDB' },
  bad: { color: '#A5314A', background: '#F9E7EB' },
  muted: { color: '#54636F', background: '#ECEFF4' },
}


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
  // Outcome tally, streamed live off the run summary (certifiable/uncertain/error, derived from
  // file_records as each file lands) — so the progress chips show real state, not just a counter.
  // `files` carries the per-file results get_scan streams, for the expandable Processing details table.
  return { phase, files_found: total, files_done: done, current: null, elapsed, pct,
           outcomes: outcomesFromRun(run), files: (g && g.files) || [],
           inventory: (run && run.scope && run.scope.inventory) || null }
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

  // The two capability tables `AssessSummary` counts over. Held HERE rather than fetched inside
  // the summary so the component stays pure — its own test forbids it deriving anything, because a
  // component that recomputes is how a fifth denominator arrives.
  //
  // The fallbacks are the synchronous default, exactly as AssessRunner uses them: they mirror the
  // Python tables verbatim and are CI-locked to them, so the numbers are right before the fetch
  // resolves and right after. A failed fetch leaves the fallback in place rather than emptying the
  // map — an empty capability map would read every criterion as "no method", which is the same
  // false verdict as a zero.
  // Run details is a sub-view of Assess, not a tab. It holds the capability reference, the
  // "no method" explanation and the scan traces — reachable from the summary, returned from, and
  // deliberately absent from the primary navigation, which is where engineering diagnostics were
  // not supposed to be.
  const [runDetails, setRunDetails] = useState(false)
  // The worklist ROW a reader opened, for the findings-by-criterion view. It holds the row rather
  // than the file so the view renders the same derivation the list was ordered by.
  //
  // This used to open FileDrawer, with a note saying the dedicated view "replaces this when it
  // lands". It landed in #546 and sat unmounted; that note is now history rather than a plan.
  const [assessFile, setAssessFile] = useState(null)
  // AssessRunner still owns the run; AssessSetup owns the button that starts it. The runner hands
  // its start function here on mount. Stable identity via useCallback, so registering does not
  // re-fire on every render of this very large component.
  const assessStart = useRef(null)
  const registerAssessStart = useCallback((fn) => { assessStart.current = fn }, [])
  const [cap, setCap] = useState(CAPABILITY_FALLBACK)
  const [assessment, setAssessment] = useState(ASSESSMENT_FALLBACK)
  useEffect(() => {
    let on = true
    getCapability().then((r) => {
      if (!on) return
      if (r?.capability) setCap(r.capability)
      if (r?.assessment) setAssessment(r.assessment)
    }).catch(() => { /* the fallbacks stand */ })
    return () => { on = false }
  }, [])
  const [scanLoading, setScanLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [view, setView] = useState('overview')
  const [decisions, setDecisions] = useState({})
  const [triage, setTriage] = useState({})              // per-scan triage, lifted from Remediate for time-travel
  const [assignees, setAssignees] = useState({})        // per-file assignee ({file: email}) for the "Assigned to me" inbox filter (#417 backend)
  const savedDecRef = useRef({ scanId: null, decisions: {}, triage: {}, assignees: {} })  // last-persisted snapshot
  const hydratingRef = useRef(false)                    // suppress the save effect during hydration
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [scanList, setScanList] = useState([])
  const [delta, setDelta] = useState(null)
  const [deltaKey, setDeltaKey] = useState(0)
  const [progress, setProgress] = useState(null)
  const [loaded, setLoaded] = useState(false)
  // Externally-certified documents, read by Publish. NOTHING WRITES THIS ANY MORE: its only writer
  // was the ad-hoc single-file upload panel on Discover, removed on request — and that was the
  // app's only mount of Upload, so there is no other route to it.
  //
  // Kept rather than deleted. Publish consumes it and handles an empty list (`certified = []` is
  // its default), so the effect is that externally-certified documents simply never appear there —
  // a consequence of removing upload, not a fault. Keeping the state means restoring the panel is
  // one commit; deleting it would widen a removal into a refactor.
  //
  // The SETTER is still bound because the workspace reset at `resetWorkspace` clears it along with
  // everything else. Dropping it from this destructure made that call a ReferenceError — caught
  // here rather than at runtime, which is the whole reason to look at who else touches a symbol
  // before narrowing it.
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
  const [queuedScan, setQueuedScan] = useState(false)  // session-scoped is the pilot default; opt into Durable (background queue) via the switch
  const [deepScan, setDeepScan] = useState(false)      // off by default → Fast scan; opt in to PII scan via the switch
  const [excludeRemediated, setExcludeRemediated] = useState(true)  // on by default — skip re-discovering ACP's own Remediated/ output
  // ADR 0011 skips re-analysing byte-identical files already scored under the same rubric. OFF by
  // default from 2026-08-19: every switch in this group now starts off, so the scan a user gets
  // without touching anything is the plainest one — nothing skipped, nothing inferred, and the
  // four toggles read as additions to a known baseline rather than as a mix whose starting state
  // has to be checked. Opting IN to the skip is the deliberate act; it is a speed and cost
  // optimisation, and a stale score kept by a skip is harder to notice than a slow scan.
  //
  // `exclude_remediated` deliberately stays ON and is NOT part of this: off, ACP re-discovers its
  // own Remediated/ output as source documents, which inflates the file count and shows
  // "remediated ✓" on a scan that remediated nothing (provenance.py). That is a wrong number
  // pointing at MORE coverage, which is the direction nobody checks.
  const [incremental, setIncremental] = useState(false)
  // The in-flight durable scan's id — what the banner's Stop button cancels. null when
  // no queued scan is being polled (sync scans finish in-request and can't be stopped).
  const [liveScanId, setLiveScanId] = useState(null)
  // "Notify me when complete" (slice 3c): the button drives `notifyArmed` for its label; the ref is what
  // the async scan-completion code reads, since it fires long after this render's closure was captured.
  const [notifyArmed, setNotifyArmed] = useState(false)
  const notifyArmedRef = useRef(false)
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
  // Ownership of the platform `scan_scope` setting (PUT /settings is owner-only). null = unknown
  // until /config reports `is_scope_owner`. Fail-open: unknown/absent leaves scope editing enabled
  // (current behavior); only an explicit `false` gates a non-owner to a read-only scope wizard.
  const [scopeOwner, setScopeOwner] = useState(null)
  // Universal scan gate: `{ source, folder }` while the app-level review modal is open. Declared
  // with the other hooks (above the `!me` early return) so the hook order never changes.
  const [pendingScan, setPendingScan] = useState(null)

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
      // Ownership of the owner-only `scan_scope` setting. Only trust an explicit boolean; a build
      // whose backend predates this field leaves `scopeOwner` null → scope editing stays enabled.
      if (typeof c?.is_scope_owner === 'boolean') setScopeOwner(c.is_scope_owner)
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

  // Deep-link into Settings from anywhere in the app (P1: the review card's empty-state honesty hint
  // points an admin at Settings → AI Providers). Reuses the same custom-event pattern as
  // acp:session-expired / acp:scan-unavailable rather than threading a callback through the tree.
  // Gated on the settings permission exactly as the ⚙ button and the modal render already are.
  useEffect(() => {
    const onOpenSettings = () => { if (me?.allow?.includes('settings')) setSettingsOpen(true) }
    window.addEventListener('acp:open-settings', onOpenSettings)
    return () => window.removeEventListener('acp:open-settings', onOpenSettings)
  }, [me])

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
        // Default to the newest NON-collapsed scan, not blindly the newest: a degenerate small
        // scan on top would otherwise make every view show a shrunken estate (see defaultScan.js).
        setScanList(l); const d = pickDefaultScan(l); if (d) setScan(await getScan(d.id))
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
  const allFiles = useMemo(() => annotate(scan?.files ?? [], ontology).map((f) => (f.rec ? f : { ...f, rec: recommendFor(f) })), [scan, ontology])

  // The file-type filter applies to EVERY tab, not just Discover.
  //
  // It used to be filtered inside Discover alone (`visibleFiles`), so an operator who scoped the
  // scan to .docx saw a docx-only inventory and then a full estate everywhere after it: Assess
  // scored the PDFs, Remediate queued them, Overview counted them, Publish certified against
  // them. The filter looked like it worked and then silently stopped applying one tab later,
  // which is worse than not having one — every number downstream described a different
  // population than the screen the operator set it on.
  //
  // Filtered once, here, so every tab inherits the same population by construction rather than
  // by each component remembering to. `scan_scope` on the server is the other half and gates
  // which CRITERIA are evaluated; this gates which FILES are shown. Both are needed: the server
  // returns the whole estate because a scan inventories everything it can see.
  //
  // An empty config means no restriction, matching Discover's original `!== false` test — a
  // type absent from the map has never been excluded, only ones explicitly set false.
  const files = useMemo(() => visibleForFileTypes(allFiles, fileTypeConfig), [allFiles, fileTypeConfig])

  // A13 · document-to-document navigation from inside a file's findings. It walks the SAME order the
  // worklist prints — documentRows, unopened last — so "next" never disagrees with the list it came
  // from. Only opened documents are reachable: an unopened file has no findings view to move to.
  // Declared here, with the other hooks and above every early return, so its hook order is stable.
  const assessNavRows = useMemo(
    () => documentRows(files, { cap, assessment }).filter((r) => r.opened),
    [files, cap, assessment])
  const assessFileNext = useMemo(() => {
    if (!assessFile) return null
    const i = assessNavRows.findIndex((r) => r.file === assessFile.file)
    return i >= 0 && i + 1 < assessNavRows.length ? assessNavRows[i + 1] : null
  }, [assessNavRows, assessFile])
  // A5/A13 · the RAW file record behind the worklist row. `assessFile` is a documentRow — the
  // derived shape the worklist and this navigation use — which carries no size, no Drive id and no
  // timestamp. Those live only on the file record `files` itself hands out, so this looks it up by
  // the one key both shapes share.
  const assessFileRaw = useMemo(
    () => (assessFile ? files.find((f) => f.file === assessFile.file) : null),
    [assessFile, files])

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
    setDecisions({}); setTriage({}); setAssignees({})
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
    if (p.token && p.sso === 'Microsoft') {
      // Microsoft: the Entra token is the API bearer (backend verifies it via Graph /me). It is
      // ALSO the SharePoint token, wired below from sp_token — no Drive scopes on this one.
      setMsToken(p.token)
    } else if (p.token) {
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
    // Scope editing is owner-only (PUT /settings = _require_admin). GET /me returns the
    // authoritative per-user `is_scope_owner` post-auth (the sign-in payload doesn't carry it,
    // and /config is fetched pre-auth so its copy is null). A non-owner → read-only scope in the
    // review modal instead of a silently-dropped edit; fail-open (null) keeps the owner editable.
    getMe().then((m2) => { if (typeof m2?.is_scope_owner === 'boolean') setScopeOwner(m2.is_scope_owner) }).catch(() => {})
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
      const dec = {}, tri = {}, asg = {}
      Object.entries(d || {}).forEach(([file, m]) => {
        if (m.action) { try { dec[file] = JSON.parse(m.action) } catch { /* ignore */ } }
        if (m.triage) tri[file] = m.triage
        if (m.assignee) asg[file] = m.assignee
      })
      hydratingRef.current = true
      savedDecRef.current = { scanId: sid, decisions: dec, triage: tri, assignees: asg }
      setDecisions(dec); setTriage(tri); setAssignees(asg)
    }).catch(() => {
      hydratingRef.current = true
      savedDecRef.current = { scanId: sid, decisions: {}, triage: {}, assignees: {} }
      setDecisions({}); setTriage({}); setAssignees({})
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
    new Set([...Object.keys(prev.assignees || {}), ...Object.keys(assignees)]).forEach((f) => {
      if ((prev.assignees || {})[f] !== assignees[f]) items.push({ file: f, kind: 'assignee', value: assignees[f] ?? null })
    })
    if (items.length) saveDecisionsBatch(sid, items).catch(() => {})
    savedDecRef.current = { scanId: sid, decisions: { ...decisions }, triage: { ...triage }, assignees: { ...assignees } }
  }, [decisions, triage, assignees]) // eslint-disable-line react-hooks/exhaustive-deps

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

  // ── Universal scan gate ──────────────────────────────────────────────────────
  // Every scan entry point calls `requestScan` (wired as their `onScan` prop), which OPENS the
  // app-level review modal instead of scanning. The only path that actually dispatches a scan is
  // the modal's "Start scan" confirm → `doScan`. This is what makes the scope/behavior review
  // unbypassable from Discover, Overview, EmptyState/ScanSetup, the Sources tab, and the
  // Drive/SharePoint browse panels alike — before this, the modal lived inside Integrations and
  // only the Sources tab reached it. (`pendingScan` state is declared with the other hooks above.)
  const requestScan = (source, folder = null) => setPendingScan({ source, folder })

  // `runScope` is the wizard's per-run folder choice ({folders, exclude}). Given, it wins over the
  // connection default below — that is what "this run only" means. Absent (a scan started without
  // the wizard), the saved connection scope is used, so a scheduled or card-launched scan still
  // honours what the source is configured to cover.
  const doScan = async (source, folder = null, runScope = null) => {
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
    // THE SAVED SCOPE HAS TO REACH THE SCAN. The Sources card persists which folders a
    // connection covers, and until this it was displayed and never sent: the card said
    // "Scans: HR" and every scan still read the whole Drive. A scope that is shown but not
    // applied is worse than none — it is a boundary the user believes in.
    //
    // Read here rather than held in state so it is never stale: the card can be edited in
    // another tab between mount and scan, and one extra GET is cheaper than a scan that
    // covered something else.
    let picked = null
    let excluded = null
    if (runScope && Array.isArray(runScope.folders)) {
      picked = runScope.folders
      excluded = runScope.exclude || []
    } else if (!SIM && (apiSource === 'drive' || apiSource === 'sharepoint') && !folder) {
      try {
        const { locations } = await getScanLocations()
        picked = (locations || {})[apiSource] || []
        excluded = ((locations || {})._exclude || {})[apiSource] || []
      } catch {
        // A failed lookup must not silently widen the scan to the whole source, and must not
        // block it either. Null means "not narrowed", which is what the server already does
        // without the parameters — and the scope line on the result will say so honestly.
        picked = null; excluded = null
      }
    }

    try {
      let fresh
      if (queuedScan) {
        // Durable path: enqueue a scan job, then poll until the scan is persisted.
        const { scan_id, workers, worker_tier_alive } = await startScanQueued(apiSource, folder, aiEnabled, deepScan, excludeRemediated, incremental, picked, excluded)
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
        const { job_id } = await startScan(apiSource, folder, aiEnabled, deepScan, excludeRemediated, incremental, picked, excluded)
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
      // "Notify me when complete" (slice 3c): if the user armed it and walked away, ping them with the
      // outcome. Best-effort — notifyScanComplete never throws, so a missing notification can't fail the
      // scan it describes.
      if (notifyArmedRef.current) {
        const r = fresh.run || {}
        notifyScanComplete({ assessed: r.files_done || 0, total: r.files || 0, review: r.uncertain || 0 })
      }
      setScanList(await listScans())
      const newAvg = fresh.run.avg_score
      if (prevAvg != null && newAvg != null && newAvg !== prevAvg) { setDelta(newAvg - prevAvg); setDeltaKey((k) => k + 1) }
      // Guide the user into the workflow: land on Discover (step 1) after a scan.
      setView(me?.allow && !me.allow.includes('discover') ? 'overview' : 'discover')
    } catch (e) { setErr(`scan failed: ${e?.message ?? e}`) } finally {
      setBusy(false); setProgress(null); setLiveScanId(null)
      setNotifyArmed(false); notifyArmedRef.current = false      // one arming per run
    }
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
  // OV-02: one action, no numbers. EmptyState no longer configures anything — the criteria
  // and file-type pickers it used to render belong after an inventory exists, in Assess,
  // where the eligible-file count can be shown against them.
  const placeholder = loaded
    ? <EmptyState onGoToSource={() => { setView('integrations'); window.scrollTo({ top: 0, behavior: 'smooth' }) }} />
    : <Loading />
  // The scan panel renders inside whichever view is open, so scope its narration to that view
  // when the view is a pipeline step that owns scan phases. The view ids ARE the step names in
  // PHASE_STEP ('discover', 'assess'); anything else is a non-step view and narrates the job.
  const narrationStep = NARRATION_STEPS.has(view) ? view : null
  // Presentation decouple: results views stay blank until the user runs Assess. The flag
  // is persisted on the scan (assessed_at); justAssessed gives an immediate optimistic flip.
  const assessed = !!run?.assessed_at || justAssessed === run?.id
  // When the Assess results (summary / worklist / file / run-details) may render. Two ways to be
  // ready, and the distinction is the bug this guards: (1) the runner finished a run THIS session
  // (assessPhase 'done'); (2) the scan was assessed in a PRIOR session — persisted `assessed_at`,
  // and NOT this session's optimistic `justAssessed` flip. Case 2 is the reload: assessPhase is
  // 'idle' because AssessRunner's per-session cache is gone, so gating purely on 'done' left an
  // already-assessed scan showing an EMPTY panel (AssessSetup hidden by `assessed`, results hidden
  // by the 'done' gate). Excluding `justAssessed === run.id` keeps results hidden during the
  // click→running gap the 'done' gate was added to cover, so a fresh run still waits for the bar.
  const resultsReady = assessPhase === 'done' || (!!run?.assessed_at && justAssessed !== run?.id)
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
          {/* SWITCH ACCOUNT — a full teardown, then the sign-in screen, which now asks Google
              and Microsoft for an account chooser rather than reusing the browser's single
              signed-in session.

              It cannot be a lighter-touch "just re-pick the Drive": the ACP identity is the
              Authorization bearer (api.js sends Google's when present, else Microsoft's) and
              api/app.py stamps request.state.user_email from it, which is what per-user data
              isolation keys on. Re-minting only the Drive token would leave you signed in as one
              account while reading another's Drive, with the scans owned by the first — the
              wrong half of a switch, and invisible. So this does the same complete teardown as
              sign out and differs only in saying what it is for. */}
          <button className="ghost small" title="Sign out and choose a different Google or Microsoft account"
                  onClick={() => {
            clearAllTokens()
            clearActivityStorage()
            try { sessionStorage.clear() } catch { /* ignore */ }
            window.location.reload()
          }}>switch account</button>
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
              <span style={{ marginLeft: 'auto', display: 'inline-flex', gap: 8 }}>
                {/* Continue working — notify me when complete (slice 3c). This banner is non-modal and
                    the scan runs server-side, so a user can already work elsewhere; arming this pings
                    them with the outcome when it finishes, so they need not watch the spinner. */}
                {notificationsSupported() && notifyPermission() !== 'denied' && (
                  <button className="ghost small" disabled={notifyArmed}
                          title={notifyArmed ? 'You’ll be notified when this scan finishes'
                                             : 'Keep working — get a notification when this scan finishes'}
                          onClick={async () => {
                            const ok = await armNotifyOnComplete()
                            if (ok) { notifyArmedRef.current = true; setNotifyArmed(true) }
                          }}>
                    {notifyArmed ? '🔔 Will notify you' : '🔔 Notify me when done'}
                  </button>
                )}
                <button className="ghost small"
                        title="Stop this scan — files already analysed are kept"
                        onClick={() => cancelScan(liveScanId).catch(() => {})}>■ Stop scan</button>
              </span>
            )}
          </div>
          <div className="track"><i style={{ width: `${progressPct(progress)}%`, background: '#BF8C00', transition: 'width .3s' }} /></div>
          {/* Outcome chips — what is actually EMERGING from the run (passed / need-review / failed /
              still-processing), streamed off the run summary as files land. Shown only once analysis
              has produced a real result (outcomeChips returns [] otherwise), so they never read
              "0 · 0 · 0" during the read phase or a metadata-only discovery. */}
          {outcomeChips(progress.outcomes).length > 0 && (
            <div className="scanoutcomes" style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 8 }}>
              {outcomeChips(progress.outcomes).map((c) => (
                <span key={c.key} style={{ fontSize: 12, fontWeight: 500, padding: '2px 9px', borderRadius: 999,
                                           fontVariantNumeric: 'tabular-nums', ...OCHIP_STYLE[c.kind] }}>
                  <b>{c.count.toLocaleString()}</b> {c.label}
                </span>
              ))}
            </div>
          )}
          {/* Expandable per-file transparency — collapsed by default, so it does not force everyone to
              watch a scrolling log. Fed by the live file results get_scan streams. */}
          {/* Why 250 selected → fewer assessed: the eligibility breakdown, so fewer-assessed is
              explained, not glossed over. Same three-denominator inventory EstateCoverage uses. */}
          <ScopeFunnel inventory={progress.inventory} blocked={progress.blocked} />
          <ProcessingDetails files={progress.files} processing={progress.outcomes?.processing || 0} />
          {/* Live Assessment command center — KPIs + funnel + worker/lane, polled from /scans/{sid}/live.
              Inert until the endpoint returns an available snapshot, so it is a no-op on backends without
              it and adds nothing to the panel when there is nothing live to show. */}
          <LiveAssessmentLive scanId={liveScanId} active={busy} />
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
          {/* Under the narration, not instead of it. The line above says what the PHASE is doing
              and is identical for the whole time a long document sits in `analysing`; this one
              names the document and the criterion, which is the question someone watching a
              spinner is actually asking. Rendered only when the backend reported one — see
              activityLine, which returns null rather than inventing a plausible sentence. */}
          {activityLine(progress) && (
            <div className="muted" data-testid="scan-activity"
                 style={{ marginTop: 4, fontSize: 12, opacity: 0.85,
                          fontVariantNumeric: 'tabular-nums' }}>
              {activityLine(progress)}
            </div>
          )}
        </div>
      )}

      <main id="main-content" tabIndex={-1}>
      <ErrorBoundary key={view}>
        {/* onScan/busy/tokens are threaded so Overview can offer the scan-scope editor after a
            scan exists. Before one, `placeholder` (EmptyState → ScanSetup) is the whole screen;
            without these the editor would still be reachable exactly once per workspace. */}
        {/* The Overview grows organically across the funnel: it renders once an estate is DISCOVERED,
            not only once it is assessed, and its own sections reveal as each stage completes (the
            discovery numbers first, the assessment KPIs once Assess has run). This reverses the older
            OV-01/OV-04 gate — "Overview stays blank until assessed" — which the reveal-as-completed
            structure makes unnecessary: there is no empty-findings page to guard against any more. */}
        {view === 'overview' && (run ? <Overview run={run} files={files} trend={trend} trendDates={trendDates} onGo={setView} scanList={scanList} onPickScan={switchScan} me={me} onScan={requestScan} busy={busy} hasDriveToken={hasDriveToken} hasSPToken={hasSPToken} onFileTypeChange={setFileTypeConfig} cap={cap} assessment={assessment} /> : placeholder)}

        {view === 'integrations' && <Integrations sources={sources} files={files} scans={scanList} onScan={requestScan} busy={busy} hasDriveToken={hasDriveToken} hasSPToken={hasSPToken} onConnect={handleConnect}
          scanId={run?.id}
          onOpenAssess={() => { setView('assess'); window.scrollTo({ top: 0, behavior: 'smooth' }) }} />}

        {view === 'discover' && <Discover sources={sources} files={files} busy={busy} onScan={requestScan} hasDriveToken={hasDriveToken} hasSPToken={hasSPToken} delegations={delegations} onAdvance={() => { setView('assess'); window.scrollTo({ top: 0, behavior: 'smooth' }) }} progress={progress} scanPct={busy ? progressPct(progress) : 0} scanId={run?.id} scope={run?.scope || null} run={run} scanList={scanList} runAt={inventorySnapshot({ run, inventory: run?.scope?.inventory || null })} decisions={decisions} setDecisions={setDecisions}
          /* Upload lost its top-level tab in the v2 simplification, but not its capability:
             it is a secondary action inside Discover now, which is where "get files in front
             of ACP" already lives. Dropping it outright would have removed the only way to try
             a single ad-hoc file without wiring a whole source. */
          me={me} />}

        {view === 'assess' && (run ? (
          <>
            {/* The assessment scope lives here now (Discover/Assess PRD §4.4): document types +
                the Core-17 WCAG picker, with a live eligible-file count, written to scan_scope as
                the single authority for the format axis. Collapsed by default so it does not
                displace the run button, and left one click away for when the scope needs changing. */}
            {/* THE PRE-RUN SCREEN (approved board 2). It replaces the two collapsed scope panels
                that used to sit here. The board's footer removes the WCAG scope-rules panel
                outright, and AssessScope's document-type and criterion pickers are rows on this
                screen now - so keeping either would be the same question asked twice, in two
                places, with two answers.

                Rendered only before a run. Afterwards the results answer a different question and
                the re-run control lives with them, inside AssessRunner - which is why `controlled`
                hides the runner's pre-run band but not its results. */}
            {/* discoveredAt takes fmtStamp, NOT the raw column. AssessSetup interpolates the value
                straight into "From discovery run {discoveredAt}" and formats nothing, so passing
                run.completed_at printed an ISO timestamp across the top of the screen. fmtStamp
                also returns null for a missing value, which is exactly the prop's "omit rather
                than invent" contract — so the `|| null` this used to carry is redundant. */}
            {assessPhase === 'idle' && !assessed && (
              <AssessSetup discoveredAt={fmtStamp(run?.completed_at)} busy={busy}
                           onRun={(decided) => assessStart.current?.(decided)} />
            )}
            <AssessRunner key={run.id} files={files} runId={run.id} scanBusy={busy}
                          controlled onReady={registerAssessStart}
                          onAssessed={() => setJustAssessed(run.id)} onPhase={setAssessPhase} />
            {/* Gated on assessPhase === 'done', not just `assessed` — `assessed` flips true the
                instant Assess is clicked (before AssessRunner's own progress animation even
                starts), so the results below were popping in fully-populated while the bar
                above still pretended to be working. assessPhase tracks AssessRunner's actual
                idle/running/done state (via onPhase), so results now appear exactly when the
                animation finishes — same instant a real assessment would land. */}
            {/* ONE summary, where four panels used to lead with four counts of "problems" over
                four unstated denominators. `AccessibilityStatus` (13 needing remediation),
                `ConfidenceDashboard` (189 unresolved — which is 176 + 13 restated),
                `CoverageScorecard` (5/20, a capability fact that does not change when you run
                anything) and `RiskScore` (the score) came out. The components still exist:
                AccessibilityStatus is the per-file hero inside FileDrawer, where its denominator
                is one document and therefore unambiguous.

                RiskScore left with the score it renders. `100 − Σ severity_weight`, floored at 0,
                averaged across documents: unresolved review items and criteria with no method
                both weigh ZERO, so a document with forty findings awaiting a person scores 100
                and reads "compliant". That is the score being structurally unable to tell
                "checked and passed" from "not checked" — the one distinction this product
                exists to make. It returns when a written, versioned weighting exists that cannot
                report "good" while a critical finding is unresolved.

                `RuleBreakdown` and `Dashboard` stay: they are the by-criterion detail beneath the
                summary, not a second scoreboard above it. */}
            {/* Run details replaces the results rather than sitting under them: it answers a
                different question, and stacking it below would put a capability reference back on
                the screen whose whole problem was too many panels answering different questions
                at once. */}
            {/* ONE FILE, BY CRITERION (approved board assess-05 / A13-A18). Replaces the results
                 while it is open, exactly as RunDetails does — it carries its own Back and
                 next-document controls, which only make sense for a view that owns the screen.

                 It takes the worklist's ROW rather than the raw file, so it renders the same
                 derivation the list was ordered by; recomputing one here could disagree with the
                 list about which document needs a person first.

                 FileDrawer is not deleted — Overview still uses it. This is only about which view
                 the Assess tab opens for a document. */}
            {assessed && resultsReady && assessFile && (
              <AssessFileFindings row={assessFile} file={assessFileRaw} cap={cap} assessment={assessment}
                                  assessedAt={fmtStamp(run?.assessed_at)}
                                  onBack={() => { setAssessFile(null); window.scrollTo({ top: 0, behavior: 'smooth' }) }}
                                  onNext={assessFileNext ? () => { setAssessFile(assessFileNext); window.scrollTo({ top: 0, behavior: 'smooth' }) } : undefined}
                                  nextName={assessFileNext?.name}
                                  onRemediate={() => { setView('remediate'); window.scrollTo({ top: 0, behavior: 'smooth' }) }} />
            )}
            {assessed && resultsReady && runDetails && (
              <RunDetails scanId={run.id} files={files} cap={cap} assessment={assessment}
                          onBack={() => { setRunDetails(false); window.scrollTo({ top: 0, behavior: 'smooth' }) }} />
            )}
            {assessed && resultsReady && !runDetails && !assessFile && <><AssessSummary files={files} cap={cap} assessment={assessment} assessedAt={fmtStamp(run?.assessed_at)} run={run} notStarted={run?.not_assessed?.count} onRemediate={() => { setView('remediate'); window.scrollTo({ top: 0, behavior: 'smooth' }) }} onRunDetails={() => { setRunDetails(true); window.scrollTo({ top: 0, behavior: 'smooth' }) }} onChangeScope={() => { setView('discover'); window.scrollTo({ top: 0, behavior: 'smooth' }) }} /><AssessWorklist files={files} cap={cap} assessment={assessment} onOpenFile={(row) => setAssessFile(row)} /><RuleBreakdown scanId={run.id} files={files} /><Dashboard run={run} files={files} trend={trend} delta={delta} deltaKey={deltaKey} scanList={scanList} onPickScan={switchScan} /></>}
          </>
        ) : placeholder)}

        {view === 'remediate' && (run ? <Remediate run={run} files={files} decisions={decisions} setDecisions={setDecisions} triage={triage} setTriage={setTriage} assignees={assignees} setAssignees={setAssignees} myEmail={me?.email} aiEnabled={aiEnabled} readOnly={isTimeTravel} onRefresh={() => getScan(run.id).then(setScan).catch(() => {})} onHitlCount={setHitlCount} cap={cap} assessment={assessment} onNavigate={(v) => { setView(v); window.scrollTo({ top: 0, behavior: 'smooth' }) }} /> : placeholder)}

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
        {run && ['assess', 'remediate', 'publish'].includes(view) && (() => {
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

      {/* The universal scan gate. Opened by `requestScan` from every entry point; the wizard's
          "Start scan" confirm is the only thing that dispatches `doScan`. The behavior toggles are
          bound to the App-level state so a choice here carries into the scan that follows. */}
      {pendingScan && (
        <ScanReviewModal
          source={pendingScan.source} folder={pendingScan.folder}
          deepScan={deepScan} setDeepScan={setDeepScan}
          queuedScan={queuedScan} setQueuedScan={setQueuedScan}
          excludeRemediated={excludeRemediated} setExcludeRemediated={setExcludeRemediated}
          incremental={incremental} setIncremental={setIncremental}
          estCount={sources.filter((s) => (pendingScan.source === 'sharepoint'
            ? (s.type === 'onedrive' || s.type === 'sharepoint')
            : (pendingScan.source === 'all' || s.type === 'google_drive')))
            .reduce((a, s) => a + (s.files || 0), 0)}
          hasDrive={hasDriveToken} hasSP={hasSPToken} canEditScope={scopeOwner !== false}
          scans={scanList}
          onConfirm={(runScope) => { const { source, folder } = pendingScan; setPendingScan(null); doScan(source, folder, runScope) }}
          onCancel={() => setPendingScan(null)} />
      )}
    </div>
  )
}
