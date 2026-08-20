import { useState, useRef, useEffect } from 'react'
import { allRules } from './rules'
import { WCAG } from './wcagCatalog.js'
import { assessScan, getCapability, getScan, getScanTraces, refreshScanDriveToken } from './api.js'
import { CAPABILITY_FALLBACK, fmtOf, isAuto } from './capability.js'
import { TraceChip } from './Transparency.jsx'
import { assessLine } from './phaseNarration.js'
import { coreStats } from './coreStats.js'
// Separate line on purpose: coreStats.test.js pins the exact `import { coreStats } from
// './coreStats.js'` line as its no-drift guard, and widening the braces would have meant
// loosening someone else's assertion to accommodate this change.
import { scOfWcag } from './coreStats.js'
import { SCOPE_SCS, SCOPE_SIZE, SCOPE_LABEL } from './activeScope.js'
import { fmtEffort, estimateEffortMin, EFFORT_BASIS } from './effort.js'

// Re-assess the whole estate against a chosen WCAG 2.1 conformance level. A finding blocks
// conformance when its level is at or below the target (A ⊆ AA ⊆ AAA), so the numbers
// genuinely shift with the level — this is a real computation over the assessed findings,
// not a cosmetic toggle.
const RANK = { A: 1, AA: 2, AAA: 3 }

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
// The blocking conformance level is DERIVED from the success criteria the user already chose
// (activeScope.SCOPE_SCS), not picked a second time here: it is the highest WCAG level present in
// that set — any AAA criterion in scope makes the target AAA, otherwise AA (the legal ADA/EAA/508
// floor, and what the standard docx scope resolves to). One source of truth for "which criteria
// matter" — the scope — instead of a separate A/AA/AAA selector that could disagree with it.
const deriveLevel = (scs) => {
  let maxR = 0
  for (const sc of scs) { const r = RANK[CATALOG_LEVEL[sc] || SC_LEVEL[sc] || 'A'] || 1; if (r > maxR) maxR = r }
  return maxR >= 3 ? 'AAA' : maxR === 1 ? 'A' : 'AA'
}
const DERIVED_LEVEL = deriveLevel(SCOPE_SCS)
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
// Both assess paths report the in-flight file, and they disagreed about its shape: the ticker
// handed over the whole record (which renders as "Objects are not valid as a React child") and
// the deferred poll read `.name`, a field file_records has never had — store.py selects `file`,
// so that path resolved to null and showed nothing at all. One extractor, so the two paths
// cannot drift apart again.
const nameOf = (f) => (typeof f === 'string' ? f : f?.file || f?.name || null)

const SKEY = (id) => `acp-assess-${id || 'none'}`
const loadSaved = (id) => { try { return JSON.parse(sessionStorage.getItem(SKEY(id)) || 'null') } catch { return null } }

