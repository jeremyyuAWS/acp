import { useEffect, useState } from 'react'
import { getSources, getRubric, listScans, getScan, startScan, getJob } from './api'
import { setPersona } from './sim.js'
import Logo from './Logo.jsx'
import ChatWidget from './ChatWidget.jsx'
import KnowledgeGraph from './KnowledgeGraph.jsx'
import SignIn from './SignIn.jsx'
import Settings from './Settings.jsx'
import Monitor from './Monitor.jsx'
import Publish from './Publish.jsx'
import Overview from './Overview.jsx'
import Integrations from './Integrations.jsx'
import Discover from './Discover.jsx'
import Dashboard from './Dashboard.jsx'
import Remediate from './Remediate.jsx'
import Upload from './Upload.jsx'
import EmptyState, { Loading } from './EmptyState.jsx'
import ErrorBoundary from './ErrorBoundary.jsx'

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
  return s
}

// Overall scan progress (0–100) across every phase, so the bar only reaches 100%
// when the scan is actually done — not when the read phase finishes (tagging,
// analysing and scoring still follow). The read phase spans 12→84%, scaled by the
// real per-file count; the post-read phases fill the remainder.
const PHASE_PCT = { queued: 2, connecting: 5, discovering: 9, reading: 12, tagging: 88, analysing: 92, scoring: 97, done: 100, error: 100 }
function progressPct(p) {
  if (!p) return 0
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

  useEffect(() => {
    if (!me) return
    getRubric().then(setRubric).catch(() => {})
    getSources().then(setSources).catch(() => {})
    listScans()
      .then(async (l) => { setScanList(l); if (l.length) setScan(await getScan(l[0].id)) })
      .catch(() => {})
      .finally(() => setLoaded(true))
  }, [me])

  const signIn = (p) => { setPersona(p); setScan(null); setScanList([]); setLoaded(false); setDecisions({}); setCertifiedDocs([]); setSettingsOpen(false); setView((p.allow || ['overview'])[0]); setMe({ email: p.email, name: p.name, role: p.role, scope: p.scope?.label, allow: p.allow || [] }) }
  if (!me) return <SignIn onSignedIn={signIn} />

  const doScan = async (source) => {
    setBusy(true); setErr(null); setProgress({ phase: 'queued' })
    const prevAvg = scan?.run?.avg_score
    try {
      const { job_id } = await startScan(source)
      let job
      do {
        await new Promise((r) => setTimeout(r, 350))
        job = await getJob(job_id)
        setProgress(job)
      } while (!job.done)
      if (job.error) throw new Error(job.error)
      const fresh = await getScan(job.scan_id)
      setScan(fresh)
      setScanList(await listScans())
      const newAvg = fresh.run.avg_score
      if (prevAvg != null && newAvg != null && newAvg !== prevAvg) { setDelta(newAvg - prevAvg); setDeltaKey((k) => k + 1) }
      setView('overview')
    } catch (e) { setErr(`scan failed: ${e}`) } finally { setBusy(false); setProgress(null) }
  }

  const run = scan?.run
  const files = scan?.files ?? []
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
  const placeholder = loaded ? <EmptyState onScan={doScan} busy={busy} /> : <Loading />

  return (
    <div className="app">
      <a className="skiplink" href="#main-content">Skip to main content</a>
      <header>
        <div className="brand"><Logo /><h1 className="sub">Accessibility Compliance</h1></div>
        <div className="userbox">
          {me.role && <span className="chip" title={me.scope}>{me.role}</span>}
          {rubric && me.allow?.includes('settings') && <span className="chip">{rubric.target} · rubric {rubric.hash.slice(0, 8)}</span>}
          <span className="user">{me.email}</span>
          {me.allow?.includes('settings') && <button className="cogbtn" aria-label="Platform settings" title="Platform settings" onClick={() => setSettingsOpen(true)}>⚙</button>}
          <button className="ghost small" onClick={() => setMe(null)}>sign out</button>
        </div>
      </header>
      {me.scope && <div className="scopebar"><i className="scopedot" />access scope · <b>{me.scope}</b></div>}

      <div className="tabs" role="tablist" aria-label="Compliance workflow">
        {TABS.filter(([k]) => !me.allow || me.allow.includes(k)).map(([k, label, rg]) => (
          <button key={k} role="tab" aria-selected={view === k} className={view === k ? 'tab on' : 'tab'} onClick={() => setView(k)}>
            {label}<span className="rg">{rg}</span>
          </button>
        ))}
      </div>
      {run && <div className="muted runinfo">last run {run.completed_at?.slice(0, 19).replace('T', ' ')}</div>}

      {err && <div className="err" role="alert">{err}</div>}
      {busy && progress && (
        <div className="scanprog" role="status" aria-live="polite">
          <div className="scanprogline"><span className="spinner" />{progressText(progress)}
            {progress.files_found ? <span className="scancount"> · {progress.files_found.toLocaleString()} files</span> : null}
            {progress.blocked ? <span className="lockwarn"> · 🔒 {progress.blocked} password-protected / couldn’t open</span> : null}
          </div>
          <div className="track"><i style={{ width: `${progressPct(progress)}%`, background: '#F5B400', transition: 'width .3s' }} /></div>
        </div>
      )}

      <main id="main-content" tabIndex={-1}>
      <ErrorBoundary key={view}>
        {view === 'overview' && (run ? <Overview run={run} files={files} trend={trend} trendDates={trendDates} onGo={setView} /> : placeholder)}

        {view === 'integrations' && <Integrations sources={sources} files={files} onScan={doScan} busy={busy} />}

        {view === 'discover' && <Discover sources={sources} files={files} busy={busy} onScan={doScan} />}

        {view === 'assess' && (
          <>
            <div className="subtabs" role="tablist" aria-label="Assessment views">
              <button role="tab" aria-selected={assess === 'results'} className={assess === 'results' ? 'fchip on' : 'fchip'} onClick={() => setAssess('results')}>4 · Assess</button>
              <button role="tab" aria-selected={assess === 'graph'} className={assess === 'graph' ? 'fchip on' : 'fchip'} onClick={() => setAssess('graph')}>5 · Risk &amp; findings</button>
            </div>
            {assess === 'results' && (run ? <Dashboard run={run} files={files} trend={trend} delta={delta} deltaKey={deltaKey} /> : placeholder)}
            {(assess === 'graph' || assess === 'rubric' || assess === 'coverage') && (run ? <KnowledgeGraph files={files} /> : placeholder)}
          </>
        )}

        {view === 'remediate' && (run ? <Remediate run={run} files={files} decisions={decisions} setDecisions={setDecisions} /> : placeholder)}

        {view === 'publish' && (run ? <Publish run={run} files={files} certified={certifiedDocs} /> : placeholder)}

        {view === 'monitor' && (run ? <Monitor sources={sources} files={files} ratified={ratified} /> : placeholder)}

        {view === 'upload' && <Upload onCertified={(e) => setCertifiedDocs((c) => [{ file: e.file, id: c.length + 1 }, ...c].slice(0, 12))} />}
      </ErrorBoundary>
      </main>

      <ChatWidget files={files} run={run} trend={trend} trendDates={trendDates} />
      {settingsOpen && me.allow?.includes('settings') && <Settings onClose={() => setSettingsOpen(false)} onRubricSaved={() => getRubric().then(setRubric)} />}
    </div>
  )
}
