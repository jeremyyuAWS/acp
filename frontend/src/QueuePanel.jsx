import { useEffect, useState } from 'react'
import { getJobs, setWorkers, clearDeadJobs } from './api.js'

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
