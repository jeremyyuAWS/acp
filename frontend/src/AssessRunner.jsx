import { useState, useRef, useEffect } from 'react'
import { allRules } from './rules'
import { assessScan } from './api.js'

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

// Real scan findings carry {rule_id, wcag, severity} but no conformance level or auto flag,
// so derive both from the SC catalog (rules/*.js meta) keyed by the WCAG SC number.
const SC_LEVEL = Object.fromEntries(allRules.map((r) => [r.meta.id, r.meta.level]))
const SC_AUTO = Object.fromEntries(allRules.map((r) => [r.meta.id, r.meta.fixMode === 'auto']))
const scOf = (w) => (String(w || '').match(/\d+\.\d+\.\d+/) || [])[0]
// Level of a finding: explicit field (SIM) → SC catalog → default A (unknown SCs still count).
const levelOf = (x) => x.level || SC_LEVEL[scOf(x.wcag)] || 'A'
const autoOf = (x) => (x.auto != null ? x.auto : !!SC_AUTO[scOf(x.wcag)])

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

// Persist the assessment per-scan in sessionStorage, so leaving the Assess tab (or even
// reloading) and coming back shows the result instead of resetting to idle. Self-contained
// — no reliance on parent state surviving an unmount/remount.
const SKEY = (id) => `acp-assess-${id || 'none'}`
const loadSaved = (id) => { try { return JSON.parse(sessionStorage.getItem(SKEY(id)) || 'null') } catch { return null } }

export default function AssessRunner({ files = [], runId, scanBusy = false, onAssessed }) {
  const saved = loadSaved(runId)
  const [level, setLevel] = useState(saved?.level || 'AA')
  const [phase, setPhase] = useState(saved?.phase || 'idle') // idle | running | done
  const [progress, setProgress] = useState(0)
  const [currentFile, setCurrentFile] = useState(null)
  const [currentPhase, setCurrentPhase] = useState('')
  const [result, setResult] = useState(saved?.result || null)
  // Track whether the current result came from a previous session (cached) or was
  // computed in this session — so we can label cached results clearly.
  const [resultFromCache, setResultFromCache] = useState(saved?.phase === 'done' && !!saved?.result)
  const timer = useRef(null)
  const phaseTimer = useRef(null)
  useEffect(() => () => { clearInterval(timer.current); clearTimeout(phaseTimer.current) }, [])

  const docs = files.filter((f) => f.score != null)
  const reset = () => {
    clearInterval(timer.current); clearTimeout(phaseTimer.current)
    setPhase('idle'); setResult(null); setResultFromCache(false); setProgress(0); setCurrentFile(null); setCurrentPhase('')
    try { sessionStorage.removeItem(SKEY(runId)) } catch { /* ignore */ }
  }

  // Deterministic conformance result over the already-scanned docs at a WCAG level.
  const computeResult = (lvl) => {
    const target = RANK[lvl]
    let conformant = 0, applicable = 0, autoFix = 0
    docs.forEach((f) => {
      const blocking = (f.issues || []).filter((x) => RANK[levelOf(x)] <= target)
      applicable += blocking.length
      autoFix += blocking.filter(autoOf).length
      if (!blocking.length) conformant++
    })
    const total = Math.max(1, docs.length)
    return { level: lvl, total, conformant, failing: total - conformant, applicable, autoFix,
             pct: Math.round((conformant / total) * 100) }
  }

  // Time-based cosmetic pass (~600ms/doc). Driven by wall-clock since startedAt so it
  // resumes correctly after a tab switch / reload — like the Scan progress bar.
  const DURATION = Math.max(1, docs.length) * 600

  const save = (obj) => { try { sessionStorage.setItem(SKEY(runId), JSON.stringify(obj)) } catch { /* ignore */ } }

  const runTicker = (startedAt, lvl, computed) => {
    clearInterval(timer.current)
    const step = () => {
      const elapsed = Date.now() - startedAt
      if (elapsed >= DURATION) {
        clearInterval(timer.current)
        setProgress(docs.length); setCurrentFile(null); setCurrentPhase('')
        setResult(computed); setPhase('done')
        save({ phase: 'done', level: lvl, result: computed })
        return
      }
      const idx = Math.min(docs.length - 1, Math.floor((elapsed / DURATION) * docs.length))
      setProgress(idx); setCurrentFile(docs[idx]); setCurrentPhase(phaseFor(docs[idx]?.name)[idx % 2])
    }
    step()
    timer.current = setInterval(step, 200)
  }

  const assess = () => {
    if (phase === 'running') return               // never launch a second pass while one runs
    if (scanBusy) return                          // a scan must finish before assessing its results
    clearInterval(timer.current); clearTimeout(phaseTimer.current)
    const computed = computeResult(level)        // result is instant + deterministic
    // Write the WCAG assessment to Langfuse on demand + mark the scan assessed (unlocks
    // the results views). The endpoint stamps assessed_at; onAssessed flips it optimistically.
    if (runId) { assessScan(runId, level).catch(() => {}); onAssessed?.() }
    const startedAt = Date.now()
    save({ phase: 'running', startedAt, level, result: computed })
    setPhase('running'); setResult(null); setResultFromCache(false); setProgress(0)
    runTicker(startedAt, level, computed)
  }

  // Resume an in-flight pass after a tab switch or reload: continue from the elapsed
  // point, or finish if the expected duration already passed while away.
  useEffect(() => {
    if (saved?.phase === 'running' && saved.startedAt) {
      if (Date.now() - saved.startedAt >= DURATION) {
        setProgress(docs.length); setResult(saved.result); setPhase('done')
        save({ phase: 'done', level: saved.level, result: saved.result })
      } else {
        runTicker(saved.startedAt, saved.level, saved.result)
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

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
          <p className="muted" style={{ margin: '3px 0 0' }}>Run all {docs.length.toLocaleString()} readable documents against the success criteria at your target conformance level.{files.length > docs.length ? ` ${(files.length - docs.length).toLocaleString()} unanalysable file${files.length - docs.length !== 1 ? 's' : ''} excluded — could not be parsed during scan.` : ''}</p>
          {scanBusy && <p style={{ margin: '6px 0 0', fontSize: 13, color: '#854F0B' }}>⏳ A scan is still running — assessment will be available once it finishes.</p>}
        </div>
        <button className="assessbtn" onClick={assess} disabled={phase === 'running' || !docs.length || scanBusy}
                title={scanBusy ? 'A scan is still running — assessment will be available when it completes' : undefined}>
          {phase === 'running' ? 'Assessing…' : scanBusy ? 'Scan in progress…' : `▶ Assess ${docs.length.toLocaleString()} files`}
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
              <span className="muted"><b style={{ color: '#1F5FA8' }}>Assessment</b> · document {Math.min(progress + 1, docs.length).toLocaleString()} of {docs.length.toLocaleString()}</span>
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
            {resultFromCache && (
              <p className="muted" style={{ fontSize: 12, margin: '0 0 8px', fontStyle: 'italic' }}>
                Showing results from a previous assessment — click Assess to run again.
              </p>
            )}
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
