import { useEffect, useState } from 'react'
import { getWorkerRevisions } from './api.js'

// The Container App deploy history — every revision GET /control/workers/revisions returns, not
// just the active one QueuePanel/WorkerAvailability already surface a handful of fields from.
// Answers "what got deployed, when, and is it healthy" — previously only visible in the Azure
// portal. Self-contained (own fetch, own state), same shape as QueuePanel, but does NOT poll:
// revisions change only on deploy, not continuously, so a mount-time fetch plus a manual refresh
// button is the honest cadence — polling every 30s like the capacity gauge would just be wasted
// Azure API calls for data that is rarely different.
const relTime = (iso) => {
  if (!iso) return null
  const ms = Date.now() - new Date(iso).getTime()
  if (!Number.isFinite(ms)) return null
  const mins = Math.round(ms / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.round(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.round(hrs / 24)}d ago`
}

// Container App revision names are the app name plus a generated suffix
// (e.g. "acp-worker--rev-a1b2c3") — the suffix is the only part that varies, so that's what's
// worth showing in a table where every row starts the same way.
const shortName = (name) => {
  if (!name) return '—'
  const i = name.lastIndexOf('--')
  return i === -1 ? name : name.slice(i + 2)
}

export default function RevisionHistoryPanel() {
  const [state, setState] = useState({ loading: true, configured: null, revisions: [], error: null })

  const load = () => {
    setState((s) => ({ ...s, loading: true, error: null }))
    getWorkerRevisions()
      .then((r) => setState({ loading: false, configured: r.configured, revisions: r.revisions || [], error: null }))
      .catch(() => setState((s) => ({ ...s, loading: false, error: 'Could not load revision history.' })))
  }

  useEffect(() => { load() }, [])

  if (state.configured === false) return null   // no Azure configured — nothing to show

  return (
    <div style={{ marginTop: 18 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
        <h3 style={{ margin: 0, fontSize: 13 }}>Deploy history</h3>
        <button type="button" onClick={load} disabled={state.loading}
                style={{ fontSize: 12, background: 'none', border: '1px solid var(--line)',
                         borderRadius: 6, padding: '3px 10px', cursor: state.loading ? 'default' : 'pointer' }}>
          {state.loading ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>

      {state.error && <p role="alert" style={{ color: '#8A2A20', fontSize: 13, margin: 0 }}>{state.error}</p>}

      {!state.error && !state.loading && state.configured && state.revisions.length === 0 && (
        <p className="muted" style={{ fontSize: 13, margin: 0 }}>No revision history found.</p>
      )}

      {state.revisions.length > 0 && (
        <div style={{ overflowX: 'auto' }}>
          <table>
            <thead>
              <tr>
                <th>Revision</th>
                <th>Status</th>
                <th>Traffic</th>
                <th>Replicas</th>
                <th>Deployed</th>
              </tr>
            </thead>
            <tbody>
              {state.revisions.map((r) => {
                const healthy = r.health_state === 'Healthy'
                const rel = relTime(r.created_time)
                return (
                  <tr key={r.name}>
                    <td>
                      {shortName(r.name)}
                      {r.active && <span style={{ marginLeft: 6, fontSize: 11, fontWeight: 600, color: '#175CD3' }}>· active</span>}
                    </td>
                    <td style={{ color: r.health_state == null ? undefined : (healthy ? '#1a7f37' : '#8A2A20') }}>
                      {r.health_state || '—'}
                      {r.provisioning_state ? ` · ${r.provisioning_state}` : ''}
                    </td>
                    <td>{r.traffic_percent != null ? `${r.traffic_percent}%` : '—'}</td>
                    <td>{r.replicas != null ? r.replicas : '—'}</td>
                    <td title={r.created_time || undefined}>{rel || '—'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
