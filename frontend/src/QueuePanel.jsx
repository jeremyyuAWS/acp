import { useEffect, useState, useRef } from 'react'
import { getJobs, setWorkers, clearDeadJobs, getWorkerReplicas, getWorkerCapacity } from './api.js'
import { TraceChip } from './Transparency.jsx'
import { phaseLine, isStalled, STALLED_AFTER_S } from './jobPhase.js'

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

export default function QueuePanel() {
  const [q, setQ] = useState(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState('')
  // Throughput meter: a rolling window of {t, done} samples from each poll -- no backend
  // change needed, "done" is already the cumulative completed-jobs counter getJobs()
  // returns. Rate = delta(done) / delta(t) over the oldest-vs-newest sample in the window.
  const historyRef = useRef([])
  const [throughput, setThroughput] = useState(null)   // jobs/min, or null until 2+ samples

  useEffect(() => {
    let on = true
    const load = () => getJobs()
      .then((d) => {
        if (!on) return
        setQ(d); setErr('')
        const now = Date.now()
        const done = d?.stats?.done ?? 0
        const hist = [...historyRef.current, { t: now, done }].filter((s) => now - s.t <= 5 * 60 * 1000)
        historyRef.current = hist
        if (hist.length >= 2) {
          const first = hist[0]
          const elapsedMin = (now - first.t) / 60000
          setThroughput(elapsedMin > 0 ? Math.max(0, (done - first.done) / elapsedMin) : null)
        }
      })
      .catch((e) => { if (on) setErr(e.message || 'unavailable') })
    load()
    // 2s poll so the worker queue animates in near-real-time (running → done ticks,
    // throughput, recent-job list) while a batch is churning — still light on the API.
    const t = setInterval(load, 2000)
    return () => { on = false; clearInterval(t) }
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
  const externallyManaged = q?.runtime_mode === 'distributed' && q?.worker_tier_alive
  const [replicas, setReplicas] = useState(null)
  useEffect(() => {
    if (!externallyManaged) return undefined
    let live = true
    getWorkerReplicas().then((d) => { if (live) setReplicas(d) }).catch(() => {})
    return () => { live = false }
  }, [externallyManaged])
  const [capacity, setCapacity] = useState(null)
  useEffect(() => {
    if (!externallyManaged) return undefined
    let live = true
    const loadCapacity = () => getWorkerCapacity().then((d) => { if (live) setCapacity(d) }).catch(() => {})
    loadCapacity()
    const id = setInterval(loadCapacity, 30000)
    return () => { live = false; clearInterval(id) }
  }, [externallyManaged])

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
  const workers = q?.workers ?? 0
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
  const order = ['queued', 'running', 'done', 'failed', 'dead']
  const shown = order.filter((s) => stats[s])
  const deadReason = q?.dead_letters?.top_errors?.[0]?.error
  // Real-time worker state: each 'running' job occupies one worker, so active ≈ running.
  const running = stats.running || 0
  const queued = stats.queued || 0
  const active = Math.min(running, workers)
  const idle = Math.max(0, workers - active)
  const initializing = note.includes('initializing')

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
      {q && workers === 0 && q.worker_tier_alive && (
        <p className="muted" style={{ marginTop: 8, fontSize: 13 }}>
          <span style={{ color: '#1a7f37', fontWeight: 600 }}>✓ worker service online</span>{' '}
          — jobs run on the dedicated worker container. The controls below scale extra
          in-process workers in this container (normally unneeded).
        </p>
      )}
      {q && workers === 0 && !q.worker_tier_alive && (
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
               || capacity.revision_health != null || capacity.draining_replicas) && (
            <div className="muted" style={{ fontSize: 11, display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              {capacity.current_replicas != null && (
                <span>
                  {capacity.current_replicas} replica{capacity.current_replicas === 1 ? '' : 's'} running now
                </span>
              )}
              {capacity.cpu_percent != null && <span>CPU {capacity.cpu_percent}%</span>}
              {capacity.memory_percent != null && <span>Memory {capacity.memory_percent}%</span>}
              {capacity.revision_health != null && (
                <span style={{ color: capacity.revision_health === 'Healthy' ? '#1a7f37' : '#8A2A20', fontWeight: 600 }}>
                  Revision {capacity.revision_health.toLowerCase()}
                </span>
              )}
              {!!capacity.draining_replicas && (
                <span>{capacity.draining_replicas} replica{capacity.draining_replicas === 1 ? '' : 's'} draining from an older revision</span>
              )}
            </div>
          )}
        </div>
      )}

      <div style={{ display: 'flex', alignItems: 'center', gap: 18, flexWrap: 'wrap', marginTop: 12 }}
           role="status" aria-live="polite">
        <span style={{ display: 'flex', flexDirection: 'column', lineHeight: 1.1 }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <button onClick={() => scaleWorkers(workers - 1)}
                    disabled={busy || workers <= 0} aria-label="Remove a worker"
                    title={workers <= 0 ? 'Already at 0 — nothing to remove' : 'Remove a worker'}
                    style={WBTN}>−</button>
            <span style={{ fontSize: 22, fontWeight: 700, minWidth: 22, textAlign: 'center' }}>{workers}</span>
            <button onClick={() => scaleWorkers(workers + 1)}
                    disabled={busy || workers >= 16} aria-label="Add a worker"
                    title={workers >= 16 ? 'Pool cap is 16 workers' : 'Add a worker'}
                    style={WBTN}>+</button>
          </span>
          <span className="muted" style={{ fontSize: 11, color: note ? '#185FA5' : undefined }}>
            {note || 'workers · live-scale (0–16)'}
          </span>
        </span>
        {/* Real-time worker state — what the pool is doing right now. */}
        <span style={{ display: 'flex', flexDirection: 'column', lineHeight: 1.1 }}>
          {workers > 0 && (
            <span className="workerdots" aria-hidden="true" style={{ marginBottom: 3 }}>
              {Array.from({ length: workers }, (_, i) => (
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
        {fullList && scanCount > 0 && <Stat label={`scan${scanCount !== 1 ? 's' : ''}`} value={scanCount} />}
        {fullList && fileCount > 0 && <Stat label={`file${fileCount !== 1 ? 's' : ''}`} value={fileCount} />}
        <Stat label="total jobs" value={total}
              title="Each scan fans out into several durable jobs — discover, one per file, finalize, then assess — so this counts pipeline steps across all your scans, not documents." />
        {throughput != null && <Stat label="throughput" value={`${throughput < 10 ? throughput.toFixed(1) : Math.round(throughput)}/min`} />}
        {shown.length === 0 && !err && (
          <span className="muted" style={{ fontSize: 13 }}>queue empty — nothing in flight</span>
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
              {stats[s]} {label}
            </span>
          )
        })}
      </div>

      {/* Dead-letters: show WHY they failed + a one-click clear (terminal failures —
          re-run the originating action to retry the actual work). */}
      {stats.dead > 0 && (
        <div style={{ marginTop: 12, padding: '10px 12px', borderRadius: 9,
                      background: '#FCEBEB', border: '1px solid #F3C9C9',
                      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                      gap: 12, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 12.5, color: '#7A2020' }}>
            <strong>{stats.dead} job{stats.dead !== 1 ? 's' : ''} failed permanently.</strong>{' '}
            {deadReason ? `Reason: ${deadReason}` : 'See server logs for details.'}
            {deadReason?.includes('Drive token') &&
              ' — re-run remediation while signed in to retry the work.'}
          </span>
          <button className="ghost small" onClick={clearDead} disabled={busy}
                  title="Remove these terminal-failure jobs from the queue">
            Clear dead-letters
          </button>
        </div>
      )}

      {/* Recent jobs — your own (the queue is owner-scoped), so you can see exactly which
          document each worker is processing right now and how long each step took. */}
      {q?.jobs?.length > 0 && (
        <div style={{ marginTop: 14 }}>
          <div className="muted" style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '.04em', marginBottom: 6 }}>
            Recent jobs <span style={{ fontWeight: 400, textTransform: 'none' }}>· your most recent {Math.min(q.jobs.length, 8)}</span>
          </div>
          <div className="jobcards">
            {q.jobs.slice(0, 8).map((jb) => {
              const desc = jobDesc(jb)
              const dur = jb.created_at && jb.updated_at ? Math.max(0, (new Date(jb.updated_at) - new Date(jb.created_at)) / 1000) : null
              const [fg, bg] = STATUS[jb.status] || ['#555', '#eee']
              const phase = phaseLine(jb)
              const stalled = isStalled(jb, dur)
              return (
                <div className="jobcard" key={jb.id}>
                  <span className="jobtype">{JOBLABEL[jb.type] || jb.type}</span>
                  <span className="jobfile" title={jb.scan_id ? `${desc} · scan ${jb.scan_id}` : desc}>
                    {desc}
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
