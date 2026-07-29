import { useState, useRef, useEffect } from 'react'
import { allRules } from './rules'
import { WCAG } from './wcagCatalog.js'
import { assessScan, getCapability, getScan, refreshScanDriveToken } from './api.js'
import { CAPABILITY_FALLBACK, fmtOf, isAuto } from './capability.js'
import { TraceChip } from './Transparency.jsx'
import { assessLine } from './phaseNarration.js'
import { coreStats } from './coreStats.js'

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

// Real scan findings carry {rule_id, wcag, severity} but no conformance level, so derive
// it from the SC catalog (rules/*.js meta) keyed by the WCAG SC number.
const SC_LEVEL = Object.fromEntries(allRules.map((r) => [r.meta.id, r.meta.level]))
// The rule modules only cover the ~29 SCs with a remediator; ACP DETECTS more than it can
// fix (e.g. 1.4.9 / 1.4.6 / 2.4.9 — all AAA — via api/ocr.py & friends, which emit no level).
// Without a level those defaulted to 'A' and wrongly BLOCKED at an AA target. The hand-kept
// wcagCatalog carries the correct conformance level for every 2.1/2.2 SC — use it as the
// authoritative fallback so the AA filter counts an AAA finding as AAA, not A.
const CATALOG_LEVEL = Object.fromEntries(WCAG.map((c) => [c.sc, c.level]))
// Findings carry wcag as EITHER the engine form 'SC_1_1_1' (real scans + SIM) or the
// axe-style '1.1.1 name' — normalize both to the bare dotted SC. (A dotted-only match
// silently returned undefined for the 'SC_' form, which read every finding as human /
// not-auto once the auto flag became capability-derived.)
const scOf = (w) => ((String(w || '')).replace(/^SC_/, '').replace(/_/g, '.').match(/\d+\.\d+\.\d+/) || [])[0]
// Level of a finding: explicit field (SIM) → rule-module meta → full WCAG catalog → default A.
// The catalog step is what stops detector-only AAA criteria (1.4.9 etc.) from blocking at AA.
const levelOf = (x) => x.level || SC_LEVEL[scOf(x.wcag)] || CATALOG_LEVEL[scOf(x.wcag)] || 'A'
// Whether a finding CAN be auto-fixed is format-aware: the same criterion may be a
// deterministic fix on one file type and human-only on another (a docx contrast fix
// exists; a pdf one does not). Answered by the remediation-capability table for the
// file's format — never by a format-blind flag (which is why a docx used to read
// "0 auto-fixable"). This is a PRE-remediation capability, not a claim anything is fixed.
const autoOf = (cap, x, fmt) => isAuto(cap, fmt, scOf(x.wcag))

// Engine label shown per file type during scanning — mirrors what the real pipeline uses



// Persist the assessment per-scan in sessionStorage, so leaving the Assess tab (or even
// reloading) and coming back shows the result instead of resetting to idle. Self-contained
// — no reliance on parent state surviving an unmount/remount.
const SKEY = (id) => `acp-assess-${id || 'none'}`
const loadSaved = (id) => { try { return JSON.parse(sessionStorage.getItem(SKEY(id)) || 'null') } catch { return null } }

