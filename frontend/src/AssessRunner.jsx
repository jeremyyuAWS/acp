import { useState, useRef, useEffect } from 'react'
import { allRules } from './rules'
import { WCAG } from './wcagCatalog.js'
import { assessScan, getCapability, getScan, getScanLive, getScanTraces, refreshScanDriveToken, getQueueJob, setWorkers, getQueueEstimate } from './api.js'
import { subscribeJobs } from './jobsFeed.js'
import { CAPABILITY_FALLBACK, fmtOf, isAuto } from './capability.js'
import WorkerReplicaControl from './WorkerReplicaControl.jsx'
import ProcessingStatusPanel from './ProcessingStatusPanel.jsx'
import { deriveProcessingState } from './processingState.js'
import { assessLine } from './phaseNarration.js'
import { coreStats } from './coreStats.js'
// Separate line on purpose: coreStats.test.js pins the exact `import { coreStats } from
// './coreStats.js'` line as its no-drift guard, and widening the braces would have meant
// loosening someone else's assertion to accommodate this change.
import { scOfWcag } from './coreStats.js'
import { SCOPE_SCS, SCOPE_LABEL } from './activeScope.js'

// Worker-tier health, as THREE states plus the local case — not the boolean the strip used to
// render.
//
// `worker_tier_alive` is `age <= 120s`, so `false` collapses two different facts: a tier that
// beat 140s ago and is late, and a tier that has never beaten at all. store.py's
// worker_tier_status() keeps them apart deliberately — "Age is None when no worker has EVER
// beaten […] which is a different failure from one that stopped, and reads differently in an
// alert" — and /jobs has carried `worker_heartbeat_age_s` all along. This file discarded it and
// printed a confident "offline" for both, which is a claim the client cannot support: absence of
// a heartbeat is absence of evidence, and it must not read as evidence of absence OR of health.
//
// TOPOLOGY decides which signal even applies. In an in-process deployment there is no separate
// tier, so its heartbeat is permanently absent and says nothing; health there is simply whether
// the local pool has workers. Reading the tier heartbeat in that deployment is how "Worker
// service offline" appeared beside a local pool that was busily working.
export function deriveWorkerHealth(snap) {
  if (!snap) return { state: 'unknown', label: 'status unknown', tone: 'unknown' }
  if (snap.runtime_mode !== 'distributed') {
    return snap.workers > 0
      ? { state: 'local', label: 'online', tone: 'ok' }
      : { state: 'no_local', label: 'no local workers', tone: 'warn' }
  }
  if (snap.heartbeatAgeS === null || snap.heartbeatAgeS === undefined) {
    return { state: 'unknown', label: 'status unknown', tone: 'unknown' }
  }
  if (snap.alive) return { state: 'online', label: 'online', tone: 'ok' }
  const mins = Math.floor(snap.heartbeatAgeS / 60)
  const ago = mins >= 1 ? `${mins}m` : `${Math.round(snap.heartbeatAgeS)}s`
  return { state: 'stale', label: `not responding · last beat ${ago} ago`, tone: 'warn' }
}
const HEALTH_TONE = { ok: '#1a7f37', warn: '#854F0B', unknown: '#5B6472' }

// A job status the queue will not act on again without a person asking.
//
// 'dead' is attempts-exhausted or a non-retryable class; 'cancelled' was stopped deliberately or
// superseded. Both mean the same thing to the user — nothing further happens on its own — and
// neither was distinguishable from a slow run on this screen: 'cancelled' had no branch at all
// and fell through to "Running · 4m", which is a claim about work that is not happening.
export const TERMINAL_JOB_STATUS = ['dead', 'cancelled']
export function isTerminalJob(status) {
  return TERMINAL_JOB_STATUS.includes(status)
}

// Whether anything OBSERVED says this run is moving.
//
// A worker heartbeat is not evidence of it. The heartbeat proves the worker process answered
// recently; it says nothing about this job, and a worker crash-looping on one document beats
// freshly between restarts while making no progress at all — which is how the 2026-08-30 incident
// looked from this screen. store.py's own oldest_queued_job docstring makes the same argument:
// "a fresh heartbeat proves the worker CONTAINER is up, not that anything is actually claiming
// work". Progress means a document finished, or the backend says one is in flight for THIS scan.
//
// When neither holds, the honest report is that progress is not confirmed — not a diagnosis. The
// client cannot tell a slow first document from a wedged parser from a queue that has not been
// reached yet, and inventing a cause is how a screen ends up contradicting the truth.
export function progressIsConfirmed({ completed = 0, inFlight = 0 } = {}) {
  return completed > 0 || inFlight > 0
}


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

