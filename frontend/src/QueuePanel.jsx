import { useEffect, useState } from 'react'
import { getJobs, setWorkers, clearDeadJobs } from './api.js'
import { TraceChip } from './Transparency.jsx'

// Job-type → short human label for the recent-jobs cards.
const JOBLABEL = {
  scan_discover: 'discover', scan_file: 'scan file', scan_batch: 'scan batch',
  scan_finalize: 'finalize', remediate_file: 'remediate', assess_trace: 'assess', scan: 'scan',
}
const fmtDur = (s) => (s == null ? '' : s < 1 ? '<1s' : s < 60 ? `${Math.round(s)}s` : `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`)
const jobFile = (payload) => { try { return JSON.parse(payload || '{}').file || null } catch { return null } }

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

export default function QueuePanel() {
  const [q, setQ] = useState(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState('')

  useEffect(() => {
    let on = true
    const load = () => getJobs()
      .then((d) => { if (on) { setQ(d); setErr('') } })
      .catch((e) => { if (on) setErr(e.message || 'unavailable') })
    load()
    const t = setInterval(load, 4000)
    return () => { on = false; clearInterval(t) }
  }, [])

  const scaleWorkers = (next) => {
    const cur = q?.workers ?? 0
    const n = Math.max(0, Math.min(16, next))
    if (n === cur) return
    setBusy(true)
    setNote(n > cur ? '⏳ initializing a worker…' : '⏳ retiring a worker (finishes its current job)…')
    setQ((c) => ({ ...(c || {}), workers: n }))   // optimistic
    setWorkers(n)
      .then((d) => {
        setQ((c) => ({ ...(c || {}), workers: d.workers }))
        setNote(n > cur ? '✓ worker ready' : '✓ worker retired')
      })
      .catch((e) => { setErr(e.message || 'could not change workers'); setNote('') })
      .finally(() => { setBusy(false); setTimeout(() => setNote(''), 2500) })
  }

  const clearDead = () => {
    setBusy(true); setNote('⏳ clearing dead-letters…')
    clearDeadJobs()
      .then((d) => { setNote(`✓ cleared ${d.purged ?? 0} dead-letter job(s)`); return getJobs().then(setQ) })
      .catch((e) => setErr(e.message || 'could not clear dead-letters'))
      .finally(() => { setBusy(false); setTimeout(() => setNote(''), 2500) })
  }

  const stats = q?.stats || {}
  const workers = q?.workers ?? 0
  const total = Object.values(stats).reduce((a, b) => a + b, 0)
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
      <h2 style={{ margin: 0 }}>
        Async job queue{' '}
        <span className="muted">· durable scan &amp; remediation processing</span>
      </h2>

      {q && workers === 0 && (
        <p className="muted" style={{ marginTop: 8, fontSize: 13 }}>
          No workers running — queued scans and remediation jobs won't process.
          Use <strong>+</strong> below to start some.
        </p>
      )}
      {!q && err && <p className="muted" style={{ marginTop: 8, fontSize: 13 }}>Queue status unavailable: {err}</p>}

      <div style={{ display: 'flex', alignItems: 'center', gap: 18, flexWrap: 'wrap', marginTop: 12 }}
           role="status" aria-live="polite">
        <span style={{ display: 'flex', flexDirection: 'column', lineHeight: 1.1 }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <button onClick={() => scaleWorkers(workers - 1)}
                    disabled={busy || workers <= 0} aria-label="Remove a worker" title="Remove a worker"
                    style={WBTN}>−</button>
            <span style={{ fontSize: 22, fontWeight: 700, minWidth: 22, textAlign: 'center' }}>{workers}</span>
            <button onClick={() => scaleWorkers(workers + 1)}
                    disabled={busy || workers >= 16} aria-label="Add a worker" title="Add a worker"
                    style={WBTN}>+</button>
          </span>
          <span className="muted" style={{ fontSize: 11, color: note ? '#185FA5' : undefined }}>
            {note || 'workers · live-scale (0–16)'}
          </span>
        </span>
        {/* Real-time worker state — what the pool is doing right now. */}
        <span style={{ display: 'flex', flexDirection: 'column', lineHeight: 1.1 }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, fontWeight: 600 }}>
            <span style={{ color: active > 0 ? '#185FA5' : 'var(--muted)' }}>
              {active > 0 && <span className="livedot" aria-hidden="true" style={{ marginRight: 5 }} />}
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
        <Stat label="total jobs" value={total} />
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
              {s === 'running' && <span className="livedot" aria-hidden="true" />}
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
              const file = jobFile(jb.payload)
              const dur = jb.created_at && jb.updated_at ? Math.max(0, (new Date(jb.updated_at) - new Date(jb.created_at)) / 1000) : null
              const [fg, bg] = STATUS[jb.status] || ['#555', '#eee']
              return (
                <div className="jobcard" key={jb.id}>
                  <span className="jobtype">{JOBLABEL[jb.type] || jb.type}</span>
                  <span className="jobfile" title={file || jb.scan_id || jb.id}>
                    {file || (jb.scan_id ? `scan ${String(jb.scan_id).slice(0, 8)}` : String(jb.id).slice(0, 8))}
                  </span>
                  <span className="jobstatus" style={{ color: fg, background: bg }}>
                    {jb.status === 'running' && <span className="livedot" aria-hidden="true" />}{jb.status}
                  </span>
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

function Stat({ label, value }) {
  return (
    <span style={{ display: 'flex', flexDirection: 'column', lineHeight: 1.1 }}>
      <span style={{ fontSize: 22, fontWeight: 700 }}>{value}</span>
      <span className="muted" style={{ fontSize: 11 }}>{label}</span>
    </span>
  )
}
