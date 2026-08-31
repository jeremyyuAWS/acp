import { useEffect, useState, useRef } from 'react'
import { getJobs, setWorkers, clearDeadJobs, getWorkerReplicas } from './api.js'
import { subscribeJobs } from './jobsFeed.js'
import { deriveFeedState, hasConfirmedData, needsFreshnessLabel, ageLabel, statusLine, topologyIsKnown } from './queueFreshness.js'
import { TraceChip } from './Transparency.jsx'
import { phaseLine, isStalled, STALLED_AFTER_S } from './jobPhase.js'
import { diagnoseWorkerHealth } from './workerDiagnosis.js'
import { useWorkerCapacity } from './workerCapacityStore.js'
import UtilizationBar from './UtilizationBar.jsx'

// Job-type → short human label for the recent-jobs cards.
const JOBLABEL = {
  scan_discover: 'discover', scan_file: 'scan file', scan_batch: 'scan batch',
  scan_finalize: 'finalize', remediate_file: 'remediate', assess_trace: 'assess', scan: 'scan',
}
const fmtDur = (s) => (s == null ? '' : s < 1 ? '<1s' : s < 60 ? `${Math.round(s)}s` : `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`)
const jobFile = (payload) => { try { return JSON.parse(payload || '{}').file || null } catch { return null } }

// Source code → friendly name for job descriptions.
const SRC_NAME = {
  drive: 'Google Drive', gdrive: 'Google Drive', sharepoint: 'SharePoint', box: 'Box',
  confluence: 'Confluence', cms: 'CMS', s3: 'S3', onedrive: 'OneDrive', upload: 'Upload',
}
// Human, informative label for a recent-job card — says what the worker is actually doing
// rather than an opaque scan id. Per-file jobs name the document; scan-level jobs (which
// have no single file) describe the phase and its source/scope from the job payload.
const jobDesc = (jb) => {
  let p = {}
  try { p = JSON.parse(jb.payload || '{}') } catch { /* opaque payload — fall through */ }
  const src = SRC_NAME[p.source] || p.source
  switch (jb.type) {
    case 'scan_file':
    case 'remediate_file':
      return p.file || 'a document'
    case 'scan_discover':
      return src ? `Finding documents · ${src}` : 'Finding documents to scan'
    case 'scan_batch': {
      const n = Array.isArray(p.items) ? p.items.length : null
      return n ? `Scanning ${n} document${n !== 1 ? 's' : ''}` : 'Scanning a batch'
    }
    case 'scan_finalize':
      return 'Scoring & finalizing results'
    case 'assess_trace':
      return `Assessing coverage · WCAG ${p.level || 'AA'}`
    case 'scan':
      return src ? `Scanning · ${src}` : 'Scanning documents'
    default:
      return p.file || (jb.scan_id ? `scan ${String(jb.scan_id).slice(0, 8)}` : String(jb.id).slice(0, 8))
  }
}

// Live view of the durable async job queue (ADR 0004). Polls /jobs and shows
// queue depth by status. The same data Grafana's queue panel renders.
const WBTN = {
  width: 26, height: 26, borderRadius: 7, border: '1px solid var(--line)',
  background: '#fff', color: 'var(--ink)', fontSize: 17, lineHeight: 1,
  cursor: 'pointer', display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
}
const STATUS = {
  queued:  ['#854F0B', '#FAEEDA', 'queued'],
  running: ['#185FA5', '#E7F0FB', 'running'],
  done:    ['#3B6D11', '#E7F0DC', 'done'],
  failed:  ['#A32D2D', '#FCEBEB', 'failed'],
  dead:    ['#A32D2D', '#FCEBEB', 'dead-letter'],
}
// The deterministic WCAG fixes the server-side remediator applies (alt text, contrast,
// title, language, reading order). Cycled next to the title while a file is in flight to
// show the remediation is active — client-paced (a one-shot job streams no per-rule step),
// the same representative animation the FileDrawer progress line uses.