export default function AssessRunner({ files = [], runId, scanBusy = false, onAssessed, onPhase }) {
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
  // A deferred assess that opened NOTHING (0 scored of N) usually means the Drive sign-in expired
  // between Discover and Assess — surface a clear "sign in again" path instead of a silent 0%.
  const [accessFailed, setAccessFailed] = useState(false)
  // The scan itself is not loadable for this account (per-scan 404 — api.SCAN_UNAVAILABLE).
  // Distinct from accessFailed: there, the scan is ours and the DOCUMENTS wouldn't open; here
  // there is no scan to assess at all, so a conformance number over zero documents would be a
  // fabrication. Found live 2026-07-29 as "Assess produces no score": the catch below computed
  // a result from an empty `files` and rendered a completed 0/100.
  const [scanGone, setScanGone] = useState(null)
  // Remediation capability ({fmt: {sc: mode}}) — fetched once, seeded with the bundled
  // table so the auto-fixable counts are correct synchronously (and never regress to the
  // format-blind view if the fetch is slow or fails).
  const [cap, setCap] = useState(CAPABILITY_FALLBACK)
  useEffect(() => {
    let on = true
    getCapability().then((r) => { if (on && r?.capability) setCap(r.capability) }).catch(() => {})
    return () => { on = false }
  }, [])
  const timer = useRef(null)
  const phaseTimer = useRef(null)
  useEffect(() => () => { clearInterval(timer.current); clearTimeout(phaseTimer.current) }, [])
  // Report the phase up so the parent gates the Master Score on completion — it must not
  // appear until the assessment has actually run over all parsable files (phase 'done').
  useEffect(() => { onPhase?.(phase) }, [phase]) // eslint-disable-line react-hooks/exhaustive-deps

  const docs = files.filter((f) => f.score != null)
  const excludedCount = files.length - docs.length
  // Deferred model (ADR 0020): before Assess runs, files are 'discovered' (no score yet) — they
  // are ASSESSABLE, not excluded. The excluded/parsable framing only makes sense AFTER analysis, so
  // pre-assess we count every discovered file as assessable and suppress the "excluded" warning.
  const discoveredN = files.filter((f) => f.status === 'discovered').length
  const deferredPending = discoveredN > 0 && docs.length === 0
  const assessN = deferredPending ? files.length : docs.length
  const reset = () => {
    clearInterval(timer.current); clearTimeout(phaseTimer.current)
    setPhase('idle'); setResult(null); setResultFromCache(false); setProgress(0); setCurrentFile(null); setCurrentPhase('')
    try { sessionStorage.removeItem(SKEY(runId)) } catch { /* ignore */ }
  }

  // Deterministic conformance result over a set of scored docs at a WCAG level. Defaults to the
  // docs already in props (immediate model); the deferred path passes the freshly-analysed files.
  const computeResultFrom = (scored, lvl) => {
    const target = RANK[lvl]
    let conformant = 0, applicable = 0, autoFix = 0
    scored.forEach((f) => {
      const fmt = fmtOf(f)
      const blocking = (f.issues || []).filter((x) => RANK[levelOf(x)] <= target)
      applicable += blocking.length
      autoFix += blocking.filter((x) => autoOf(cap, x, fmt)).length
      if (!blocking.length) conformant++
    })
    // The tile leads with the DOCUMENT-CORE numbers so it reconciles exactly with the "By WCAG
    // criterion" table below (also the document-core lens) — no more "6 in the tile vs 4 in the
    // table". coreStats() is the shared source of that lens; RiskScore reads the SAME function
    // so the leadership panel can't disagree with this tile.
    const core = coreStats(scored, cap, lvl)
    const total = Math.max(1, scored.length)
    // Three aggregation levels, kept distinct so the UI can reconcile them: findings (individual
    // issues) → criteria (distinct WCAG rules) → documents. `applicable`/`autoFix` remain the
    // ALL-criteria totals (used elsewhere); the core* fields are the document-core subset the tile leads with.
    return { level: lvl, total, conformant, failing: total - conformant, applicable, autoFix,
             coreFindings: core.coreFindings, coreCriteria: core.coreCriteria, coreAutoFix: core.coreAutoFix,
             pct: Math.round((conformant / total) * 100) }
  }
  const computeResult = (lvl) => computeResultFrom(docs, lvl)

  // Time-based cosmetic pass. Floor at 1.5s so even a handful of files still reads as real
  // work happening (80ms/doc alone was as little as 80-800ms for small estates — gone before
  // a person can register the bar moving); capped at 6s so it doesn't drag on large ones.
  const DURATION = Math.min(Math.max(1500, docs.length * 80), 6000)

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
      setProgress(idx); setCurrentFile(docs[idx]); setCurrentPhase(assessLine(idx))
    }
    step()
    timer.current = setInterval(step, 200)
  }

  // Deferred model (ADR 0020): Assess just KICKED OFF the real download+WCAG analysis. Poll the
  // scan until it's assessed, driving progress off the true per-file count, then compute the
  // result from the freshly-scored files. This is real work, not a cosmetic ticker.
  const pollDeferred = (startedAt) => {
    clearInterval(timer.current)
    const tick = () => {
      getScan(runId).then((data) => {
        const run = data?.run || {}
        const fs = data?.files || []
        const scored = fs.filter((f) => f.score != null)
        const total = run.files || fs.length || 1
        setProgress(Math.min(scored.length, total))
        setCurrentPhase(`Opening & assessing ${scored.length} of ${total}…`)
        // The first file with no score yet is the one in flight. `currentFile` state has
        // existed since this component was written but was never populated or rendered, so a
        // long scan showed a moving bar and no indication of what it was moving through.
        const nextUp = fs.find((x) => x.score == null)
        setCurrentFile(nextUp ? (nextUp.name || null) : null)
        if (run.assessed_at || run.finalized_at) {
          clearInterval(timer.current)
          const computed = computeResultFrom(scored, level)
          setProgress(scored.length); setCurrentFile(null); setCurrentPhase('')
          // Opened nothing → almost always an expired Drive sign-in in the deferred model.
          setAccessFailed(scored.length === 0 && total > 0)
          setResult(computed); setPhase('done')
          onAssessed?.()
          save({ phase: 'done', level, result: computed })
        }
      }).catch((e) => {
        // An unloadable scan is NOT transient — it will 404 for as long as this tab holds the
        // id. Polling it was the ~60s of invisible retries in the live incident. Stop, and say so.
        if (e?.scanUnavailable) {
          clearInterval(timer.current)
          setPhase('idle'); setProgress(0); setCurrentFile(null); setCurrentPhase('')
          setScanGone(e.message)
          try { sessionStorage.removeItem(SKEY(runId)) } catch { /* ignore */ }
          return
        }
        /* transient poll error — keep polling */
      })
    }
    tick()
    timer.current = setInterval(tick, 2000)
  }

  const assess = () => {
    if (phase === 'running') return               // never launch a second pass while one runs
    if (scanBusy) return                          // a scan must finish before assessing its results
    if (!runId) return
    clearInterval(timer.current); clearTimeout(phaseTimer.current)
    const startedAt = Date.now()
    setPhase('running'); setResult(null); setResultFromCache(false); setProgress(0); setAccessFailed(false); setScanGone(null)
    // ADR 0020: in the deferred model the DOWNLOAD happens now, at Assess — but GIS Drive tokens
    // live ~1h and are held in-memory per scan, so a scan discovered a while ago (or after a
    // container restart) has a stale/absent token and every file would 401. Push a fresh Drive
    // token from the live session first (best-effort; the endpoint 422s harmlessly for a local /
    // SharePoint scan with no token). Then kick off the assessment.
    Promise.resolve(refreshScanDriveToken(runId)).catch(() => {}).then(() => assessScan(runId, level)).then((resp) => {
      if (resp && resp.deferred) {
        // The analysis is running now — track it for real.
        save({ phase: 'running', startedAt, level, deferred: true })
        pollDeferred(startedAt)
      } else {
        // Immediate model: results already exist. Optimistic reveal + cosmetic pass over them.
        onAssessed?.()
        const computed = computeResult(level)
        save({ phase: 'running', startedAt, level, result: computed })
        runTicker(startedAt, level, computed)
      }
    }).catch((e) => {
      // A scan this account cannot load has NOTHING already scored, so the fallback below would
      // present a conformance verdict computed over zero documents — the live "no score on
      // Assess". Never score an absent scan; report it.
      if (e?.scanUnavailable) {
        setPhase('idle'); setProgress(0)
        setScanGone(e.message)
        try { sessionStorage.removeItem(SKEY(runId)) } catch { /* ignore */ }
        return
      }
      // On any OTHER error fall back to the immediate behaviour over whatever is already scored.
      onAssessed?.()
      const computed = computeResult(level)
      save({ phase: 'running', startedAt, level, result: computed })
      runTicker(startedAt, level, computed)
    })
  }

  // Resume an in-flight pass after a tab switch or reload: continue from the elapsed
  // point, or finish if the expected duration already passed while away.
  useEffect(() => {
    if (saved?.phase === 'running') {
      if (saved.deferred) { pollDeferred(saved.startedAt || Date.now()); return }
      if (saved.startedAt) {
        if (Date.now() - saved.startedAt >= DURATION) {
          setProgress(docs.length); setResult(saved.result); setPhase('done')
          save({ phase: 'done', level: saved.level, result: saved.result })
        } else {
          runTicker(saved.startedAt, saved.level, saved.result)
        }
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [docs.length])

  const note = result && (result.level === 'A'
    ? 'Level A is the floor — only must-have criteria block conformance.'
    : result.level === 'AA'
      ? 'Level AA is the legal target for ADA Title II, the EAA and Section 508 — Level A + AA findings both count.'
      : 'Level AAA is the enhanced bar — every A, AA and AAA finding counts, so conformance is strictest here.')

  const pct = phase === 'running' ? Math.round((progress / Math.max(1, assessN, docs.length)) * 100) : 0

  return (
    <section className="panel assesspanel">
      <div className="assesshd">
        <div>
          <h2 style={{ margin: 0 }}>Assess the estate against WCAG 2.1</h2>
          <p className="muted" style={{ margin: '3px 0 0' }}>
            {deferredPending
              ? <>Run all {assessN.toLocaleString()} discovered documents — Assess opens each file and scores it against the success criteria at your target conformance level.</>
              : <>Run all {assessN.toLocaleString()} readable documents against the success criteria at your target conformance level.</>}
          </p>
          {!deferredPending && excludedCount > 0 && (
            <p style={{ margin: '5px 0 0', fontSize: 12.5, color: '#854F0B', background: '#FAEEDA', border: '1px solid #E8C98A', borderRadius: 6, padding: '5px 10px', display: 'inline-block' }}>
              ⚠ {excludedCount} of {files.length} files excluded — could not be parsed during scan (password-protected, unsupported format, or corrupt). Only {docs.length} parsable files are assessed.
            </p>
          )}
          {scanBusy && <p style={{ margin: '6px 0 0', fontSize: 13, color: '#854F0B' }}>⏳ A scan is still running — assessment will be available once it finishes.</p>}
        </div>
        <button className="assessbtn" onClick={assess} disabled={phase === 'running' || !assessN || scanBusy}
                style={phase === 'done' ? { background: 'transparent', color: '#1F5FA8', border: '1.5px solid #9DBCE4', fontWeight: 600 } : undefined}
                title={scanBusy ? 'A scan is still running — assessment will be available when it completes'
                       : phase === 'done' ? 'Already assessed — re-run only if you changed the target level or re-scanned' : undefined}>
          {phase === 'running' ? 'Assessing…'
            : scanBusy ? 'Scan in progress…'
            : phase === 'done' ? `↻ Re-assess ${assessN.toLocaleString()} files`
            : `▶ Assess ${assessN.toLocaleString()} files`}
        </button>
      </div>

      <div className="lvlseg" role="radiogroup" aria-label="Target conformance level">
        {LEVELS.map((l) => (
          <button key={l.k} role="radio" aria-checked={level === l.k} className={level === l.k ? 'lvlchip on' : 'lvlchip'} onClick={() => { setLevel(l.k); reset() }} disabled={phase === 'running'}>
            <b>{l.k}</b><span>{l.desc}</span>
          </button>
        ))}
      </div>
      <p className="muted" style={{ fontSize: 12, margin: '4px 0 0', lineHeight: 1.5 }}>
        The level controls <b>which WCAG success criteria count as blocking</b> — not which files are scanned. All {assessN} {deferredPending ? 'discovered' : 'parsable'} files are always assessed; at <b>A</b> only Level A findings block conformance, at <b>AA</b> both A + AA findings count (the legal target for ADA / EAA), and at <b>AAA</b> all findings count. Changing the level resets the result so you can re-run at the new target.
      </p>

      <div role="status" aria-live="polite">
        {phase === 'running' && (
          <div className="assessrun">
            <div className="assessbar">
              <i style={{ width: `${pct}%` }} />
            </div>
            <div className="assessrunmeta">
              <span className="muted"><b style={{ color: '#1F5FA8' }}>Computing conformance</b> · {docs.length.toLocaleString()} documents at WCAG 2.1 {level}</span>
              <span className="assesspct">{pct}%</span>
            </div>
            {(currentFile || currentPhase) && (
              <div className="assessnow" title={currentFile || ''}>
                {currentFile
                  ? <>Reading <b>{currentFile}</b> — checking all {ruleCount} criteria</>
                  : currentPhase}
              </div>
            )}
          </div>
        )}
        {scanGone && (
          <div role="alert" style={{ margin: '4px 0 12px', padding: '11px 14px', borderRadius: 8, fontSize: 13.5,
               background: '#FBE9E7', border: '1px solid #E7B4AC', color: '#8A2A20' }}>
            ⚠ <b>No score — this scan can’t be opened.</b> {scanGone} Nothing was assessed, so there
            is no result to show. Pick one of your own scans from <b>Time-travel</b>, or run a new
            scan from <b>Discover</b>.
          </div>
        )}
        {phase === 'done' && accessFailed && (
          <div style={{ margin: '4px 0 12px', padding: '11px 14px', borderRadius: 8, fontSize: 13.5,
               background: '#FBE9E7', border: '1px solid #E7B4AC', color: '#8A2A20' }}>
            ⚠ <b>Assess couldn’t open any of these documents.</b> If they’re on Google Drive, your
            sign-in has most likely expired since Discover ran — <b>sign in again</b> and re-run
            Assess. (If they aren’t on Drive, the files may be password-protected or an unsupported
            format.)
            <div style={{ marginTop: 8 }}>
              <button className="ghost small" onClick={assess} disabled={phase === 'running' || scanBusy}>↻ Re-run Assess</button>
            </div>
          </div>
        )}
        {phase === 'done' && result && !accessFailed && (
          <div className="assessres">
            {resultFromCache && (
              <p className="muted" style={{ fontSize: 12, margin: '0 0 8px', fontStyle: 'italic' }}>
                Showing results from a previous assessment — click Assess to run again.
              </p>
            )}
            {/* Actionability-first verdict (Scan → Understand → Fix): answer "what do I need to
                fix, and can ACP fix it?" in plain language BEFORE the WCAG taxonomy below. All
                counts are the document-core numbers, so they reconcile with the tiles + the
                "By WCAG criterion" table. */}
            {result.failing > 0 ? (
              <div style={{ margin: '0 0 12px', padding: '12px 14px', borderRadius: 8, background: '#FBF1E3', border: '1px solid #E8C98A' }}>
                <div style={{ fontSize: 14.5, fontWeight: 700, color: '#7A4A0B' }}>⚠ Needs attention — what to fix</div>
                <div style={{ fontSize: 13.5, margin: '5px 0 0', color: '#3D3A34', lineHeight: 1.5 }}>
                  <b>{result.coreFindings.toLocaleString()}</b> issue{result.coreFindings !== 1 ? 's' : ''} across <b>{result.coreCriteria.toLocaleString()}</b> WCAG criteria in <b>{result.failing.toLocaleString()}</b> of <b>{result.total.toLocaleString()}</b> document{result.total !== 1 ? 's' : ''}.
                  {' '}<b style={{ color: '#3B6D11' }}>{result.coreAutoFix.toLocaleString()}</b> ACP can fix automatically · <b style={{ color: '#854F0B' }}>{(result.coreFindings - result.coreAutoFix).toLocaleString()}</b> need a person.
                </div>
              </div>
            ) : (
              <div style={{ margin: '0 0 12px', padding: '12px 14px', borderRadius: 8, background: '#EDF6E4', border: '1px solid #B7D89B' }}>
                <div style={{ fontSize: 14.5, fontWeight: 700, color: '#3B6D11' }}>✓ Ready to certify</div>
                <div style={{ fontSize: 13.5, margin: '5px 0 0', color: '#3D3A34' }}>
                  No blocking findings at WCAG 2.1 {result.level} — all {result.total.toLocaleString()} document{result.total !== 1 ? 's' : ''} pass the document core.
                </div>
              </div>
            )}
            <div className="assesstiles">
              <div className="atile" title={`Documents with zero blocking findings at WCAG 2.1 ${result.level} — they pass as-is`}>
                <b style={{ color: '#3B6D11' }}>{result.conformant.toLocaleString()}</b>
                <span>documents pass <span className="muted">· of {result.total.toLocaleString()}</span></span>
              </div>
              <div className="atile" title={`Documents with at least one finding that blocks WCAG 2.1 ${result.level} conformance — one blocking finding fails the whole document`}>
                <b style={{ color: '#854F0B' }}>{result.failing.toLocaleString()}</b>
                <span>documents blocked <span className="muted">· of {result.total.toLocaleString()}</span></span>
              </div>
              <div className="atile" title={`${result.conformant.toLocaleString()} of ${result.total.toLocaleString()} documents pass — the estate's pass rate at this level`}>
                <b style={{ color: '#1F5FA8' }}>{result.pct}%</b>
                <span>pass rate at {result.level}</span>
              </div>
              <div className="atile" title={`${result.coreFindings.toLocaleString()} findings across ${result.coreCriteria.toLocaleString()} document-core WCAG criteria (the 20 shown in the table below) at ${result.level}. ${result.coreAutoFix.toLocaleString()} can be fixed automatically from the Remediate tab; the rest need a person. Reconciles with the "By WCAG criterion" table below.`}>
                <b>{result.coreFindings.toLocaleString()}</b>
                <span>issues found <span className="muted">· across {result.coreCriteria.toLocaleString()} criteria · {result.coreAutoFix.toLocaleString()} auto-fixable, {(result.coreFindings - result.coreAutoFix).toLocaleString()} need review</span></span>
              </div>
            </div>
            <p className="muted assessnote">{note}</p>
            <div style={{ marginTop: 8 }}><TraceChip scanId={runId} kind="session" label="View this scan's traces in Langfuse" /></div>
          </div>
        )}
      </div>
    </section>
  )
}