// "3s" under a minute, "1m 12s" past it — short enough to sit inline next to a status line
// without dominating it. Floors at 0 rather than going negative on a clock skew blip.
const fmtElapsed = (ms) => {
  const s = Math.max(0, Math.round(ms / 1000))
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`
}

const SKEY = (id) => `acp-assess-${id || 'none'}`
const loadSaved = (id) => { try { return JSON.parse(sessionStorage.getItem(SKEY(id)) || 'null') } catch { return null } }

export default function AssessRunner({ files = [], runId, scanBusy = false, onAssessed, onPhase,
                                       controlled = false, onReady, onViewMonitor, me = null }) {
  const saved = loadSaved(runId)
  // Derived from the selected scope, not a picker — see deriveLevel above.
  const level = DERIVED_LEVEL
  // Deva's Assess filter #6: ignore files a discovery rule flagged for archival or deletion. ON by
  // default — the run already skips them (PRD §4.5), and this surfaces that as a controllable choice
  // rather than a silent one. Unchecking sends the authorized include-flagged override to the run.
  const [ignoreLifecycle, setIgnoreLifecycle] = useState(true)
  const assessRef = useRef(null)                  // latest `assess`, for the optional external start
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
  // A deferred assess that opened NOTHING (0 scored of N) usually means the Drive sign-in expired
  // between Discover and Assess — surface a clear "sign in again" path instead of a silent 0%.
  const [accessFailed, setAccessFailed] = useState(false)
  // The scan itself is not loadable for this account (per-scan 404 — api.SCAN_UNAVAILABLE).
  // Distinct from accessFailed: there, the scan is ours and the DOCUMENTS wouldn't open; here
  // there is no scan to assess at all, so a conformance number over zero documents would be a
  // fabrication. Found live 2026-07-29 as "Assess produces no score": the catch below computed
  // a result from an empty `files` and rendered a completed 0/100.
  const [scanGone, setScanGone] = useState(null)
  // Real-time queue visibility for the deferred model (2026-08-22). Before this, "Opening &
  // assessing 0 of 148…" looked IDENTICAL whether a worker was about to pick the job up or the
  // worker tier was down entirely — the live incident this answers: a user watching a stuck 0%
  // with no way to tell "about to start" from "never going to start". POST /assess already
  // returned workers/worker_tier_alive/job_id; this is the first thing that reads them.
  const [workersDown, setWorkersDown] = useState(false)
  const [jobInfo, setJobInfo] = useState(null)          // {status, phase, locked_at} from GET /jobs/{id}
  const [assessStartedAt, setAssessStartedAt] = useState(null)
  const [nowTick, setNowTick] = useState(Date.now())     // re-renders the elapsed-time line every second
  useEffect(() => {
    if (phase !== 'running') return undefined
    const id = setInterval(() => setNowTick(Date.now()), 1000)
    return () => clearInterval(id)
  }, [phase])
  // Live worker strip — polled at 10s while running (lighter than QueuePanel's 2s; the
  // user needs "is it alive?" not sub-second accuracy here).
  const [workerSnap, setWorkerSnap] = useState(null)  // {workers, running, queued, alive, suggested}
  const [workerBusy, setWorkerBusy] = useState(false)
  const [workerMsg, setWorkerMsg] = useState(null)     // transient feedback after +/- click
  const workerMsgTimer = useRef(null)
  // Activity tracking: update on both completions and new assignments so "Last activity" is honest.
  const lastProgressRef = useRef(null)     // ms timestamp of last scored-count increase
  const lastProgressValRef = useRef(null)  // last known scored count, to detect movement
  const lastInFlightRef = useRef(null)     // ms timestamp of last inFlight-count increase
  const lastInFlightValRef = useRef(null)  // last known inFlight count
  useEffect(() => {
    if (phase !== 'running') return undefined
    // Shared subscription (jobsFeed.js) rather than a private timer — see its header for the
    // measured cost of five components each polling /jobs on their own.
    return subscribeJobs(null, (d) => {
      setWorkerSnap({ workers: d.workers ?? 0, running: d.stats?.running ?? 0,
                      queued: d.stats?.queued ?? 0, alive: !!d.worker_tier_alive,
                      // The heartbeat's AGE, not just its boolean. /jobs has carried both since
                      // system.py exposed worker_tier_status(); this file threw them away and
                      // rendered `alive` as a hard binary, which cannot express the third state
                      // (see deriveWorkerHealth). `age_s` is null when no worker has EVER beaten
                      // or when the stored timestamp is unparseable — both "we cannot say",
                      // which is different from "we know it is down".
                      heartbeatAgeS: typeof d.worker_heartbeat_age_s === 'number'
                        ? d.worker_heartbeat_age_s : null,
                      heartbeatAt: d.worker_heartbeat_at ?? null,
                      suggested: d.suggested_workers ?? 4,
                      runtime_mode: d.runtime_mode ?? 'auto' })
    }, { intervalMs: 10000 })
  }, [phase])
  // The "Estimated pickup" range (GET /scans/{id}/queue-estimate?kind=assess) — same 10s cadence
  // and running-only gate as workerSnap above, since it answers the same "is anything happening
  // yet" question. Omitted (stays null) until the backend has enough recent-completion history
  // for an honest range — processingState.js's deriveProcessingState reads that absence as
  // pickupUnavailable, same as before this existed, rather than showing a guess.
  const [pickupEstimate, setPickupEstimate] = useState(null)
  useEffect(() => {
    setPickupEstimate(null)
    if (phase !== 'running' || !runId) return undefined
    let on = true
    const load = () => getQueueEstimate(runId, 'assess').then((d) => { if (on) setPickupEstimate(d) }).catch(() => {})
    load()
    const id = setInterval(load, 10000)
    return () => { on = false; clearInterval(id) }
  }, [phase, runId])
  // Per-scan queue snapshot from GET /scans/{id}/live — accurate in-flight/waiting counts
  // for THIS scan only, unlike workerSnap which counts across all jobs system-wide.
  const [liveQueue, setLiveQueue] = useState(null)   // {inFlight, queued, workersBusy, workersMax}
  // RETIRED, NOT DELETED (2026-08-31). Nothing in this file calls adjustWorkers any more: the ±
  // concurrency buttons and the panel's "Start workers" button were the only two callers, and both
  // were ordinary-user affordances for an infrastructure decision. Kept per this repo's convention
  // — remove the mount, keep the code, and write down that it is retired — so restoring a control
  // is one line if that decision is reversed. `workerBusy`/`workerMsg` below belong to it and are
  // kept for the same reason. assessTopologyHealth.test.jsx asserts no such control renders, and
  // will fail if one is wired back in, which is the reminder to delete this note rather than a
  // regression. The AUTHORIZED path is unaffected: WorkerReplicaControl adjusts Azure warm
  // replicas and gates its buttons on `me?.is_admin`.
  const adjustWorkers = (delta) => {
    if (!workerSnap || workerBusy) return
    // First click from zero: jump straight to the server's suggested count rather than to 1.
    const next = (delta === 1 && workerSnap.workers === 0)
      ? (workerSnap.suggested ?? 4)
      : Math.max(0, Math.min(16, workerSnap.workers + delta))
    if (next === workerSnap.workers) return
    const diff = next - workerSnap.workers
    const count = Math.abs(diff)
    const noun = count === 1 ? 'worker' : 'workers'
    clearTimeout(workerMsgTimer.current)
    setWorkerMsg(diff > 0 ? `Starting ${count} ${noun}…` : `Stopping ${count} ${noun}…`)
    setWorkerBusy(true)
    setWorkerSnap((s) => ({ ...s, workers: next }))   // optimistic
    setWorkers(next)
      .then((d) => {
        const actual = d.workers ?? next
        setWorkerSnap((s) => ({ ...s, workers: actual }))
        setWorkerMsg(actual > 0 ? `${actual} ${actual === 1 ? 'worker' : 'workers'} active` : 'Workers stopped')
      })
      .catch(() => {
        setWorkerSnap((s) => ({ ...s, workers: workerSnap.workers }))
        setWorkerMsg('Failed to update — try again')
      })
      .finally(() => {
        setWorkerBusy(false)
        workerMsgTimer.current = setTimeout(() => setWorkerMsg(null), 3500)
      })
  }
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
  useEffect(() => () => {
    clearInterval(timer.current); clearTimeout(phaseTimer.current); clearTimeout(workerMsgTimer.current)
  }, [])
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
  //
  // `jobId` (2026-08-22) additionally polls GET /jobs/{id} — but ONLY while nothing has scored
  // yet. Once real per-file progress is flowing, "queued vs a worker claimed it Ns ago" is a
  // question that's already been answered by the fact of progress existing; polling the job row
  // past that point is a request that tells the user nothing the file list doesn't already say.
  const pollDeferred = (startedAt, jobId) => {
    clearInterval(timer.current)
    setAssessStartedAt(startedAt)
    const tick = () => {
      // Per-scan queue accuracy: /live returns THIS scan's in_flight/queued counts, not
      // system-wide totals. Best-effort — a blip must not break the main poll.
      getScanLive(runId).then((d) => {
        const q = d?.queue
        if (q) {
          const lq = { inFlight: q.in_flight ?? 0, queued: q.queued ?? 0,
                       workersBusy: q.workers?.busy ?? 0, workersMax: q.workers?.max ?? 0 }
          if (lq.inFlight > (lastInFlightValRef.current ?? -1)) {
            lastInFlightRef.current = Date.now()
            lastInFlightValRef.current = lq.inFlight
          }
          setLiveQueue(lq)
        }
      }).catch(() => {})
      getScan(runId).then((data) => {
        const run = data?.run || {}
        const fs = data?.files || []
        const scored = fs.filter((f) => f.score != null)
        const total = run.files || fs.length || 1
        if (scored.length > (lastProgressValRef.current ?? -1)) {
          lastProgressRef.current = Date.now()
          lastProgressValRef.current = scored.length
        }
        setProgress(Math.min(scored.length, total))
        setCurrentPhase(`Opening & assessing ${scored.length} of ${total}…`)
        if (scored.length === 0 && jobId) {
          getQueueJob(jobId)
            .then((j) => setJobInfo(j))
            // A 404/network blip on the job-status side-channel must not blank out what's
            // already showing — keep the last known status rather than flashing to nothing.
            .catch(() => {})
        } else if (scored.length > 0 && jobInfo) {
          setJobInfo(null)   // real progress answers the question; stop showing the queue guess
        }
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
        // The first file WITHOUT A RESULT YET — deliberately not "the one in flight", which is
        // what this used to claim and could not know. There is no per-file execution signal to
        // read: file_records rows are INSERTed when a file FINISHES, so an unfinished file simply
        // has no record and getScan surfaces it from scan_inventory as 'discovered'. `score ==
        // null` means "no result yet", not "a worker has this open".
        //
        // Assessment is also CONCURRENT — production runs a 12-slot pool (readyz: pool_size: 12)
        // — so roughly twelve documents are in flight at once and picking the first is arbitrary
        // even when it happens to be right. The list order is the query's, not the worker's.
        //
        // The name is still worth showing: it tells a user where a long run has reached, which is
        // why it was added. What changed is the CLAIM the UI makes about it — see the label at
        // the render site.
        setCurrentFile(nameOf(fs.find((x) => x.score == null)))
        if (run.assessed_at || run.finalized_at) {
          clearInterval(timer.current)
          const computed = computeResultFrom(scored, level)
          setProgress(scored.length); setCurrentFile(null); setCurrentPhase('')
          // Opened nothing → almost always an expired Drive sign-in in the deferred model.
          const accessFail = scored.length === 0 && total > 0
          setAccessFailed(accessFail)
          setResult(computed); setPhase('done')
          // Persist BEFORE announcing. The announcement makes App refetch the scan, which changes
          // `files` → `docs.length` → the resume effect below re-reads sessionStorage; if that
          // still said 'running' the effect would start a SECOND poller over a finished run.
          save({ phase: 'done', level, result: computed })
          if (!accessFail) onAssessed?.()          // don't announce a false 0% result
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

  // `opts` is AssessSetup's onRun descriptor when the pre-run screen drives the run, and null
  // when this component's own button does. Null means "use my local state", which is what every
  // existing caller gets.
  const assess = (opts) => {
    if (phase === 'running') return               // never launch a second pass while one runs
    if (scanBusy) return                          // a scan must finish before assessing its results
    if (!runId) return
    clearInterval(timer.current); clearTimeout(phaseTimer.current)
    const startedAt = Date.now()
    setPhase('running'); setResult(null); setProgress(0); setAccessFailed(false); setScanGone(null)
    setWorkersDown(false); setJobInfo(null); setLiveQueue(null)
    // ADR 0020: in the deferred model the DOWNLOAD happens now, at Assess — but GIS Drive tokens
    // live ~1h and are held in-memory per scan, so a scan discovered a while ago (or after a
    // container restart) has a stale/absent token and every file would 401. Push a fresh Drive
    // token from the live session first (best-effort; the endpoint 422s harmlessly for a local /
    // SharePoint scan with no token). Then kick off the assessment.
    Promise.resolve(refreshScanDriveToken(runId)).catch(() => {}).then(() => assessScan(runId, opts?.level || level, opts ? !!opts.includeLifecycleFlagged : !ignoreLifecycle)).then((resp) => {
      if (resp && resp.deferred) {
        // Same "no workers available" guard doScan (App.jsx) already applies to a fresh scan
        // start — a queue with nobody to drain it is worth saying plainly rather than leaving
        // the user to infer it from a bar that never moves.
        if (!resp.workers && !resp.worker_tier_alive) setWorkersDown(true)
        // The analysis is running now — track it for real.
        save({ phase: 'running', startedAt, level, deferred: true, jobId: resp.job_id })
        pollDeferred(startedAt, resp.job_id)
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
      if (saved.deferred) { pollDeferred(saved.startedAt || Date.now(), saved.jobId); return }
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

  // ONE denominator, the same one `progress` is measured against. `progress` is
  // `Math.min(scored.length, run.files)` — a SERVER-scale numerator — while `assessN` and
  // `docs.length` come from the `files` PROP, so dividing by those divided two unrelated scales.
  // Math.max did not reconcile them; it just picked the larger client number.
  //
  // On the deferred path (ADR 0020) the prop legitimately lags the server — Assess is running
  // precisely BECAUSE the files have no scores yet — so this was the normal case, not an edge
  // one. With 148 documents server-side and 12 scored, the bar rendered 60% beside a caption
  // reading "12 of 148", which is 8%.
  //
  // `liveTotal` is that server count, and its own declaration already calls it "the REAL total,
  // not docs.length". The caption, the "Computing conformance · N documents" line and the
  // no-workers banner all read it; the percentage was the one consumer that did not. The
  // fallbacks keep the immediate (non-deferred) path and the first render — before any poll has
  // landed — working exactly as before.
  const pct = phase === 'running'
    ? Math.round((progress / Math.max(1, liveTotal || assessN || docs.length)) * 100) : 0

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

  // Through a ref, not by handing `assess` to the effect directly: `assess` closes over `phase`,
  // `ignoreLifecycle` and `level`, so a function captured once would keep starting runs from the
  // state of the render that registered it. The ref is reassigned every render, so the parent
  // always invokes the current one.
  assessRef.current = assess
  useEffect(() => {
    if (!onReady) return undefined
    onReady((opts) => assessRef.current?.(opts))
    return () => onReady(null)
  }, [onReady])

  return (
    <section className="panel assesspanel">
      {/* The pre-run band — heading, document count, exclusions, target-level sentence, lifecycle
          toggle and the Run button. `controlled` hides ALL of it, because AssessSetup renders its
          own version of every one of those and two of them on one screen is the defect this
          redesign removes. Progress and results below are unaffected either way. */}
      {!controlled && (<>
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
        <button className="assessbtn" onClick={() => assess()} disabled={phase === 'running' || !assessN || scanBusy}
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
        Scored against <b>WCAG 2.1 Level {level}</b>, derived
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
      </>)}

      <div role="status" aria-live="polite">
        {phase === 'running' && (
          <div className="assessrun">
            {/* PRD "Processing details" (Phase 1 slice, 2026-08-28) — leads the running view with
                ONE plain-language sentence before the granular strip below, per the PRD's own
                principle: "explain status before showing metrics". Reuses the exact same signals
                the strip and the two banners below already compute (noCapacity/stalled match
                those banners' own conditions) rather than deriving a second, possibly-diverging
                notion of the same thing. */}
            {(() => {
              // Gated on TOPOLOGY, exactly like the banner below — these must agree, and the
              // comment above says they do. Before this they did not: #1060 changed the banner
              // and left this reading `!(distributed && alive)`, so one stale heartbeat made
              // `noCapacity` true and the panel announced "no worker is currently online to
              // process them" — the same claim the banner had just been fixed to withhold,
              // rendered ABOVE it, with a "Start workers" button attached.
              const processingCount = liveQueue ? liveQueue.workersBusy : 0
              const noCapacity = !!(workerSnap && workerSnap.workers === 0 && !workersDown
                && workerSnap.runtime_mode !== 'distributed'
                && !progressIsConfirmed({ completed: progress, inFlight: processingCount }))
              const stalled = !!(workerSnap && workerSnap.workers > 0 && assessStartedAt && (() => {
                const lastActivityMs = Math.max(lastProgressRef.current ?? 0, lastInFlightRef.current ?? 0) || assessStartedAt
                return lastActivityMs < nowTick - 5 * 60 * 1000
              })())
              const waitingCount = liveQueue ? liveQueue.queued : Math.max(0, assessN - progress - processingCount)
              const lastActivityMs = Math.max(lastProgressRef.current ?? 0, lastInFlightRef.current ?? 0) || null
              const lastActivityMins = lastActivityMs ? Math.round((nowTick - lastActivityMs) / 60000) : null
              const derived = deriveProcessingState({
                phase, noCapacity, stalled, completedCount: progress, totalCount: assessN,
                processingCount, waitingCount, lastActivityMins, currentFile, currentPhase,
                pickupEstimate,
              })
              // No `onStartWorkers`. The panel renders its "Start workers" button only when the
              // caller supplies the handler, so withholding it removes the affordance without
              // touching the panel — which still serves Settings, where an operator may keep one.
              return (
                <ProcessingStatusPanel derived={derived} onViewMonitor={onViewMonitor} />
              )
            })()}
            {workersDown && !progressIsConfirmed({ completed: progress, inFlight: liveQueue?.workersBusy }) && (
              <div role="alert" style={{ margin: '0 0 10px', padding: '10px 14px', borderRadius: 8,
                   fontSize: 13, background: '#FBE9E7', border: '1px solid #E7B4AC', color: '#8A2A20' }}>
                ⛔ <b>Assessment cannot continue.</b> No worker capacity was available when this run
                started — the queue is unmanned and documents will not be processed. Use the worker
                concurrency control below to start local workers, or check your deployment's
                worker tier.
              </div>
            )}
            <div className="assessbar">
              <i style={{ width: `${pct}%` }} />
            </div>
            <div className="assessrunmeta">
              <span className="muted"><b style={{ color: '#1F5FA8' }}>Computing conformance</b> · {(liveTotal || docs.length).toLocaleString()} documents at WCAG 2.1 {level}</span>
              <span className="assesspct">{pct}%</span>
            </div>
            {/* Real queue status, not a guess — GET /jobs/{id}, polled only while nothing has
                scored yet (see pollDeferred). Distinguishes "about to start" from "genuinely
                stuck" instead of leaving both read as an identical, silent 0%. */}
            {jobInfo && !workersDown
              && (isTerminalJob(jobInfo.status) || !progressIsConfirmed({ inFlight: liveQueue?.workersBusy })) && (
              <div style={{ fontSize: 13, margin: '4px 0 0', display: 'flex', alignItems: 'center', gap: 6 }}>
                {jobInfo.status === 'queued'
                  ? <><span style={{ background: '#FAEEDA', color: '#854F0B', fontWeight: 600,
                                     padding: '2px 8px', borderRadius: 4, whiteSpace: 'nowrap' }}>
                        ⏳ Queued
                      </span>
                      <span className="muted">— waiting for a worker to pick this up
                        {assessStartedAt && <> · {fmtElapsed(nowTick - assessStartedAt)}</>}
                      </span></>
                  : jobInfo.status === 'dead'
                    /* "failed repeatedly" is kept verbatim: assessQueueStatus.test.jsx asserts on
                       it, and rewording it away would have meant loosening someone else's test to
                       accommodate this change. The new clause is added alongside it. */
                    ? <span style={{ color: '#8A2A20', fontWeight: 600 }}>
                        ⚠ This run failed repeatedly — <b>automatic retries have stopped</b> and it
                        will not resume on its own. Re-run it once the cause is addressed.
                        {jobInfo.error && <> — {jobInfo.error}</>}</span>
                    : jobInfo.status === 'cancelled'
                      /* Previously fell through to the `Running · 4m` branch below, so a run that
                         had been stopped or superseded went on reporting elapsed time as though a
                         worker were still on it. */
                      ? <span style={{ color: '#8A2A20', fontWeight: 600 }}>
                          ⏹ This run was stopped — <b>automatic retries have stopped</b> and it
                          will not resume on its own.</span>
                    : jobInfo.status === 'running'
                      ? <span className="muted">🔧 A worker is on this now{jobInfo.phase && <> · {jobInfo.phase}</>}
                          {jobInfo.locked_at && <> · claimed {fmtElapsed(Date.now() - new Date(jobInfo.locked_at).getTime())} ago</>}</span>
                      : assessStartedAt && <span className="muted">Running · {fmtElapsed(nowTick - assessStartedAt)}</span>}
              </div>
            )}
            {/* Zero-workers warning — LOCAL POOL ONLY, and gated on TOPOLOGY, not health.
                `workerSnap.workers` is this API container's own in-process pool, which in the
                split topology (#113) is 0 BY DESIGN — production's readyz reports
                `pool_size: 12, local_pool: 0`. So that half of the test is permanently true in
                every real deployment, and the banner used to be held back by nothing but
                `alive`.
                Pairing it with `runtime_mode === 'distributed' && alive` conflated TOPOLOGY (is
                there a separate worker tier?) with HEALTH (is it heartbeating this instant?) —
                the same defect fixed in Discover.jsx and QueuePanel.jsx. One stale heartbeat poll
                flipped `alive`, lifted the suppression, and rendered "nothing is processing them"
                directly beneath the line reporting the job claimed by a worker that was in fact
                running it. Reproduced in assessStatusContradiction.test.jsx.
                A distributed tier's health is not this banner's subject: when one exists, the
                local pool being 0 says nothing about whether work is progressing, so the banner
                simply does not apply. */}
            {workerSnap && workerSnap.workers === 0 && !workersDown
              && workerSnap.runtime_mode !== 'distributed'
              && !progressIsConfirmed({ completed: progress, inFlight: liveQueue?.workersBusy }) && (
              <div role="alert" style={{ margin: '8px 0', padding: '10px 14px', borderRadius: 8,
                   fontSize: 13, background: '#FBE9E7', border: '1px solid #E7B4AC', color: '#8A2A20',
                   display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
                <span>⛔ <b>No local workers active</b> — {(liveTotal || docs.length).toLocaleString()} documents are queued but nothing is processing them.</span>
                {/* The inline "Start N workers" button is deliberately gone. Choosing worker
                    concurrency is an infrastructure decision, and the worker-provisioning PRD is
                    explicit that no ordinary-user surface should expose one. The remedy is not
                    removed, only moved to where an operator already manages it — adjustWorkers()
                    and setWorkers stay in this file for Settings' own control, so restoring this
                    button is one line if that decision is reversed. */}
                <span className="muted" style={{ fontSize: 12 }}>
                  Worker capacity is managed in Settings → Worker Configuration.
                </span>
              </div>
            )}
            {workerSnap && workerSnap.workers > 0 && assessStartedAt && (() => {
              const lastActivityMs = Math.max(lastProgressRef.current ?? 0, lastInFlightRef.current ?? 0) || assessStartedAt
              return lastActivityMs < nowTick - 5 * 60 * 1000
            })() && (
              <div role="alert" style={{ margin: '8px 0', padding: '10px 14px', borderRadius: 8,
                   fontSize: 13, background: '#FAEEDA', border: '1px solid #D4A017', color: '#7A5800' }}>
                ⚠ <b>Assessment may be stalled</b> — {assessN - progress} document{assessN - progress === 1 ? '' : 's'} remain,
                but no worker has started or completed a document in the last 5 minutes.
                Check that the worker service is reachable and that documents are not repeatedly failing.
              </div>
            )}
            {workerSnap && (() => {
              // TOPOLOGY, not health. Whether a separate worker tier exists does not stop being
              // true because one heartbeat poll came back late — and this value decided whether
              // an ordinary user saw the ± concurrency buttons, so a stale beat handed out
              // infrastructure controls in a deployment where those controls adjust a pool
              // (the API container's own) that is 0 by design and does no work.
              const externallyManaged = workerSnap.runtime_mode === 'distributed'
              const processingCount = liveQueue ? liveQueue.workersBusy : 0
              const health = processingCount > 0
                ? { state: 'active', label: 'active for this run', tone: 'ok' }
                : deriveWorkerHealth(workerSnap)
              // TERMINAL STATE OUTRANKS SERVICE HEALTH. A dead or cancelled job does not become
              // less dead because the tier is answering, so a green "online" light must not sit
              // beside it as though it were reassurance about this run. When the job is terminal
              // the light drops to neutral and says what it is actually about.
              const jobTerminal = isTerminalJob(jobInfo?.status)
              // NO "assigned next" COUNT. It was `inFlight - workersBusy`, and the backend sets
              // `workers.busy = in_flight` by construction (live_queue.compose), so that subtraction
              // is always exactly 0 — a category that could never appear, taking up room in a strip
              // whose whole job is to say where the work is. The distinction it was reaching for
              // (claimed-by-a-worker vs actively-being-assessed) is real, but nothing scan-scoped
              // reports it: `workerSnap.running` is the jobs table system-wide, across every scan
              // and every user, so subtracting a per-scan number from it would produce a figure
              // belonging to neither. Rather than invent one, the strip reports the two counts that
              // ARE measured. Restoring this needs a per-scan claimed count from the backend first.
              const brokerQueued = liveQueue ? liveQueue.queued : Math.max(0, assessN - progress - processingCount)
              const workerCount = liveQueue?.workersMax || workerSnap.workers
              const lastActivityMs = Math.max(lastProgressRef.current ?? 0, lastInFlightRef.current ?? 0) || null
              const lastActivityMins = lastActivityMs ? Math.round((nowTick - lastActivityMs) / 60000) : null
              return (
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, margin: '6px 0 2px',
                            fontSize: 12.5, flexWrap: 'wrap' }}>
                <span className="assesshealth"
                      style={{ color: jobTerminal ? HEALTH_TONE.unknown : HEALTH_TONE[health.tone],
                               fontWeight: 600 }}
                      title={'Whether the worker service is answering. Not a statement about this '
                             + "run's progress — a worker that restarts repeatedly answers between "
                             + 'restarts.'}>
                  ● Worker service&nbsp;
                  <span style={{ fontWeight: 400 }}>{health.label}</span>
                  {jobTerminal && <span style={{ fontWeight: 400 }}> — but this run has stopped</span>}
                </span>
                <span className="muted">·</span>
                <span className="muted">
                  {progress} of {assessN} completed
                  {processingCount > 0 && <> · {processingCount} processing</>}
                  {brokerQueued > 0 && <> · {brokerQueued} waiting</>}
                  {/* Says nothing about a CAUSE. The client cannot tell a slow first document
                      from a wedged parser from a queue not yet reached, and a guess here is how
                      this screen ends up contradicting the job's own status. */}
                  {!jobTerminal && !progressIsConfirmed({ completed: progress, inFlight: processingCount })
                    && <> · <span className="assessunconfirmed">progress not confirmed</span></>}
                </span>
                {lastActivityMins !== null && lastActivityMins >= 1 && (
                  <><span className="muted">·</span>
                  <span className="muted">{workerCount} worker{workerCount === 1 ? '' : 's'} · Last activity {lastActivityMins} min ago</span></>
                )}
                {/* The ± worker-concurrency buttons are deliberately gone from this view. They
                    called setWorkers() with NO admin check at all — unlike WorkerReplicaControl
                    mounted three lines below, which shows its count to everyone and its buttons
                    only when `me?.is_admin`, the same value the backend's _require_admin reads.
                    The right pattern was already in this file, next to the wrong one.
                    Choosing worker concurrency is an infrastructure decision and the
                    worker-provisioning PRD is explicit that no ordinary-user surface should
                    expose one. Both branches now say where capacity is actually managed, which
                    differs by topology: a separate tier is the deployment's, a local pool is
                    Settings'. Nothing is deleted — adjustWorkers()/setWorkers stay in this file
                    (see their retirement note) so restoring a control is one line, and the
                    authorized path (WorkerReplicaControl) is untouched. */}
                <span className="muted" style={{ marginLeft: 4, fontStyle: 'italic' }}>
                  {externallyManaged
                    ? 'Worker capacity is managed by your deployment administrator.'
                    : 'Worker capacity is managed in Settings → Worker Configuration.'}
                </span>
                <WorkerReplicaControl leadingSeparator me={me} />
              </div>
            )
          })()}
            {(currentFile || currentPhase) && (
              <div className="assessfile">
                {/* Say what this name IS. Rendered bare inside a running card, beside "Opening &
                    assessing N of M…", a filename reads as "this is the document we are working
                    on now" — a claim nothing here can support (see the setCurrentFile comment).
                    Labelling it as the first document still awaiting a result says exactly what
                    `score == null` does support, and keeps the information that made it worth
                    showing. */}
                {currentFile && <span className="assessfilelabel muted">Awaiting result:</span>}
                {currentFile && <span className="assessfname" title={`${currentFile} — the first document with no result yet. Assessment runs several documents at once, so this is not necessarily the one being opened at this instant.`}>{currentFile}</span>}
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
                        : <span className="muted alscs">{f.status === 'analysed' ? 'Processing now' : 'Waiting'}</span>}
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
              <button className="ghost small" onClick={() => assess()} disabled={phase === 'running' || scanBusy}>↻ Re-run Assess</button>
            </div>
          </div>
        )}
      </div>
    </section>
  )
}
