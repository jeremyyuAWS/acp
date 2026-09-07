import { useId, useState } from 'react'
import { NOT_REPORTED, REPLICA_STATES, TONE, formatDuration, num, replicaLifecycle } from './liveOpsDrawer.js'

const PANEL = { minWidth: 0, border: '1px solid var(--line)', borderRadius: 10,
  background: 'var(--card, #fff)' }
const FIFTEEN_MINUTES_MS = 15 * 60 * 1000

export const OVERVIEW_METRICS = [
  { key: 'replicas', label: 'Replicas', format: compactNumber },
  { key: 'cpu_percent', label: 'CPU', format: (value) => percent(value) },
  { key: 'memory_percent', label: 'Memory', format: (value) => percent(value) },
  { key: 'restarts', label: 'Restarts', format: compactNumber, adverseIncrease: true },
  { key: 'network_in_bytes', label: 'Network in', format: formatBytes },
  { key: 'network_out_bytes', label: 'Network out', format: formatBytes },
]

function compactNumber(value) {
  const n = num(value)
  return n == null ? NOT_REPORTED : new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 }).format(n)
}

function percent(value) {
  const formatted = compactNumber(value)
  return formatted === NOT_REPORTED ? formatted : `${formatted}%`
}

export function formatBytes(value) {
  const n = num(value)
  if (n == null) return NOT_REPORTED
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let amount = Math.abs(n)
  let unit = 0
  while (amount >= 1024 && unit < units.length - 1) { amount /= 1024; unit += 1 }
  const signed = n < 0 ? -amount : amount
  return `${new Intl.NumberFormat('en-US', { maximumFractionDigits: amount < 10 ? 1 : 0 }).format(signed)} ${units[unit]}`
}

function metricSeries(metric = {}, nowMs) {
  const start = nowMs - FIFTEEN_MINUTES_MS
  return (Array.isArray(metric.series) ? metric.series : [])
    .map((point) => ({ at: new Date(point?.at).getTime(), value: num(point?.value) }))
    .filter((point) => Number.isFinite(point.at) && point.at >= start && point.at <= nowMs)
    .sort((a, b) => a.at - b.at)
}

/** Stable integration contract for the drawer's Overview tab. */
export function liveOpsOverviewModel({ capacity = null, service = null, nowMs = Date.now() } = {}) {
  const metrics = OVERVIEW_METRICS.map((definition) => {
    const metric = capacity?.metrics?.[definition.key] || {}
    const series = metricSeries(metric, nowMs)
    const latest = metric.available === false ? null : num(metric.latest)
    const first = series.find((point) => point.value != null)?.value
    const last = [...series].reverse().find((point) => point.value != null)?.value
    const change = first == null || last == null ? null : last - first
    return { ...definition, latest, value: definition.format(latest), series,
      delta: change === 0 ? 0 : change,
      deltaLabel: change == null ? 'Change not reported' : change === 0 ? 'No change over 15 minutes'
        : `${change > 0 ? 'Up' : 'Down'} ${definition.format(Math.abs(change))} over 15 minutes` }
  })
  return { metrics, lifecycle: replicaLifecycle(capacity, service), capacity }
}

