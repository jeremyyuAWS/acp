import { useEffect, useState, useMemo } from 'react'
import { getSources, getRubric, listScans, getScan, startScan, startScanQueued, getJob, setDriveToken, setSPToken, setGoogleToken, clearAllTokens } from './api'
import { SIM } from './sim.js'
import { setPersona } from './sim.js'
import { loadDelegations } from './OwnerDelegate.jsx'
import { loadRolePrivileges } from './RolePrivilege.jsx'
import { loadFileTypeConfig } from './FileTypeConfig.jsx'
import { annotate, loadPublished } from './ontology.js'
import Logo from './Logo.jsx'
import ChatWidget from './ChatWidget.jsx'
import KnowledgeGraph from './KnowledgeGraph.jsx'
import SignIn from './SignIn.jsx'
import Settings from './Settings.jsx'
import Monitor from './Monitor.jsx'
import Publish from './Publish.jsx'
import Overview from './Overview.jsx'
import AssessRunner from './AssessRunner.jsx'
import RiskScore from './RiskScore.jsx'
import Integrations from './Integrations.jsx'
import Discover from './Discover.jsx'
import Dashboard from './Dashboard.jsx'
import Remediate from './Remediate.jsx'
import Upload from './Upload.jsx'
import EmptyState, { Loading } from './EmptyState.jsx'
import ErrorBoundary from './ErrorBoundary.jsx'
import A11ySelfCheck from './A11ySelfCheck.jsx'

// Self-scan overlay: on in dev, or on the deployed demo via ?a11y
const SHOW_A11Y = import.meta.env.DEV || (typeof location !== 'undefined' && new URLSearchParams(location.search).has('a11y'))

const TABS = [
  ['overview', 'Overview', 'at a glance'],
  ['integrations', 'Integrations', 'data sources'],
  ['discover', 'Discover', 'steps 1–3'],
  ['assess', 'Assess', 'steps 4–5'],
  ['remediate', 'Remediate', 'steps 6–8'],
  ['publish', 'Publish', 'step 9'],
  ['monitor', 'Monitor', 'step 10'],
  ['upload', 'Upload', 'try it live'],
]

