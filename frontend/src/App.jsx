import { useEffect, useState } from 'react'
import { getMe, getSources, getRubric, listScans, getScan, runScan } from './api'
import KnowledgeGraph from './KnowledgeGraph.jsx'
import SignIn from './SignIn.jsx'

const CRIT = {
  SC_1_1_1: '1.1.1 non-text', SC_1_3_1: '1.3.1 structure', SC_2_4_2: '2.4.2 page titled',
  SC_2_4_4: '2.4.4 link purpose', SC_3_1_1: '3.1.1 language',
}
const scoreColor = (s) => (s >= 90 ? '#639922' : s >= 50 ? '#F5B400' : '#F0524A')
const statusOf = (f) => (f.status === 'error' ? 'unanalysable' : f.compliant ? 'certifiable' : 'issues')
const BADGE = {
  certifiable: ['#E7F0DC', '#3B6D11'], issues: ['#FAEEDA', '#854F0B'], unanalysable: ['#EEEDEA', '#5F5E5A'],
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
  const [view, setView] = useState('sources')

  useEffect(() => {
    if (!me) return
    getRubric().then(setRubric).catch(() => {})
    getSources().then(setSources).catch(() => {})
    listScans().then((l) => l.length && getScan(l[0].id).then(setScan)).catch(() => {})
  }, [me])

  if (!me) return <SignIn onSignedIn={setMe} />

  const doScan = async (source) => {
    setBusy(true); setErr(null)
    try {
      const r = await runScan(source)
      setScan(await getScan(r.scan_id))
      setView('dashboard')
    } catch (e) { setErr(`scan failed: ${e}`) } finally { setBusy(false) }
  }

  const run = scan?.run
  const files = scan?.files ?? []
  const critFails = {}
  files.forEach((f) => new Set(f.issues.map((i) => i.wcag)).forEach((c) => { critFails[c] = (critFails[c] || 0) + 1 }))
  const maxFail = Math.max(1, ...Object.values(critFails))

  return (
    <div className="app">
      <header>
        <div className="brand"><Logo /><span className="sub">accessibility compliance</span></div>
        <div className="userbox">
          {rubric && <span className="chip">{rubric.target} · rubric {rubric.hash.slice(0, 8)}</span>}
          <span className="user">{me.email}</span>
          <button className="ghost small" onClick={() => setMe(null)}>sign out</button>
        </div>
      </header>

      <div className="tabs">
        <button className={view === 'sources' ? 'tab on' : 'tab'} onClick={() => setView('sources')}>Sources</button>
        <button className={view === 'dashboard' ? 'tab on' : 'tab'} onClick={() => setView('dashboard')}>Dashboard</button>
        <button className={view === 'graph' ? 'tab on' : 'tab'} onClick={() => setView('graph')}>Knowledge graph</button>
        {run && <span className="muted runinfo">last run {run.completed_at?.slice(0, 19).replace('T', ' ')}</span>}
      </div>
      {err && <div className="err">{err}</div>}

      {view === 'sources' && (
        <section className="panel">
          <h2>Connected sources</h2>
          {sources.length === 0 && <p className="muted">No sources connected.</p>}
          {sources.map((s) => (
            <div className="source" key={s.id}>
              <div className="srcleft">
                <span className="srcicon" aria-hidden="true">▦</span>
                <div>
                  <div className="srcname">{s.name}</div>
                  <div className="muted">Google Drive · {s.files} files · {s.access}</div>
                </div>
              </div>
              <button disabled={busy} onClick={() => doScan('drive')}>{busy ? 'scanning…' : 'Run scan'}</button>
            </div>
          ))}
          <div className="source ghosted">
            <div className="srcleft"><span className="srcicon" aria-hidden="true">＋</span>
              <div><div className="srcname">Connect another source</div><div className="muted">SharePoint · OneDrive — coming soon</div></div>
            </div>
            <button className="ghost" disabled onClick={() => {}}>Connect</button>
          </div>
          <p className="muted" style={{ marginTop: 14 }}>Or <a href="#" onClick={(e) => { e.preventDefault(); doScan('local') }}>run a scan on the bundled sample corpus</a>.</p>
        </section>
      )}

      {view === 'dashboard' && (run ? (
        <>
          <section className="metrics">
            <div className="metric"><span>Files</span><b>{run.files}</b></div>
            <div className="metric"><span>Avg score</span><b>{run.avg_score ?? '—'}</b></div>
            <div className="metric"><span>Certifiable</span><b style={{ color: '#3B6D11' }}>{run.certifiable}</b></div>
            <div className="metric"><span>Uncertain</span><b style={{ color: '#854F0B' }}>{run.uncertain}</b></div>
            <div className="metric"><span>Unanalysable</span><b style={{ color: '#A32D2D' }}>{run.error}</b></div>
          </section>
          {Object.keys(critFails).length > 0 && (
            <section className="panel">
              <h2>WCAG 2.1 criteria failing, by file count</h2>
              {Object.entries(critFails).sort((a, b) => b[1] - a[1]).map(([c, n]) => (
                <div className="critrow" key={c}>
                  <span className="critlabel">{CRIT[c] ?? c}</span>
                  <span className="track"><i style={{ width: `${(n / maxFail) * 100}%`, background: n >= maxFail ? '#F0524A' : '#F5B400' }} /></span>
                  <span className="critn">{n}</span>
                </div>
              ))}
            </section>
          )}
          <section className="panel">
            <h2>File inventory</h2>
            <table>
              <thead><tr><th>file</th><th>status</th><th>score</th><th>findings</th></tr></thead>
              <tbody>
                {files.map((f) => {
                  const st = statusOf(f); const [bg, fg] = BADGE[st]
                  return (
                    <tr key={f.file}>
                      <td className="fname">{f.file}</td>
                      <td><span className="badge" style={{ background: bg, color: fg }}>{st}</span></td>
                      <td>{f.score === null ? <span className="muted">n/a</span> : (
                        <span className="scorecell"><span>{f.score}</span>
                          <span className="track sm"><i style={{ width: `${f.score}%`, background: scoreColor(f.score) }} /></span></span>)}</td>
                      <td className="muted">{f.issues.length ? `${f.issues.length} issue(s)` : (f.status === 'error' ? 'could not analyse' : 'clean')}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </section>
        </>
      ) : <p className="muted">No scan yet — run one from Sources.</p>)}

      {view === 'graph' && (run ? <KnowledgeGraph files={files} /> : <p className="muted">No scan yet — run one from Sources.</p>)}
    </div>
  )
}