function Sparkline({ metric }) {
  const values = metric.series.filter((point) => point.value != null)
  if (values.length < 2) return <div className="muted" style={{ fontSize: 10, marginTop: 8 }}>Trend not reported</div>
  const min = Math.min(...values.map((point) => point.value))
  const max = Math.max(...values.map((point) => point.value))
  const range = max - min
  const points = values.map((point, index) => {
    const x = values.length === 1 ? 50 : (index / (values.length - 1)) * 100
    const y = range === 0 ? 14 : 25 - ((point.value - min) / range) * 22
    return `${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
  return <svg viewBox="0 0 100 28" preserveAspectRatio="none" role="img"
    aria-label={`${metric.label}, 15-minute trend. ${metric.deltaLabel}`}
    style={{ display: 'block', width: '100%', height: 28, marginTop: 7 }}>
    <polyline points={points} fill="none" stroke="currentColor" strokeWidth="2"
      vectorEffect="non-scaling-stroke" />
  </svg>
}

function MetricCard({ metric }) {
  const changed = metric.delta != null && metric.delta !== 0
  const deltaColor = metric.adverseIncrease && metric.delta > 0 ? TONE.bad : 'var(--muted)'
  return <li style={{ ...PANEL, listStyle: 'none', padding: 10 }}>
    <span className="muted" style={{ display: 'block', fontSize: 11 }}>{metric.label}</span>
    <strong style={{ display: 'block', marginTop: 2, fontSize: 18 }}>{metric.value}</strong>
    <span aria-label={metric.deltaLabel} style={{ display: 'block', minHeight: 16, marginTop: 2,
      fontSize: 10.5, color: deltaColor }}>
      {metric.delta == null ? '— Change unavailable' : changed
        ? `${metric.delta > 0 ? '↑' : '↓'} ${metric.format(Math.abs(metric.delta))}`
        : '— No change'}
    </span>
    <Sparkline metric={metric} />
  </li>
}

function ReplicaCard({ replica }) {
  const state = REPLICA_STATES[replica?.state] || REPLICA_STATES.unknown
  return <li style={{ ...PANEL, listStyle: 'none', padding: 9 }}>
    <div style={{ display: 'flex', gap: 7, alignItems: 'baseline', flexWrap: 'wrap' }}>
      <span aria-hidden="true" style={{ color: TONE[state.tone] }}>{state.icon}</span>
      <b style={{ overflowWrap: 'anywhere' }}>{replica?.name || 'Unnamed replica'}</b>
      <span style={{ color: TONE[state.tone], fontSize: 11, fontWeight: 700 }}>{state.label}</span>
      <span className="muted" style={{ marginLeft: 'auto', fontSize: 11 }}>
        {replica?.age_s == null ? NOT_REPORTED : `up ${formatDuration(replica.age_s)}`}
      </span>
    </div>
    <div className="muted" style={{ marginTop: 3, fontSize: 11, overflowWrap: 'anywhere' }}>
      {replica?.containers_ready == null || replica?.containers == null
        ? 'Container readiness not reported'
        : `${replica.containers_ready}/${replica.containers} containers ready`}
      {' · '}{replica?.restarts == null ? 'restarts not reported'
        : `${replica.restarts} restart${replica.restarts === 1 ? '' : 's'}`}
      {replica?.revision ? ` · ${replica.revision}` : ''}
    </div>
  </li>
}

function LifecycleSummary({ lifecycle }) {
  const [expanded, setExpanded] = useState(false)
  const listId = useId()
  if (!lifecycle.available) return <p className="muted" style={{ fontSize: 12 }}>{lifecycle.reason}</p>
  const replicas = lifecycle.replicas || []
  const shown = expanded ? replicas : replicas.slice(0, 3)
  return <section aria-label="Replica lifecycle summary" style={{ marginTop: 14 }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'baseline' }}>
      <b>Replica lifecycle</b><span className="muted" style={{ fontSize: 11 }}>{lifecycle.total} total</span>
    </div>
    <ul aria-label="Replica state counts" style={{ display: 'flex', flexWrap: 'wrap', gap: '5px 12px',
      listStyle: 'none', padding: 0, margin: '8px 0 0', fontSize: 11 }}>
      {lifecycle.counts.map((row) => <li key={row.state}>
        <span aria-hidden="true" style={{ color: TONE[row.tone] }}>{row.icon} </span>{row.label} <b>{row.count}</b>
      </li>)}
    </ul>
    {!!replicas.length && <ul id={listId} style={{ display: 'grid', gap: 6, listStyle: 'none',
      padding: 0, margin: '9px 0 0', ...(expanded ? { maxHeight: 360, overflowY: 'auto', paddingRight: 4 } : {}) }}>
      {shown.map((replica) => <ReplicaCard key={`${replica.revision || ''}:${replica.name || ''}`} replica={replica} />)}
    </ul>}
    {replicas.length > 3 && <button type="button" className="ghost small" aria-expanded={expanded}
      aria-controls={listId} onClick={() => setExpanded((value) => !value)} style={{ marginTop: 7 }}>
      {expanded ? 'Show fewer replicas' : `Show all ${replicas.length} replicas`}
    </button>}
  </section>
}

function CapacityAllocation({ capacity }) {
  const reserved = capacity?.metrics?.reserved_cores
  const reservedValue = reserved?.available === false ? null : num(reserved?.latest)
  return <details style={{ ...PANEL, marginTop: 14, padding: '9px 11px' }}>
    <summary style={{ cursor: 'pointer', fontWeight: 700 }}>Capacity allocation</summary>
    <dl style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1fr) auto', gap: '6px 12px',
      margin: '10px 0 0', fontSize: 12 }}>
      <dt>CPU per replica</dt><dd style={{ margin: 0 }}>{num(capacity?.cpu_cores_per_replica) == null
        ? NOT_REPORTED : `${capacity.cpu_cores_per_replica} cores`}</dd>
      <dt>Memory per replica</dt><dd style={{ margin: 0 }}>{capacity?.memory_per_replica || NOT_REPORTED}</dd>
      <dt>Reserved cores</dt><dd style={{ margin: 0 }}>{reservedValue == null ? NOT_REPORTED : `${reservedValue} cores`}</dd>
    </dl>
  </details>
}

export function LiveOpsOverviewMetrics({ capacity = null, service = null, nowMs = Date.now() }) {
  const model = liveOpsOverviewModel({ capacity, service, nowMs })
  return <section aria-label="Live Operations overview metrics">
    <ul style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(125px,1fr))',
      gap: 7, padding: 0, margin: 0 }}>
      {model.metrics.map((metric) => <MetricCard key={metric.key} metric={metric} />)}
    </ul>
    <LifecycleSummary lifecycle={model.lifecycle} />
    <CapacityAllocation capacity={capacity} />
  </section>
}