// focusScanId/onClearFocus: "View in Monitor →" from Discover/Assess (2026-08-30) lands here
// wanting the originating scan's own job(s) surfaced, not a filtered queue — this codebase's
// "never hide data, only surface it" convention (see CLAUDE.md's retired-features section) rules
// out dropping every other job from the list, so this only highlights + banners, never filters.
export default function QueuePanel({ focusScanId = null, onClearFocus = null }) {
  const [q, setQ] = useState(null)
  // jobsFeed hands every callback `{ fetchedAt, ageMs, stale }`. This panel used to discard it
  // and derive everything from `q` alone with `?? 0` fallbacks — so before the first response it
  // rendered "queue empty" and a bold "0 workers", two factual claims no successful read had
  // established. See queueFreshness.js for the four states that replaces.
  const [meta, setMeta] = useState(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState('')
  // Throughput meter: a rolling window of {t, done} samples from each poll -- no backend
  // change needed, "done" is already the cumulative completed-jobs counter getJobs()
  // returns. Rate = delta(done) / delta(t) over the oldest-vs-newest sample in the window.
  const historyRef = useRef([])
  const [throughput, setThroughput] = useState(null)   // jobs/min, or null until 2+ samples

  useEffect(() => {
    // Shared subscription (jobsFeed.js) — QueuePanel, Discover, AssessRunner, FailureLane and
    // FixOutcomes all want this same unfiltered response, and each private timer cost another
    // 5 connection-pool acquisitions per tick.
    const onData = (d, m) => {
      setQ(d); setErr(''); setMeta(m || null)
      const now = Date.now()
      const done = d?.stats?.done ?? 0
      const hist = [...historyRef.current, { t: now, done }].filter((s) => now - s.t <= 5 * 60 * 1000)
      historyRef.current = hist
      if (hist.length >= 2) {
        const first = hist[0]
        const elapsedMin = (now - first.t) / 60000
        setThroughput(elapsedMin > 0 ? Math.max(0, (done - first.done) / elapsedMin) : null)
      }
    }
    // 2s so the worker queue animates in near-real-time (running → done ticks, throughput,
    // recent-job list) while a batch is churning. The feed polls at the SHORTEST interval any
    // subscriber asks for, so this stays 2s here while Discover's 10s worker strip rides the
    // same request rather than adding a second one.
    return subscribeJobs(null, onData, {
      intervalMs: 2000,
      // The cached counts stay on screen, labelled with their age, rather than being blanked
      // or — worse — falling back to zeros that read as fact. meta carries the age of whatever
      // is still cached, which is exactly what makes "last known 4m ago" possible.
      onError: (e, m) => { setErr(e.message || 'unavailable'); setMeta(m || null) },
    })
  }, [])

  // Azure Container App replica config + capacity evidence — the SAME /control/workers/replicas
  // and /control/workers/capacity signals Discover.jsx's WorkerAvailability strip already shows
  // for a single active scan, surfaced here too because Monitor is meant to be the estate-wide
  // operational view and previously had NO Azure visibility at all (only the in-process pool
  // above, via getJobs/setWorkers). `q.runtime_mode`/`q.worker_tier_alive` come from the SAME
  // /jobs payload this panel already polls — no extra fetch needed to detect the mode.
  //
  // Deliberately READ-ONLY here, both endpoints being open reads (not admin-gated) notwithstanding
  // — monitorWorkersQueue.test.jsx already pins Monitor's own copy as "points to Settings for
  // capacity changes rather than duplicating the control here", and Settings' Worker Configuration
  // tab (WorkerReplicaControl.jsx) is where that decision lives. Adding a second +/- here would
  // silently reopen a question the codebase already answered — this only adds visibility.
  // TOPOLOGY, not health — see the same split in Discover.jsx. `&& worker_tier_alive` meant the
  // estate-wide Azure evidence below vanished the moment the worker tier stopped heartbeating,
  // which is when an operator most needs to see whether replicas exist at all, how many are
  // draining, and which revision is serving. The replica/capacity block this gates is read-only
  // and permission-checked server-side, so it is safe to show while the tier is down — and far
  // more useful then than while everything is healthy.
  const externallyManaged = q?.runtime_mode === 'distributed'
  const [replicas, setReplicas] = useState(null)
  useEffect(() => {
    if (!externallyManaged) return undefined
    let live = true
    getWorkerReplicas().then((d) => { if (live) setReplicas(d) }).catch(() => {})
    return () => { live = false }
  }, [externallyManaged])
  // Shared with Discover.jsx's own capacity strip via workerCapacityStore.js — a single 30s
  // poller reference-counted across every mounted consumer, rather than each maintaining its own
  // independent setInterval and doubling the Azure Monitor API calls whenever both are mounted.
  const capacity = useWorkerCapacity(externallyManaged)

  // Diagnosis layer (workerDiagnosis.js): Monitor is the estate-wide operational view — the one
  // place someone actually goes to ask "why", not just "what" — but until now had no interpretive
  // text at all, not even a queue-stall check. Runs in every runtime mode, not just distributed:
  // the offline/heartbeat-aging/queue-stall rules apply to the in-process worker pool too.
  const diagnosis = q ? diagnoseWorkerHealth({
    snap: { workers: q.workers, alive: q.worker_tier_alive, runtime_mode: q.runtime_mode,
            oldestQueuedCreatedAt: q.oldest_queued?.created_at ?? null,
            workerHeartbeatAgeS: q.worker_heartbeat_age_s ?? null },
    capacity, replicas,
  }) : null

  // The file a worker is remediating right now (most recent running remediate job).
  const remJob = (q?.jobs || []).find((j) => j.status === 'running' && j.type === 'remediate_file')
  const remFile = remJob ? jobFile(remJob.payload) : null
  const scaleWorkers = (next) => {
    const cur = q?.workers ?? 0
    const n = Math.max(0, Math.min(16, next))
    if (n === cur) return
    setBusy(true); setErr('')
    setNote(n > cur ? '⏳ initializing a worker…' : '⏳ retiring a worker (finishes its current job)…')
    setQ((c) => ({ ...(c || {}), workers: n }))   // optimistic
    setWorkers(n)
      .then((d) => {
        setQ((c) => ({ ...(c || {}), workers: d.workers }))
        setNote(n > cur ? '✓ worker ready' : '✓ worker retired')
      })
      .catch((e) => {
        // Roll the optimistic count back so the UI never claims a pool size the
        // server rejected (the 4s poll would fix it anyway — this fixes it NOW).
        setQ((c) => ({ ...(c || {}), workers: cur }))
        setErr(e.message || 'could not change workers'); setNote('')
      })
      .finally(() => { setBusy(false); setTimeout(() => setNote(''), 2500) })
  }

  const clearDead = () => {
    setBusy(true); setErr(''); setNote('⏳ clearing dead-letters…')
    clearDeadJobs()
      .then((d) => { setNote(`✓ cleared ${d.purged ?? 0} dead-letter job(s)`); return getJobs().then(setQ) })
      .catch((e) => setErr(e.message || 'could not clear dead-letters'))
      .finally(() => { setBusy(false); setTimeout(() => setNote(''), 2500) })
  }

  const stats = q?.stats || {}
  const feedState = deriveFeedState({ data: q, meta, error: err || null })
  const confirmed = hasConfirmedData(feedState)
  // `?? 0` is what turned "we have not read the queue" into "there are zero workers". null now
  // means unknown, and every consumer below has to decide what to do about that rather than
  // being handed a number that looks measured.
  const workers = q?.workers ?? null
  const workerCount = workers ?? 0
  const total = Object.values(stats).reduce((a, b) => a + b, 0)
  // Distinct scans & documents behind those jobs — so the count reads as "2 scans · 1
  // file · 8 jobs" instead of implying 8 documents. Each scan fans out into several
  // durable jobs (discover → one per file → finalize → assess), which is why jobs > files.
  // Derived from the visible job list (capped at 100 by /jobs); only shown when that list
  // covers every job (jobs.length >= total), so we never under-report on a huge estate.
  const jobList = q?.jobs || []
  const fullList = total > 0 && jobList.length >= total
  const scanCount = new Set(jobList.map((j) => j.scan_id).filter(Boolean)).size
  const fileCount = (() => {
    const seen = new Set()
    for (const j of jobList) {
      let p = {}
      try { p = JSON.parse(j.payload || '{}') } catch { /* opaque payload */ }
      if (p.file) seen.add(p.file)
      if (Array.isArray(p.items)) for (const it of p.items) if (it?.file) seen.add(it.file)
    }
    return seen.size
  })()
  // A job reaches 'dead' two ways that mean opposite things to whoever is reading this panel:
  // it exhausted its retries (a fault), or someone pressed Stop and a newer run superseded it
  // (a decision — _end_running_scan marks every outstanding job of the scan 'dead'). The status
  // alone cannot tell those apart, so `stats.dead` counted both and this panel called all of
  // them "failed permanently": stopping a 200-document scan raised a red banner announcing 200
  // permanent failures, and offered "See server logs for details" about a button press.
  //
  // dead_letters splits them server-side now (store.dead_letter_breakdown reads
  // cancel_requested_at alongside the status), so read those numbers instead of the raw status
  // count. When the split is absent — an older API behind a newer bundle, which the app's
  // blue-green cutover can produce for a few seconds — fall back to the unsplit count. That is
  // exactly what this panel did before the split, and quietly under-reporting a real failure is
  // the worse of the two mistakes.
  const split = q?.dead_letters?.failed
  const failedCount = split ? (split.n || 0) : (stats.dead || 0)
  const stoppedCount = q?.dead_letters?.stopped?.n || 0
  const order = ['queued', 'running', 'done', 'failed', 'dead']
  const counts = { ...stats, dead: failedCount }
  const shown = order.filter((s) => counts[s])
  const deadReason = q?.dead_letters?.top_errors?.[0]?.error
  // Real-time worker state: each 'running' job occupies one worker, so active ≈ running.
  const running = stats.running || 0
  const queued = stats.queued || 0
  const active = Math.min(running, workerCount)
  const idle = Math.max(0, workerCount - active)
  const initializing = note.includes('initializing')
  // The in-process pool is legitimately, permanently 0 whenever a dedicated worker tier is
  // doing the real work (split topology, #113) — that is the SAME condition the "✓ worker
  // service online" paragraph below already gates on. A bold "0" sized like every other stat
  // on this row reads as "no capacity" regardless of that paragraph, because font-weight beats
  // prose. Found live 2026-08-30: a real deployment showed "worker service online" directly
  // above a 22px-bold "0", and it read as a contradiction rather than as "this number doesn't
  // mean what it looks like it means". Collapsing it behind a disclosure only in THIS case —
  // never when the pool is the genuine capacity control (workers > 0, or no tier heartbeat at
  // all) — keeps the control reachable without it dominating the healthy, common case.
  const poolDecorative = !!(q && workerCount === 0 && q.worker_tier_alive)
  // Worker controls require BOTH a confirmed read and a known topology. Offering +/- against an
  // unread queue puts a control in front of someone for a number nothing has measured; offering
  // it when runtime_mode is absent asks them to scale a pool that may not be the thing actually
  // running their work (the split topology of #113). Unknown is not zero.
  const showPoolControls = confirmed && topologyIsKnown(q)
  const poolBlock = (
    <>
      <span style={{ display: 'flex', flexDirection: 'column', lineHeight: 1.1 }}>
        <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <button onClick={() => scaleWorkers(workerCount - 1)}
                  disabled={busy || workerCount <= 0} aria-label="Remove a worker"
                  title={workerCount <= 0 ? 'Already at 0 — nothing to remove' : 'Remove a worker'}
                  style={WBTN}>−</button>
          <span style={{ fontSize: 22, fontWeight: 700, minWidth: 22, textAlign: 'center' }}>{workerCount}</span>
          <button onClick={() => scaleWorkers(workerCount + 1)}
                  disabled={busy || workerCount >= 16} aria-label="Add a worker"
                  title={workerCount >= 16 ? 'Pool cap is 16 workers' : 'Add a worker'}
                  style={WBTN}>+</button>
        </span>
        <span className="muted" style={{ fontSize: 11, color: note ? '#185FA5' : undefined }}>
          {note || 'workers · live-scale (0–16)'}
        </span>
      </span>
      {/* Real-time worker state — what the pool is doing right now. */}
      <span style={{ display: 'flex', flexDirection: 'column', lineHeight: 1.1 }}>
        {workerCount > 0 && (
          <span className="workerdots" aria-hidden="true" style={{ marginBottom: 3 }}>
            {Array.from({ length: workerCount }, (_, i) => (
              <span key={i} className={i < active ? 'activedot' : 'idledot'} />
            ))}
          </span>
        )}
        <span style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, fontWeight: 600 }}>
          <span style={{ color: active > 0 ? '#185FA5' : 'var(--muted)' }}>
            {active > 0 && <span className="pulsedot" aria-hidden="true" style={{ marginRight: 5 }} />}
            {active} active
          </span>
          <span style={{ color: 'var(--muted)' }}>· {idle} idle</span>
          {initializing && <span style={{ color: '#185FA5' }}>· ⏳ initializing</span>}
        </span>
        <span className="muted" style={{ fontSize: 11 }}>
          {running > 0 ? `processing ${running} job${running !== 1 ? 's' : ''}` : 'idle — nothing in flight'}
          {queued > 0 ? ` · ${queued} waiting` : ''}
        </span>
      </span>
    </>
  )

  return (
    <section className="panel" style={{ marginBottom: 14 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
        <h2 style={{ margin: 0 }}>
          Async job queue{' '}
          <span className="muted">· durable scan &amp; remediation processing</span>
        </h2>
        {remFile && (
          <span aria-live="polite" style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13, color: '#185FA5', fontWeight: 600 }}>
            <span className="pulsedot" aria-hidden="true" />
            Remediating <span className="fname" title={remFile} style={{ fontWeight: 700 }}>{remFile}</span>
            {phaseLine(remJob) && <span className="muted" style={{ fontWeight: 400 }}>· {phaseLine(remJob)}</span>}
          </span>
        )}
      </div>

      {/* Split topology (#113): jobs normally run on the standalone worker service, whose
          heartbeat is worker_tier_alive — its liveness, not this container's local pool,
          is what says whether the queue is manned. */}
      {q && workerCount === 0 && q.worker_tier_alive && (
        <p className="muted" style={{ marginTop: 8, fontSize: 13 }}>
          <span style={{ color: '#1a7f37', fontWeight: 600 }}>✓ worker service online</span>{' '}
          — jobs run on the dedicated worker container. The controls below scale extra
          in-process workers in this container (normally unneeded).
        </p>
      )}
      {q && workerCount === 0 && !q.worker_tier_alive && (
        <p className="muted" style={{ marginTop: 8, fontSize: 13 }}>
          No workers available — the worker service isn't reporting a heartbeat, and this
          container has no in-process pool. Queued scans and remediation jobs won't process.
          Use <strong>+</strong> below to start emergency in-process workers.
        </p>
      )}
      {!q && err && <p className="muted" style={{ marginTop: 8, fontSize: 13 }}>Queue status unavailable: {err}</p>}

      {/* Azure Container App visibility — Monitor previously showed nothing about the dedicated
          worker service beyond "online"/"offline"; this is the same replica-config and
          current-replica/CPU/memory evidence Discover's WorkerAvailability strip already shows
          for a single scan, now available estate-wide. Read-only — adjust it from Settings →
          Worker Configuration (see the comment above `replicas` state for why). */}
      {externallyManaged && (
        <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 4 }}>
          {replicas?.configured ? (
            <p className="muted" style={{ margin: 0, fontSize: 13 }}>
              Azure warm replicas: {replicas.min_replicas}
              {replicas.max_replicas != null ? ` (max ${replicas.max_replicas})` : ''}
            </p>
          ) : (
            <p className="muted" style={{ margin: 0, fontSize: 13, fontStyle: 'italic' }}>
              Worker capacity is managed by your deployment administrator.
            </p>
          )}
          {capacity?.configured
           && (capacity.current_replicas != null || capacity.metrics_available
               || capacity.revision_health != null || capacity.draining_replicas
               || capacity.revision_traffic_percent != null) && (
            <div className="muted" style={{ fontSize: 11, display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              {capacity.current_replicas != null && (
                <span>
                  {capacity.current_replicas} replica{capacity.current_replicas === 1 ? '' : 's'} running now
                </span>
              )}
              <UtilizationBar label="CPU" percent={capacity.cpu_percent} />
              <UtilizationBar label="Memory" percent={capacity.memory_percent} />
              {capacity.revision_health != null && (
                <span style={{ color: capacity.revision_health === 'Healthy' ? '#1a7f37' : '#8A2A20', fontWeight: 600 }}>
                  Revision {capacity.revision_health.toLowerCase()}
                </span>
              )}
              {!!capacity.draining_replicas && (
                <span>{capacity.draining_replicas} replica{capacity.draining_replicas === 1 ? '' : 's'} draining from an older revision</span>
              )}
              {capacity.revision_traffic_percent != null && (
                <span>{capacity.revision_traffic_percent}% of traffic on the active revision</span>
              )}
            </div>
          )}
        </div>
      )}
      {diagnosis && (
        <div role="alert" style={{ marginTop: 8, fontSize: 12,
                                    color: diagnosis.severity === 'critical' ? '#8A2A20' : '#854F0B',
                                    display: 'flex', alignItems: 'baseline', gap: 5 }}>
          <span aria-hidden="true">⚠</span>
          <span>{diagnosis.message}</span>
        </div>
      )}

      <div style={{ display: 'flex', alignItems: 'center', gap: 18, flexWrap: 'wrap', marginTop: 12 }}
           role="status" aria-live="polite">
        {showPoolControls && (poolDecorative ? (
          <details>
            <summary className="muted" style={{ fontSize: 12, cursor: 'pointer' }}>
              Advanced: emergency in-process workers
            </summary>
            <div style={{ display: 'flex', alignItems: 'center', gap: 18, flexWrap: 'wrap', marginTop: 8 }}>
              {poolBlock}
            </div>
          </details>
        ) : poolBlock)}
        {fullList && scanCount > 0 && <Stat label={`scan${scanCount !== 1 ? 's' : ''}`} value={scanCount} />}
        {fullList && fileCount > 0 && <Stat label={`file${fileCount !== 1 ? 's' : ''}`} value={fileCount} />}
        {confirmed && <Stat label="total jobs" value={total}
              title="Each scan fans out into several durable jobs — discover, one per file, finalize, then assess — so this counts pipeline steps across all your scans, not documents." />}
        {throughput != null && <Stat label="throughput" value={`${throughput < 10 ? throughput.toFixed(1) : Math.round(throughput)}/min`} />}
        {/* "empty" is a CLAIM about the queue, so it needs a response that established it. This
            used to render on `shown.length === 0 && !err`, which is true before the first poll has
            returned — so a freshly-mounted panel asserted an empty queue it had never read. */}
        {confirmed && shown.length === 0 && (
          <span className="muted" style={{ fontSize: 13 }}>queue empty — nothing in flight</span>
        )}
        {!confirmed && (
          <span className="muted" style={{ fontSize: 13 }}>{statusLine(feedState)}</span>
        )}
        {needsFreshnessLabel(feedState) && (
          <span className="muted" style={{ fontSize: 12 }} title={
            meta?.fetchedAt ? new Date(meta.fetchedAt).toISOString() : undefined}>
            {statusLine(feedState, { ageMs: meta?.ageMs })}
          </span>
        )}
        {shown.map((s) => {
          const [fg, bg, label] = STATUS[s]
          return (
            <span key={s} style={{
              display: 'inline-flex', alignItems: 'center', gap: 7,
              padding: '5px 12px', borderRadius: 9, background: bg, color: fg,
              fontSize: 13, fontWeight: 600,
            }}>
              {s === 'running' && <span className="pulsedot" aria-hidden="true" />}
              {counts[s]} {label}
            </span>
          )
        })}
        {/* Stopped jobs get their own chip in a neutral colour rather than a red one, because
            "you stopped this" is not a condition anybody needs to act on. It is shown at all —
            rather than simply subtracted out of the dead count — so that the jobs do not appear
            to have evaporated: they really did end, and a user who pressed Stop should be able
            to see the consequence of having done so. */}
        {stoppedCount > 0 && (
          <span style={{
            display: 'inline-flex', alignItems: 'center', gap: 7,
            padding: '5px 12px', borderRadius: 9, background: '#EDEDEA', color: '#5C5C57',
            fontSize: 13, fontWeight: 600,
          }} title="Jobs that ended because a run was stopped or superseded, not because anything failed.">
            {stoppedCount} stopped
          </span>
        )}
      </div>

      {/* Dead-letters: show WHY they failed, what to do about it, and a clear-the-records
          action that is deliberately NOT phrased as the fix — it removes the diagnostic
          evidence, it doesn't touch whatever actually made the jobs fail. Retrying means
          re-running the originating action once the real cause is addressed. */}
      {failedCount > 0 && (
        <div style={{ marginTop: 12, padding: '10px 12px', borderRadius: 9,
                      background: '#FCEBEB', border: '1px solid #F3C9C9',
                      display: 'flex', flexDirection: 'column', gap: 6 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                        gap: 12, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 12.5, color: '#7A2020' }}>
              <strong>{failedCount} job{failedCount !== 1 ? 's' : ''} failed permanently.</strong>{' '}
              {deadReason ? `Reason: ${deadReason}` : 'See server logs for details.'}
              {deadReason?.includes('Drive token') &&
                ' — re-run remediation while signed in to retry the work.'}
            </span>
            <button className="ghost small" onClick={clearDead} disabled={busy}
                    title="Removes these records from the queue — this does not fix whatever caused the failures.">
              Dismiss records
            </button>
          </div>
          {/* Discover's suspicious-zero guard (_scan_discover, api/handlers.py) refuses to
              publish an empty listing over a proven non-empty inventory — the reason string is
              this specific and stable because it's a RuntimeError message, not free text, so
              matching it here is safe. Every dead-lettered attempt shares one root cause, so
              this reads as one incident rather than N unexplained identical rows. */}
          {deadReason?.includes('refusing to publish suspicious zero') && (
            <div style={{ fontSize: 12, color: '#7A2020' }}>
              ACP preserved the previously verified inventory rather than overwrite it with an
              empty result. Verify the source's connection and authorization, then re-run
              Discover to retry — dismissing these records alone will not.
            </div>
          )}
        </div>
      )}

      {/* Recent jobs — your own (the queue is owner-scoped), so you can see exactly which
          document each worker is processing right now and how long each step took. */}
      {q?.jobs?.length > 0 && (
        <div style={{ marginTop: 14 }}>
          {focusScanId && (
            <div className="queuefocusbanner" role="status">
              <span>Focused on this run</span>
              <button onClick={() => onClearFocus?.()}>Show all</button>
            </div>
          )}
          <div className="muted" style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '.04em', marginBottom: 6 }}>
            Recent jobs <span style={{ fontWeight: 400, textTransform: 'none' }}>· your most recent {Math.min(q.jobs.length, 8)}</span>
          </div>
          <div className="jobcards">
            {/* The focused scan's own job usually IS among the visible 8 — but not always: a
                terminal (done/dead) job old enough to have already been pushed off "recent 8" by
                newer activity is a real case, not an edge case to ignore. When none of the
                visible 8 match, prepend the single most recent matching job from the FULL list
                (already fetched by getJobs(), just sliced below for display) rather than let the
                banner point at a highlight nobody can see. Still additive, never a filter — every
                one of the visible 8 stays exactly where it was. */}
            {(() => {
              const visible = q.jobs.slice(0, 8)
              const focusInVisible = focusScanId && visible.some((jb) => jb.scan_id === focusScanId)
              const pushedOff = focusScanId && !focusInVisible
                ? q.jobs.find((jb) => jb.scan_id === focusScanId) : null
              return pushedOff ? [{ ...pushedOff, __pushedOff: true }, ...visible] : visible
            })().map((jb) => {
              const desc = jobDesc(jb)
              const dur = jb.created_at && jb.updated_at ? Math.max(0, (new Date(jb.updated_at) - new Date(jb.created_at)) / 1000) : null
              const [fg, bg] = STATUS[jb.status] || ['#555', '#eee']
              const phase = phaseLine(jb)
              const stalled = isStalled(jb, dur)
              const focused = !!focusScanId && jb.scan_id === focusScanId
              return (
                <div className={focused ? 'jobcard focused' : 'jobcard'} key={jb.id}>
                  <span className="jobtype">{JOBLABEL[jb.type] || jb.type}</span>
                  <span className="jobfile" title={jb.scan_id ? `${desc} · scan ${jb.scan_id}` : desc}>
                    {desc}
                    {jb.__pushedOff && (
                      <div className="jobphase muted" aria-live="polite">focused run · not in the most recent 8</div>
                    )}
                    {/* What this job is doing right now, straight from jobs.phase. Absent
                        phase renders nothing — never a placeholder standing in for work. */}
                    {phase && <div className="jobphase muted" aria-live="polite">{phase}</div>}
                    {jb.status === 'failed' && jb.last_error &&
                      <div className="jobphase" style={{ color: '#B3261E' }} title={jb.last_error}>{jb.last_error.slice(0, 90)}</div>}
                  </span>
                  <span className="jobstatus flash" key={jb.status} style={{ color: fg, background: bg }}>
                    {jb.status === 'running' && <span className="pulsedot" aria-hidden="true" />}{jb.status}
                  </span>
                  {jb.attempts > 1 && <span className="muted jobdur" title={`${jb.attempts} attempts`}>×{jb.attempts}</span>}
                  {stalled && (
                    <span className="jobstatus" style={{ color: '#8A4B00', background: '#FDF3E0' }}
                          title={`No new phase reported for over ${Math.round(STALLED_AFTER_S / 60)} minutes. A large deck can legitimately take this long — but so can a hung job.`}>
                      stalled?
                    </span>
                  )}
                  {dur != null && <span className="muted jobdur">{fmtDur(dur)}</span>}
                  {jb.scan_id && <TraceChip scanId={jb.scan_id} kind="session" label="trace" />}
                </div>
              )
            })}
          </div>
        </div>
      )}
    </section>
  )
}

function Stat({ label, value, title }) {
  return (
    <span title={title} style={{ display: 'flex', flexDirection: 'column', lineHeight: 1.1, cursor: title ? 'help' : undefined }}>
      <span style={{ fontSize: 22, fontWeight: 700 }}>{value}</span>
      <span className="muted" style={{ fontSize: 11 }}>{label}</span>
    </span>
  )
}
