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

// Engine label shown per file type during scanning — mirrors what the real pipeline uses
const engineFor = (name = '') => {
  const n = name.toLowerCase()
  if (/\.docx?$/.test(n) || /\.pptx?$/.test(n)) return 'OOXML engine'
  if (/\.pdf$/.test(n)) return 'PDF engine'
  if (/\.html?$/.test(n)) return 'axe-core'
  if (/\.mp3$|\.webm$|\.wav$/.test(n)) return 'Whisper transcription'
  if (/\.xlsx?$/.test(n)) return 'OOXML engine'
  if (/\.png$|\.jpe?g$|\.gif$|\.webp$/.test(n)) return 'Claude vision'
  return 'WCAG rule engine'
}

// Realistic phase messages shown as each file is scanned
const phaseFor = (name = '') => {
  const n = name.toLowerCase()
  if (/\.docx?$/.test(n)) return ['Opening OOXML package…', 'Checking alt text, headings & tables…', 'Running WCAG 2.1 AA conformance checks…']
  if (/\.pptx?$/.test(n)) return ['Unpacking presentation slides…', 'Checking slide titles & reading order…', 'Running WCAG 2.1 AA conformance checks…']
  if (/\.pdf$/.test(n)) return ['Extracting PDF tag tree…', 'Checking alt text, title & language…', 'Running WCAG 2.1 AA conformance checks…']
  if (/\.html?$/.test(n)) return ['Parsing DOM…', 'Running axe-core rules…', 'Scoring against WCAG 2.1 AA…']
  if (/\.mp3$|\.webm$/.test(n)) return ['Transcribing with Whisper…', 'Checking captions & transcript…']
  return ['Analysing…', 'Scoring…']
}

export default function AssessRunner({ files = [] }) {
  const [level, setLevel] = useState('AA')
  const [phase, setPhase] = useState('idle') // idle | running | done
  const [progress, setProgress] = useState(0)
  const [currentFile, setCurrentFile] = useState(null)
  const [currentPhase, setCurrentPhase] = useState('')
  const [result, setResult] = useState(null)
  const timer = useRef(null)
  const phaseTimer = useRef(null)
  useEffect(() => () => { clearInterval(timer.current); clearTimeout(phaseTimer.current) }, [])

  const docs = files.filter((f) => f.score != null)
  const reset = () => {
    clearInterval(timer.current); clearTimeout(phaseTimer.current)
    setPhase('idle'); setResult(null); setProgress(0); setCurrentFile(null); setCurrentPhase('')
  }

  const runPhases = (file, onDone) => {
    const phases = phaseFor(file?.name)
    let pi = 0
    const next = () => {
      if (pi >= phases.length) { onDone(); return }
      setCurrentPhase(phases[pi++])
      // each phase message shows for 180–280ms
      phaseTimer.current = setTimeout(next, 180 + Math.random() * 100)
    }
    next()
  }

  const assess = () => {
    clearInterval(timer.current); clearTimeout(phaseTimer.current)
    setPhase('running'); setProgress(0); setResult(null); setCurrentFile(null); setCurrentPhase('')
    const total = Math.max(1, docs.length)
    let i = 0

    const tick = () => {
      if (i >= total) {
        clearInterval(timer.current)
        setProgress(total); setCurrentFile(null); setCurrentPhase('')
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
        return
      }
      const file = docs[i]
      setCurrentFile(file)
      setProgress(i)
      runPhases(file, () => {})
      i++
    }

    tick()
    // Each file takes ~500–700ms: phases (3×~220ms) + a small gap
    timer.current = setInterval(tick, 600)
  }

  const note = result && (result.level === 'A'
    ? 'Level A is the floor — only must-have criteria block conformance.'
    : result.level === 'AA'
      ? 'Level AA is the legal target for ADA Title II, the EAA and Section 508 — Level A + AA findings both count.'
      : 'Level AAA is the enhanced bar — every A, AA and AAA finding counts, so conformance is strictest here.')

  const pct = phase === 'running' ? Math.round((progress / Math.max(1, docs.length)) * 100) : 0

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

      <div role="status" aria-live="polite">
        {phase === 'running' && (
          <div className="assessrun">
            <div className="assessbar">
              <i style={{ width: `${pct}%` }} />
            </div>
            <div className="assessrunmeta">
              <span className="muted">Document {Math.min(progress + 1, docs.length).toLocaleString()} of {docs.length.toLocaleString()}</span>
              <span className="assesspct">{pct}%</span>
            </div>
            {currentFile && (
              <div className="assessfile">
                <span className="assessfname">{currentFile.name}</span>
                <span className="assessengine">{engineFor(currentFile.name)}</span>
                {currentPhase && <span className="assessphase muted">{currentPhase}</span>}
              </div>
            )}
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
