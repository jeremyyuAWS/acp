import { useEffect, useState } from 'react'
import { getJobs } from './api.js'

// Live view of the durable async job queue (ADR 0004). Polls /jobs and shows
// queue depth by status. The same data Grafana's queue panel renders.
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

  useEffect(() => {
    let on = true
    const load = () => getJobs()
      .then((d) => { if (on) { setQ(d); setErr('') } })
      .catch((e) => { if (on) setErr(e.message || 'unavailable') })
    load()
    const t = setInterval(load, 4000)
    return () => { on = false; clearInterval(t) }
  }, [])

  const stats = q?.stats || {}
  const workers = q?.workers ?? 0
  const total = Object.values(stats).reduce((a, b) => a + b, 0)
  const order = ['queued', 'running', 'done', 'failed', 'dead']
  const shown = order.filter((s) => stats[s])

  return (
    <section className="panel" style={{ marginBottom: 14 }}>
      <h2 style={{ margin: 0 }}>
        Async job queue{' '}
        <span className="muted">· durable scan &amp; remediation processing</span>
      </h2>

      {q && workers === 0 && (
        <p className="muted" style={{ marginTop: 8, fontSize: 13 }}>
          No workers running. Set <code>ACP_WORKERS</code> (e.g. 4) at deploy to process
          queued scans and remediation jobs.
        </p>
      )}
      {!q && err && <p className="muted" style={{ marginTop: 8, fontSize: 13 }}>Queue status unavailable: {err}</p>}

      <div style={{ display: 'flex', alignItems: 'center', gap: 18, flexWrap: 'wrap', marginTop: 12 }}
           role="status" aria-live="polite">
        <Stat label="workers" value={workers} />
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
