import { useState, useEffect, useRef } from 'react'

// Live Scan Theater (bundle #3) — a real-time view of a scan in flight, driven entirely by
// the real scan-progress signal (phase, files_done/found, current file, blocked, elapsed).
// Shows the pipeline lighting up stage by stage, the live document count + throughput, and
// the documents streaming through as they're processed. Renders nothing when idle.
const STAGES = [
  { key: 'discover', label: 'Discover', phases: ['queued', 'connecting', 'discovering'] },
  { key: 'scan', label: 'Scan', phases: ['reading', 'analysing', 'tagging'] },
  { key: 'score', label: 'Score', phases: ['scoring'] },
  { key: 'done', label: 'Done', phases: ['done'] },
]

export default function ScanTheater({ busy, progress, pct = 0, status = '' }) {
  const [recent, setRecent] = useState([])
  const lastFile = useRef(null)
  useEffect(() => {
    if (!busy) { setRecent([]); lastFile.current = null; return }
    const f = progress?.current
    if (f && f !== lastFile.current) { lastFile.current = f; setRecent((r) => [f, ...r].slice(0, 6)) }
  }, [progress?.current, busy])

  if (!busy || !progress) return null
  const done = progress.files_done || 0
  const found = progress.files_found || 0
  const rate = progress.elapsed > 0 && done ? (done / progress.elapsed).toFixed(1) : null
  const curStage = Math.max(0, STAGES.findIndex((s) => s.phases.includes(progress.phase)))

  return (
    <section className="panel theaterpanel" style={{ marginBottom: 14 }}>
      <div className="proghd">
        <h2 style={{ margin: 0 }}><span className="livedot" aria-hidden="true" style={{ marginRight: 7 }} />Live scan in progress</h2>
        {progress.elapsed != null && <span className="muted" style={{ fontSize: 12 }}>{progress.elapsed}s elapsed</span>}
      </div>

      <div className="theaterstages">
        {STAGES.map((s, i) => (
          <div className={`tstage${i < curStage ? ' done' : i === curStage ? ' active' : ''}`} key={s.key}>
            <span className="tstagedot" aria-hidden="true" />{s.label}
          </div>
        ))}
      </div>

      <div className="theatercount">
        <b>{done.toLocaleString()}</b><span className="muted">{found ? ` / ${found.toLocaleString()} documents` : ' documents'}</span>
        {rate ? <span className="muted" style={{ marginLeft: 12 }}>· {rate} docs/s</span> : null}
        {progress.blocked ? <span className="lockwarn" style={{ marginLeft: 12 }}>🔒 {progress.blocked} couldn’t open</span> : null}
      </div>

      <div className="track" style={{ marginTop: 8 }}><i style={{ width: `${pct}%`, background: '#7C3AED', transition: 'width .4s' }} /></div>
      {status && <div className="muted theaterstatus" style={{ marginTop: 8, fontSize: 12.5 }} role="status" aria-live="polite">{status}</div>}

      {recent.length > 0 && (
        <div className="theaterstream">
          {recent.map((f, i) => <div className="theaterfile" key={f + i} style={{ opacity: 1 - i * 0.13 }}><span className="fname">{f}</span></div>)}
        </div>
      )}
    </section>
  )
}
