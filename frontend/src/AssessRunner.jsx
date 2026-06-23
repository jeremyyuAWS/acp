import { useState, useRef, useEffect } from 'react'

// Re-assess the whole estate against a chosen WCAG 2.1 conformance level. A finding blocks
// conformance when its level is at or below the target (A ⊆ AA ⊆ AAA), so the numbers
// genuinely shift with the level — this is a real computation over the assessed findings,
// not a cosmetic toggle.
const RANK = { A: 1, AA: 2, AAA: 3 }
const LEVELS = [
  { k: 'A', desc: 'minimum' },
  { k: 'AA', desc: 'legal target · ADA · EAA · 508' },
  { k: 'AAA', desc: 'enhanced' },
]

export default function AssessRunner({ files = [] }) {
  const [level, setLevel] = useState('AA')
  const [phase, setPhase] = useState('idle') // idle | running | done
  const [progress, setProgress] = useState(0)
  const [result, setResult] = useState(null)
  const timer = useRef(null)
  useEffect(() => () => clearInterval(timer.current), [])

  const docs = files.filter((f) => f.score != null) // readable documents we can certify
  const reset = () => { clearInterval(timer.current); setPhase('idle'); setResult(null); setProgress(0) }

  const assess = () => {
    clearInterval(timer.current)
    setPhase('running'); setProgress(0); setResult(null)
    const total = Math.max(1, docs.length)
    let i = 0
    timer.current = setInterval(() => {
      i += Math.max(1, Math.round(total / 26))
      if (i >= total) {
        clearInterval(timer.current); setProgress(total)
        const target = RANK[level]
        let conformant = 0, applicable = 0, autoFix = 0
        docs.forEach((f) => {
          const blocking = (f.issues || []).filter((x) => RANK[x.level] && RANK[x.level] <= target)
          applicable += blocking.length
          autoFix += blocking.filter((x) => x.auto).length
          if (!blocking.length) conformant++
        })
        setResult({ level, total, conformant, failing: total - conformant, applicable, autoFix, pct: Math.round((conformant / total) * 100) })
        setPhase('done')
      } else setProgress(i)
    }, 40)
  }

  const note = result && (result.level === 'A'
    ? 'Level A is the floor — only must-have criteria block conformance.'
    : result.level === 'AA'
      ? 'Level AA is the legal target for ADA Title II, the EAA and Section 508 — Level A + AA findings both count.'
      : 'Level AAA is the enhanced bar — every A, AA and AAA finding counts, so conformance is strictest here.')

  return (
    <section className="panel assesspanel">
      <div className="assesshd">
        <div>
          <h2 style={{ margin: 0 }}>Assess the estate against WCAG 2.1</h2>
          <p className="muted" style={{ margin: '3px 0 0' }}>Run all {docs.length.toLocaleString()} readable documents against the success criteria at your target conformance level.</p>
        </div>
        <button className="assessbtn" onClick={assess} disabled={phase === 'running' || !docs.length}>
          {phase === 'running' ? 'Assessing…' : `▶ Assess ${docs.length.toLocaleString()} files`}
        </button>
      </div>

      <div className="lvlseg" role="radiogroup" aria-label="Target conformance level">
        {LEVELS.map((l) => (
          <button key={l.k} role="radio" aria-checked={level === l.k} className={level === l.k ? 'lvlchip on' : 'lvlchip'} onClick={() => { setLevel(l.k); reset() }} disabled={phase === 'running'}>
            <b>{l.k}</b><span>{l.desc}</span>
          </button>
        ))}
      </div>

      {/* Live region — a screen reader announces the run progress + result without a focus move */}
      <div role="status" aria-live="polite">
        {phase === 'running' && (
          <div className="assessrun">
            <div className="assessbar"><i style={{ width: `${Math.round((progress / Math.max(1, docs.length)) * 100)}%` }} /></div>
            <span className="muted">Checking document {Math.min(progress, docs.length).toLocaleString()} of {docs.length.toLocaleString()} against WCAG 2.1 {level}…</span>
          </div>
        )}
        {phase === 'done' && result && (
          <div className="assessres">
            <p className="sronly">Assessment complete: {result.conformant} of {result.total} documents conformant at WCAG 2.1 {result.level} ({result.pct}%); {result.applicable} findings apply.</p>
            <div className="assesstiles">
              <div className="atile"><b style={{ color: '#3B6D11' }}>{result.conformant.toLocaleString()}</b><span>conformant at {result.level}</span></div>
              <div className="atile"><b style={{ color: '#854F0B' }}>{result.failing.toLocaleString()}</b><span>with blocking findings</span></div>
              <div className="atile"><b style={{ color: '#1F5FA8' }}>{result.pct}%</b><span>estate conformant</span></div>
              <div className="atile"><b>{result.applicable.toLocaleString()}</b><span>findings apply · {result.autoFix.toLocaleString()} auto-fixable</span></div>
            </div>
            <p className="muted assessnote">{note}</p>
          </div>
        )}
      </div>
    </section>
  )
}