export default function AssessRunner({ files = [], runId, scanBusy = false, onAssessed, onPhase }) {
  const saved = loadSaved(runId)
  // Derived from the selected scope, not a picker — see deriveLevel above.
  const level = DERIVED_LEVEL
  // Deva's Assess filter #6: ignore files a discovery rule flagged for archival or deletion. ON by
  // default — the run already skips them (PRD §4.5), and this surfaces that as a controllable choice
  // rather than a silent one. Unchecking sends the authorized include-flagged override to the run.
  const [ignoreLifecycle, setIgnoreLifecycle] = useState(true)
  const [phase, setPhase] = useState(saved?.phase || 'idle') // idle | running | done
  const [progress, setProgress] = useState(0)
  const [currentFile, setCurrentFile] = useState(null)
  const [currentPhase, setCurrentPhase] = useState('')
  // Per-document progress, shown UNDER the bar. A percentage says how far along the run is; it
  // cannot say which documents are done, which is the thing a person watching actually wants —
  // and on a deferred run the header's own count read "0 documents" the whole time because
  // `docs` filters on a score the files do not have yet.
  const [liveFiles, setLiveFiles] = useState([])      // [{ file, score, done }]
  const [liveTotal, setLiveTotal] = useState(0)       // run.files — the REAL total, not docs.length
  // Failing criteria per finished document, fetched once each and cached. Keyed by filename, so a
  // file is never re-fetched no matter how many times the poll sees it.
  const [failedScs, setFailedScs] = useState({})
  const scsWanted = useRef(new Set())
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
    // The tile leads with the ACTIVE-SCOPE numbers so it reconciles exactly with the "By WCAG
    // criterion" table below (scoped the same way) — no more "6 in the tile vs 4 in the table".
    // coreStats() is the shared source of that lens and defaults to the agreed scope, which is
    // what the table defaults to; RiskScore reads the SAME function so the leadership panel
    // can't disagree with this tile.
    const core = coreStats(scored, cap, lvl)
    const total = Math.max(1, scored.length)
    // Three aggregation levels, kept distinct so the UI can reconcile them: findings (individual
    // issues) → criteria (distinct WCAG rules) → documents. `applicable`/`autoFix` remain the
    // ALL-criteria totals (used elsewhere); the core* fields are the document-core subset the tile leads with.
    return { level: lvl, total, conformant, failing: total - conformant, applicable, autoFix,
             coreFindings: core.coreFindings, coreCriteria: core.coreCriteria, coreAutoFix: core.coreAutoFix,
             scopeTotal: core.scopeTotal, scopeLabel: core.scopeLabel,
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
      setProgress(idx); setCurrentFile(nameOf(docs[idx])); setCurrentPhase(assessLine(idx))
      // Same per-document list the deferred path builds, so the demo shows the real component
      // rather than a second implementation that could drift from it. The criteria come from
      // each file's OWN issues — sim data, but not invented here.
      setLiveTotal(docs.length)
      setLiveFiles(docs.map((d, i) => ({ file: nameOf(d), path: d.file || nameOf(d),
                                         score: d.score, done: i < idx, status: d.status })))
      setFailedScs(Object.fromEntries(docs.slice(0, idx).map((d) => [
        d.file || nameOf(d),
        [...new Set((d.issues || []).map((x) => scOfWcag(x.wcag)).filter(Boolean))].sort(),
      ])))
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
        // Feed the per-document list straight off the poll — no extra request. `status` and
        // `score` are already in this payload; only the failing criteria need fetching.
        setLiveTotal(total)
        setLiveFiles(fs.map((x) => ({ file: nameOf(x), path: x.file, score: x.score,
                                      done: x.score != null, status: x.status })))
        // One traces call per document, the first time it finishes. Scan-wide traces would be
        // file x rule rows on every tick — 5,000+ on a 258-document estate, several times a
        // second — so this asks per file and never asks twice.
        for (const f of fs) {
          if (f.score == null || !f.file || scsWanted.current.has(f.file)) continue
          scsWanted.current.add(f.file)
          getScanTraces(runId, f.file)
            .then((rows) => {
              const bad = (rows || []).filter((r) => r.outcome === 'FAIL')
                .map((r) => r.rule_id).filter(Boolean)
              setFailedScs((m) => ({ ...m, [f.file]: [...new Set(bad)].sort() }))
            })
            .catch(() => { /* best-effort detail — never block or fail the assessment on it */ })
        }
        // The first file with no score yet is the one in flight. `currentFile` state has
        // existed since this component was written but was never populated or rendered, so a
        // long scan showed a moving bar and no indication of what it was moving through.
        setCurrentFile(nameOf(fs.find((x) => x.score == null)))
        if (run.assessed_at || run.finalized_at) {
          clearInterval(timer.current)
          const computed = computeResultFrom(scored, level)
          setProgress(scored.length); setCurrentFile(null); setCurrentPhase('')
          // Opened nothing → almost always an expired Drive sign-in in the deferred model.
          setAccessFailed(scored.length === 0 && total > 0)
          setResult(computed); setPhase('done')
          // Persist BEFORE announcing. The announcement makes App refetch the scan, which changes
          // `files` → `docs.length` → the resume effect below re-reads sessionStorage; if that
          // still said 'running' the effect would start a SECOND poller over a finished run.
          save({ phase: 'done', level, result: computed })
          onAssessed?.()
          // The worker has only just written file_records. Every OTHER surface holding this scan
          // is still rendering the payload fetched before Assess — under ADR 0020 that is the
          // inventory fallback (status 'discovered', score null, issues []), which the inventory
          // renders as "not assessed". Nothing refetches on its own, so those rows stay wrong
          // indefinitely even though the findings now exist and the drawer shows them. Announce
          // completion the way remediate-now does (#86) and let App re-read the scan once.
          //
          // Fired HERE, at finalize, not when POST /assess returns: the deferred response is
          // {phase: 'assessing', deferred: true} and stamps no assessed_at, so a refetch then
          // would re-read the same pre-Assess inventory and change nothing.
          window.dispatchEvent(new CustomEvent('acp:scan-assessed', { detail: { scanId: runId } }))
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
    Promise.resolve(refreshScanDriveToken(runId)).catch(() => {}).then(() => assessScan(runId, level, !ignoreLifecycle)).then((resp) => {
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

  // How many criteria the in-flight file is actually being weighed against. This is the SAME
  // list the result tile and the "By WCAG criterion" table reconcile to — the agreed scope
  // (activeScope.SCOPE_SCS) — narrowed to the levels that block at the chosen target, so the
  // progress line cannot claim a wider assessment than the result it leads to. That constraint
  // is why it follows the scope rather than the 20-check document core: the engine still runs
  // every detector it has, but the assessment this run REPORTS is the scoped one, and a progress
  // line promising 20 followed by a result over 14 is the mismatch this was derived to avoid.
  // Derived, not hardcoded: at level A the AA criteria in that set do not count, and the number
  // has to move with the level selector or it is just decoration.
  const ruleCount = [...SCOPE_SCS].filter((sc) => RANK[CATALOG_LEVEL[sc]] <= RANK[level]).length

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

      <p className="muted" style={{ fontSize: 12, margin: '4px 0 0', lineHeight: 1.5 }}>
        Scored against <b>WCAG 2.1 Level {level}</b>{level === 'AA' ? ' — the legal target for ADA / EAA / 508' : ''}, derived
        from the <b>{ruleCount}</b> success criteria you selected in your {SCOPE_LABEL}. A finding blocks conformance when its
        criterion is at or below Level {level}. All {assessN} {deferredPending ? 'discovered' : 'parsable'} files are assessed.
      </p>

      {phase !== 'running' && (
        <label className="assess-lifecycle-ignore" style={{ display: 'flex', alignItems: 'flex-start', gap: 8, margin: '8px 0 0', fontSize: 12.5, lineHeight: 1.5, cursor: 'pointer' }}>
          <input type="checkbox" checked={ignoreLifecycle} onChange={(e) => setIgnoreLifecycle(e.target.checked)}
                 aria-label="Ignore files flagged for archival or deletion" style={{ marginTop: 2 }} />
          <span>
            <b>Ignore files flagged for archival or deletion</b>
            <span className="muted"> — files a discovery rule marked <i>Archive Candidate</i>, <i>Archived</i>, <i>Delete&nbsp;Candidate</i> or <i>Deleted</i> are skipped; there is no point assessing a document you are about to remove. Uncheck to assess them anyway.</span>
          </span>
        </label>
      )}

      <div role="status" aria-live="polite">
        {phase === 'running' && (
          <div className="assessrun">
            <div className="assessbar">
              <i style={{ width: `${pct}%` }} />
            </div>
            <div className="assessrunmeta">
              <span className="muted"><b style={{ color: '#1F5FA8' }}>Computing conformance</b> · {(liveTotal || docs.length).toLocaleString()} documents at WCAG 2.1 {level}</span>
              <span className="assesspct">{pct}%</span>
            </div>
            {(currentFile || currentPhase) && (
              <div className="assessfile">
                {currentFile && <span className="assessfname" title={currentFile}>{currentFile}</span>}
                {currentFile && <span className="assessengine" title={`The ${ruleCount} criteria in your ${SCOPE_LABEL} that block at level ${level} — the same list the result below is scored over`}>{ruleCount} criteria in scope</span>}
                {currentPhase && <span className="muted assessphase">{currentPhase}</span>}
              </div>
            )}
            {liveFiles.length > 0 && (
              <ul className="assesslist" aria-label="Per-document assessment progress">
                {liveFiles.map((f) => {
                  const scs = failedScs[f.path]
                  return (
                    <li key={f.path} className={f.done ? 'done' : 'pending'}>
                      <span className="alstate" aria-hidden="true">{f.done ? '\u2713' : '\u25CB'}</span>
                      <span className="alname" title={f.path}>{f.file}</span>
                      {f.done
                        ? <>
                            <span className="alscore">{f.score}/100</span>
                            {/* The criteria this document FAILED, by number. An empty array is a
                                real answer — it means nothing failed — so it renders as such
                                rather than as a spinner that never resolves. */}
                            {scs === undefined
                              ? <span className="muted alscs">reading criteria…</span>
                              : scs.length
                                ? <span className="alscs">{scs.map((c) => <b key={c}>{c}</b>)}</span>
                                : <span className="alclean">no failures</span>}
                          </>
                        : <span className="muted alscs">{f.status === 'analysed' ? 'scoring…' : 'queued'}</span>}
                    </li>
                  )
                })}
              </ul>
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
                counts are the agreed-scope numbers, so they reconcile with the tiles + the
                "By WCAG criterion" table. */}
            {result.failing > 0 ? (
              <div style={{ margin: '0 0 12px', padding: '12px 14px', borderRadius: 8, background: '#FBF1E3', border: '1px solid #E8C98A' }}>
                <div style={{ fontSize: 14.5, fontWeight: 700, color: '#7A4A0B' }}>⚠ Needs attention — what to fix</div>
                <div style={{ fontSize: 13.5, margin: '5px 0 0', color: '#3D3A34', lineHeight: 1.5 }}>
                  <b>{result.coreFindings.toLocaleString()}</b> issue{result.coreFindings !== 1 ? 's' : ''} across <b>{result.coreCriteria.toLocaleString()}</b> of the <b>{result.scopeTotal ?? SCOPE_SIZE}</b> WCAG criteria in your {result.scopeLabel || SCOPE_LABEL}, in <b>{result.failing.toLocaleString()}</b> of <b>{result.total.toLocaleString()}</b> document{result.total !== 1 ? 's' : ''}.
                  {' '}<b style={{ color: '#3B6D11' }}>{result.coreAutoFix.toLocaleString()}</b> ACP can fix automatically · <b style={{ color: '#854F0B' }}>{(result.coreFindings - result.coreAutoFix).toLocaleString()}</b> need a person.
                </div>
              </div>
            ) : (
              <div style={{ margin: '0 0 12px', padding: '12px 14px', borderRadius: 8, background: '#EDF6E4', border: '1px solid #B7D89B' }}>
                <div style={{ fontSize: 14.5, fontWeight: 700, color: '#3B6D11' }}>✓ Ready to certify</div>
                <div style={{ fontSize: 13.5, margin: '5px 0 0', color: '#3D3A34' }}>
                  No blocking findings at WCAG 2.1 {result.level} — all {result.total.toLocaleString()} document{result.total !== 1 ? 's' : ''} pass the {result.scopeTotal ?? SCOPE_SIZE} criteria in your {result.scopeLabel || SCOPE_LABEL}.
                </div>
              </div>
            )}
            {/* Four decision-first KPI cards. Every number is read from `result` (→ coreStats, the
                one estate lens AssessRunner + RiskScore share), so they cannot disagree with the
                verdict above or the "By WCAG criterion" table below. The old "pass rate %" tile is
                deliberately GONE: it was a third rendering of the same estate failure already shown
                as the master-score ring and the risk score below — the duplication the redesign
                removes. Documents are now framed as "need action" (the decision), not "pass %". */}
            {(() => {
              const person = result.coreFindings - result.coreAutoFix
              const addrPct = result.coreFindings ? Math.round((result.coreAutoFix / result.coreFindings) * 100) : 0
              const effortMin = estimateEffortMin({ auto: result.coreAutoFix, person })
              const denom = result.scopeTotal ?? SCOPE_SIZE
              const scopeLbl = result.scopeLabel || SCOPE_LABEL
              return (
                <div className="assesstiles">
                  {/* KPI 1 — documents requiring action (the decision), not a pass rate */}
                  <div className="atile" title={`${result.failing.toLocaleString()} of ${result.total.toLocaleString()} documents have at least one finding that blocks WCAG 2.1 ${result.level}; ${result.conformant.toLocaleString()} pass as-is.`}>
                    <b style={{ color: result.failing ? '#854F0B' : '#3B6D11' }}>{result.failing.toLocaleString()}<span className="atile-den"> / {result.total.toLocaleString()}</span></b>
                    <span>documents need action <span className="muted">· {result.conformant.toLocaleString()} currently pass</span></span>
                  </div>
                  {/* KPI 2 — findings, with their criteria denominator */}
                  <div className="atile" title={`${result.coreFindings.toLocaleString()} findings across ${result.coreCriteria.toLocaleString()} of the ${denom} WCAG criteria in your ${scopeLbl}. Counted over the same list the "By WCAG criterion" table below defaults to, so the two reconcile.`}>
                    <b>{result.coreFindings.toLocaleString()}</b>
                    <span>findings <span className="muted">· across {result.coreCriteria.toLocaleString()} of {denom} criteria</span></span>
                  </div>
                  {/* KPI 3 — ACP-addressable (deterministic auto-fix) */}
                  <div className="atile" title={`${result.coreAutoFix.toLocaleString()} of ${result.coreFindings.toLocaleString()} findings ACP can fix automatically (deterministic) from the Remediate tab; the remaining ${person.toLocaleString()} need a person.`}>
                    <b style={{ color: '#3B6D11' }}>{result.coreAutoFix.toLocaleString()}<span className="atile-den"> · {addrPct}%</span></b>
                    <span>ACP fixes automatically <span className="muted">· {person.toLocaleString()} need a person</span></span>
                  </div>
                  {/* KPI 4 — estimated human effort (planning heuristic; est./EFFORT_BASIS per effort.js) */}
                  <div className="atile" title={EFFORT_BASIS}>
                    <b style={{ color: '#854F0B' }}>{fmtEffort(effortMin)}</b>
                    <span>human effort <span className="muted">· {person.toLocaleString()} findings need review</span></span>
                  </div>
                </div>
              )
            })()}
            <p className="muted assessnote">{note}</p>
            <div style={{ marginTop: 8 }}><TraceChip scanId={runId} kind="session" label="View this scan's traces" /></div>
          </div>
        )}
      </div>
    </section>
  )
}