function progressText(p) {
  if (!p) return ''
  const m = {
    queued: 'Queued…', connecting: 'Connecting to source…', discovering: 'Discovering files…',
    reading: `Reading files · ${p.files_done}/${p.files_found}`,
    tagging: 'mova Agent classifying & tagging documents…',
    analysing: `Analysing documents · ${p.files_done}/${p.files_found}`,
    scoring: 'Scoring against rubric…', done: 'Complete', error: 'Error',
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
// Light-hearted "still working" lines for the long worker-pool phase, so a
// multi-minute scan feels alive instead of frozen. Cycled by elapsed seconds.
const FUNNY = [
  'Politely asking 200 documents to declare their language…',
  'Counting alt-texts that should exist but mysteriously don’t…',
  'Negotiating with PDFs about their reading order…',
  'Checking contrast ratios with a very picky ruler…',
  'Untangling heading levels (h1 → h7, really?)…',
  'Hunting down every “click here” link to gently scold…',
  'Sniffing out SSNs hiding in spreadsheets…',
  'Making sure every button has a name to answer to…',
  'Reticulating WCAG splines…',
  'Reading the fine print so you don’t have to…',
  'Teaching screen readers to read between the lines…',
  'Bribing the rubric to score a little faster…',
]
function funnyMsg(elapsed) { return FUNNY[Math.floor(elapsed / 5) % FUNNY.length] }

function progressPct(p) {
  if (!p) return 0
  if (typeof p.pct === 'number') return p.pct   // explicit (e.g. queued elapsed-creep)
  if (p.phase === 'reading' && p.files_found) {
    const frac = Math.min(1, (p.files_done || 0) / p.files_found)
    return Math.round(12 + frac * (84 - 12))
  }
  return PHASE_PCT[p.phase] ?? 6
}

export default function App() {
  const [me, setMe] = useState(null)
  const [rubric, setRubric] = useState(null)
  const [sources, setSources] = useState([])
  const [scan, setScan] = useState(null)
  const [scanLoading, setScanLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [view, setView] = useState('overview')
  const [assess, setAssess] = useState('results')
  const [decisions, setDecisions] = useState({})
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [scanList, setScanList] = useState([])
  const [delta, setDelta] = useState(null)
  const [deltaKey, setDeltaKey] = useState(0)
  const [progress, setProgress] = useState(null)
  const [loaded, setLoaded] = useState(false)
  const [certifiedDocs, setCertifiedDocs] = useState([])
  const [publishedFiles, setPublishedFiles] = useState([])
  const [hasDriveToken, setHasDriveToken] = useState(() => !!sessionStorage.getItem('gd_token'))
  const [hasSPToken, setHasSPToken] = useState(() => !!sessionStorage.getItem('sp_token'))
  const [delegations, setDelegations] = useState(loadDelegations)
  const [fileTypeConfig, setFileTypeConfig] = useState(loadFileTypeConfig)
  const [rolePrivileges, setRolePrivileges] = useState(loadRolePrivileges)
  const [ontology, setOntology] = useState(loadPublished)
  const [aiEnabled, setAiEnabled] = useState(true)
  const [queuedScan, setQueuedScan] = useState(false)  // durable queue vs in-process
  const [deepScan, setDeepScan] = useState(true)       // PII/sensitive-data detection on/off

  useEffect(() => {
    const onExpired = () => {
      clearAllTokens()
      sessionStorage.removeItem('gd_token')
      sessionStorage.removeItem('sp_token')
      setHasDriveToken(false)
      setHasSPToken(false)
      setMe(null)
    }
    window.addEventListener('acp:session-expired', onExpired)
    return () => window.removeEventListener('acp:session-expired', onExpired)
  }, [])

  useEffect(() => {
    if (!me) return
    getRubric().then(setRubric).catch(() => {})
    getSources().then(setSources).catch(() => {})
    listScans()
      .then(async (l) => { setScanList(l); if (l.length) setScan(await getScan(l[0].id)) })
      .catch(() => {})
      .finally(() => setLoaded(true))
  }, [me])

  // Annotate the corpus with the published business ontology (adds `.ont`: label,
  // priority, matched rule, weighted score) so the live workflow is ontology-aware.
  // Kept above the early return below to satisfy the rules of hooks.
  const files = useMemo(() => annotate(scan?.files ?? [], ontology), [scan, ontology])

  // Real accounts that get elevated privileges on source connect (never shown in demo list)
  const PRIV_PROFILE = {
    id: 'jeremy-yu', name: 'Jeremy Yu', role: 'Compliance Officer & Admin',
    scope: { label: 'Full estate · all departments', departments: 'all' },
    allow: ['overview', 'integrations', 'discover', 'assess', 'remediate', 'publish', 'monitor', 'settings', 'upload'],
  }
  const PRIVILEGED = { 'jeremyyu.movate@gmail.com': PRIV_PROFILE }

  const signIn = (p) => {
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
    setPersona(p); setScan(null); setScanList([]); setLoaded(false); setDecisions({}); setCertifiedDocs([]); setPublishedFiles([]); setSettingsOpen(false); setView((p.allow || ['overview'])[0]); setMe({ email: p.email, name: p.name, role: p.role, scope: p.scope?.label, allow: p.allow || [] })
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
  if (!me) return <SignIn onSignedIn={signIn} />

  const switchScan = async (id) => {
    if (id === scan?.run?.id) return
    setScanLoading(true)
    try {
      setScan(await getScan(id))
      setDecisions({})
      setCertifiedDocs([])
    } catch { /* leave current scan */ } finally { setScanLoading(false) }
  }

  const doScan = async (source, folder = null) => {
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
        const { scan_id, workers } = await startScanQueued(apiSource, folder, aiEnabled, deepScan)
        if (!SIM && !workers) throw new Error('no workers running — start some in Monitor (or set ACP_WORKERS)')
        const t0 = Date.now()
        for (let i = 0; i < 600 && !fresh; i++) {        // up to ~10 min for large estates
          await new Promise((r) => setTimeout(r, 1000))
          // No per-file stream on the durable path; show elapsed time + a bar that
          // eases toward ~95% so the user can see it's still working.
          const elapsed = Math.round((Date.now() - t0) / 1000)
          setProgress({ phase: 'scoring', queued: true, elapsed,
                        pct: Math.min(95, 10 + Math.round(85 * (1 - Math.exp(-elapsed / 90)))) })
          // Fan-out scans create the row early with status 'running'; wait for 'done'.
          try { const g = await getScan(scan_id); if (g && g.run && g.run.status !== 'running') fresh = g } catch { fresh = null }
        }
        if (!fresh) throw new Error('scan still processing — watch it finish in the Monitor queue')
      } else {
        const { job_id } = await startScan(apiSource, folder, aiEnabled, deepScan)
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
      setScanList(await listScans())
      const newAvg = fresh.run.avg_score
      if (prevAvg != null && newAvg != null && newAvg !== prevAvg) { setDelta(newAvg - prevAvg); setDeltaKey((k) => k + 1) }
      setView('overview')
    } catch (e) { setErr(`scan failed: ${e}`) } finally { setBusy(false); setProgress(null) }
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
  const placeholder = loaded ? <EmptyState onScan={doScan} busy={busy} hasDriveToken={hasDriveToken} /> : <Loading />

  return (
    <div className="app">
      <a className="skiplink" href="#main-content">Skip to main content</a>
      <header>
        <div className="brand"><Logo /><h1 className="sub">Accessibility Platform</h1></div>
        <div className="userbox">
          {me.role && <span className="chip" title={me.scope}>{me.role}</span>}
          {rubric && me.allow?.includes('settings') && <span className="chip">{rubric.target} · rubric {rubric.hash.slice(0, 8)}</span>}
          {/* Global mode (applies across scanning, explanations, and remediation). The
              scan-only options (Deep scan, Queued) live on the Sources tab where you scan. */}
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
            sessionStorage.removeItem('gd_token')
            sessionStorage.removeItem('sp_token')
            setHasDriveToken(false)
            setHasSPToken(false)
            setMe(null)
          }}>sign out</button>
        </div>
      </header>
      {me.scope && <div className="scopebar"><i className="scopedot" />access scope · <b>{me.scope}</b></div>}

      <nav aria-label="Compliance workflow">
        <div className="tabs" role="tablist" aria-label="Compliance workflow">
          {TABS.filter(([k]) => !me.allow || me.allow.includes(k)).map(([k, label, rg]) => (
            <button key={k} role="tab" aria-selected={view === k} className={view === k ? 'tab on' : 'tab'} onClick={() => setView(k)}>
              {label}<span className="rg">{rg}</span>
            </button>
          ))}
        </div>
      </nav>
      {scanList.length > 0 && (
        <div className="runinfo">
          {scanList.length === 1 ? (
            <span className="muted">last run {run?.completed_at?.slice(0, 19).replace('T', ' ')}</span>
          ) : (
            <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12 }}>
              <span className="muted">scan:</span>
              <select
                value={scan?.run?.id || ''}
                onChange={(e) => switchScan(e.target.value)}
                disabled={scanLoading || busy}
                aria-label="Select scan run"
                style={{ fontSize: 12, padding: '2px 6px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--surface)', color: 'inherit', cursor: 'pointer' }}
              >
                {scanList.map((s) => (
                  <option key={s.id} value={s.id}>
                    {new Date(s.completed_at).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}
                    {' · '}{s.source}{' · '}{s.avg_score ?? 'n/a'}/100{' · '}{s.certifiable} certifiable
                  </option>
                ))}
              </select>
              {scanLoading && <span className="spinner" />}
            </label>
          )}
        </div>
      )}

      {err && <div className="err" role="alert">{err}</div>}
      {busy && progress && (
        <div className="scanprog" role="status" aria-live="polite">
          <div className="scanprogline"><span className="spinner" />{progressText(progress)}
            {progress.files_found ? <span className="scancount"> · {progress.files_found.toLocaleString()} files</span> : null}
            {progress.blocked ? <span className="lockwarn"> · 🔒 {progress.blocked} password-protected / couldn’t open</span> : null}
          </div>
          <div className="track"><i style={{ width: `${progressPct(progress)}%`, background: '#BF8C00', transition: 'width .3s' }} /></div>
          {progress.elapsed != null && (
            <div className="muted" style={{ marginTop: 6, fontSize: 12, fontStyle: 'italic' }}>{funnyMsg(progress.elapsed)}</div>
          )}
        </div>
      )}

      <main id="main-content" tabIndex={-1}>
      <ErrorBoundary key={view}>
        {view === 'overview' && (run ? <Overview run={run} files={files} trend={trend} trendDates={trendDates} onGo={setView} /> : placeholder)}

        {view === 'integrations' && <Integrations sources={sources} files={files} scans={scanList} onScan={doScan} busy={busy} hasDriveToken={hasDriveToken} hasSPToken={hasSPToken} onConnect={handleConnect}
          deepScan={deepScan} setDeepScan={setDeepScan} queuedScan={queuedScan} setQueuedScan={setQueuedScan} />}

        {view === 'discover' && <Discover sources={sources} files={files} busy={busy} onScan={doScan} delegations={delegations} fileTypeConfig={fileTypeConfig} />}

        {view === 'assess' && (
          <>
            <div className="subtabs" role="tablist" aria-label="Assessment views">
              <button role="tab" aria-selected={assess === 'results'} className={assess === 'results' ? 'fchip on' : 'fchip'} onClick={() => setAssess('results')}>4 · Assess</button>
              <button role="tab" aria-selected={assess === 'graph'} className={assess === 'graph' ? 'fchip on' : 'fchip'} onClick={() => setAssess('graph')}>5 · Risk &amp; findings</button>
            </div>
            {assess === 'results' && (run ? <><AssessRunner files={files} /><Dashboard run={run} files={files} trend={trend} delta={delta} deltaKey={deltaKey} /></> : placeholder)}
            {(assess === 'graph' || assess === 'rubric' || assess === 'coverage') && (run ? <><RiskScore run={run} files={files} /><KnowledgeGraph files={files} /></> : placeholder)}
          </>
        )}

        {view === 'remediate' && (run ? <Remediate run={run} files={files} decisions={decisions} setDecisions={setDecisions} aiEnabled={aiEnabled} /> : placeholder)}

        {view === 'publish' && (run ? <Publish run={run} files={files} certified={certifiedDocs} onPublish={(file) => setPublishedFiles((s) => [...s, file])} /> : placeholder)}

        {view === 'monitor' && (run ? <Monitor sources={sources} files={files} ratified={ratified} decisions={decisions} publishedFiles={publishedFiles} aiEnabled={aiEnabled} onAiToggle={setAiEnabled} /> : placeholder)}

        {view === 'upload' && <Upload onCertified={(e) => setCertifiedDocs((c) => [{ file: e.file, id: c.length + 1 }, ...c].slice(0, 12))} />}
      </ErrorBoundary>
      </main>

      <ChatWidget files={files} run={run} trend={trend} trendDates={trendDates} me={me} />
      {SHOW_A11Y && <A11ySelfCheck />}
      {settingsOpen && me.allow?.includes('settings') && <Settings files={files} onClose={() => setSettingsOpen(false)} onRubricSaved={() => getRubric().then(setRubric)} onOntologyChange={() => setOntology(loadPublished())} onDelegationChange={setDelegations} onFileTypeChange={(cfg) => setFileTypeConfig(cfg)}
            onPrivilegeChange={setRolePrivileges} />}
    </div>
  )
}
