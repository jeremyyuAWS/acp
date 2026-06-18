import { useEffect, useState } from 'react'
import { getMe, getSources, getRubric, listScans, getScan, startScan, getJob } from './api'
import KnowledgeGraph from './KnowledgeGraph.jsx'
import SignIn from './SignIn.jsx'
import Rubric from './Rubric.jsx'
import Overview from './Overview.jsx'
import Integrations from './Integrations.jsx'
import Discover from './Discover.jsx'
import Dashboard from './Dashboard.jsx'
import Remediate from './Remediate.jsx'
import Report from './Report.jsx'
import Upload from './Upload.jsx'
import EmptyState, { Loading } from './EmptyState.jsx'
import ErrorBoundary from './ErrorBoundary.jsx'

const TABS = [
  ['overview', 'Overview', 'at a glance'],
  ['integrations', 'Integrations', 'data sources'],
  ['discover', 'Discover', 'steps 1–3'],
  ['assess', 'Assess', 'steps 4–5'],
  ['remediate', 'Remediate', 'steps 6–8'],
  ['report', 'Report', 'steps 9–10'],
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

function Logo() {
  return (
    <span className="logo">
      <span className="word">mova</span>
      <span className="io"><span>io</span></span>
    </span>
  )
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
  const [scanList, setScanList] = useState([])
  const [delta, setDelta] = useState(null)
  const [deltaKey, setDeltaKey] = useState(0)
  const [progress, setProgress] = useState(null)
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    if (!me) return
    getRubric().then(setRubric).catch(() => {})
    getSources().then(setSources).catch(() => {})
    listScans()
      .then(async (l) => { setScanList(l); if (l.length) setScan(await getScan(l[0].id)) })
      .catch(() => {})
      .finally(() => setLoaded(true))
  }, [me])

  if (!me) return <SignIn onSignedIn={setMe} />

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
  const trend = [...scanList].reverse().map((s) => s.avg_score).filter((x) => x != null)
  const placeholder = loaded ? <EmptyState onScan={doScan} busy={busy} /> : <Loading />

  return (
    <div className="app">
      <header>
        <div className="brand"><Logo /><span className="sub">Accessibility Compliance</span></div>
        <div className="userbox">
          {rubric && <span className="chip">{rubric.target} · rubric {rubric.hash.slice(0, 8)}</span>}
          <span className="user">{me.email}</span>
          <button className="ghost small" onClick={() => setMe(null)}>sign out</button>
        </div>
      </header>

      <div className="tabs" role="tablist" aria-label="Compliance workflow">
        {TABS.map(([k, label, rg]) => (
          <button key={k} role="tab" aria-selected={view === k} className={view === k ? 'tab on' : 'tab'} onClick={() => setView(k)}>
            {label}<span className="rg">{rg}</span>
          </button>
        ))}
      </div>
      {run && <div className="muted runinfo">last run {run.completed_at?.slice(0, 19).replace('T', ' ')}</div>}

      {err && <div className="err" role="alert">{err}</div>}
      {busy && progress && (
        <div className="scanprog" role="status" aria-live="polite">
          <div className="scanprogline"><span className="spinner" />{progressText(progress)}{progress.files_found ? <span className="muted"> · {progress.files_found} files found</span> : null}</div>
          <div className="track"><i style={{ width: `${progress.files_found ? Math.round((progress.files_done / progress.files_found) * 100) : 6}%`, background: '#F5B400', transition: 'width .3s' }} /></div>
        </div>
      )}

      <ErrorBoundary key={view}>
        {view === 'overview' && (run ? <Overview run={run} files={files} trend={trend} onGo={setView} /> : placeholder)}

        {view === 'integrations' && <Integrations sources={sources} files={files} onScan={doScan} busy={busy} />}

        {view === 'discover' && <Discover sources={sources} files={files} busy={busy} onScan={doScan} />}

        {view === 'assess' && (
          <>
            <div className="subtabs" role="tablist" aria-label="Assessment views">
              <button role="tab" aria-selected={assess === 'results'} className={assess === 'results' ? 'fchip on' : 'fchip'} onClick={() => setAssess('results')}>Results</button>
              <button role="tab" aria-selected={assess === 'graph'} className={assess === 'graph' ? 'fchip on' : 'fchip'} onClick={() => setAssess('graph')}>Knowledge graph</button>
              <button role="tab" aria-selected={assess === 'rubric'} className={assess === 'rubric' ? 'fchip on' : 'fchip'} onClick={() => setAssess('rubric')}>Rubric</button>
            </div>
            {assess === 'results' && (run ? <Dashboard run={run} files={files} trend={trend} delta={delta} deltaKey={deltaKey} /> : placeholder)}
            {assess === 'graph' && (run ? <KnowledgeGraph files={files} /> : placeholder)}
            {assess === 'rubric' && <Rubric onSaved={() => getRubric().then(setRubric)} />}
          </>
        )}

        {view === 'remediate' && (run ? <Remediate run={run} files={files} /> : placeholder)}

        {view === 'report' && (run ? <Report run={run} files={files} trend={trend} /> : placeholder)}

        {view === 'upload' && <Upload />}
      </ErrorBoundary>
    </div>
  )
}
