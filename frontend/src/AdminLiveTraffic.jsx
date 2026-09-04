import { useEffect, useMemo, useRef, useState } from 'react'
import { Background, Controls, Handle, MiniMap, Position, ReactFlow } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { getAdminActivity, openAdminActivityStream } from './api.js'

const STAGE = {
  discover: { label: 'Discover', color: '#4F7F2A' },
  assess: { label: 'Assess', color: '#4C78C2' },
  remediate: { label: 'Remediate', color: '#8B4D79' },
  release: { label: 'Release', color: '#A66A16' },
}

const PRESSURE = {
  healthy: { label: 'Capacity available', color: '#4F7F2A' },
  busy: { label: 'Work waiting', color: '#A66A16' },
  saturated: { label: 'At capacity', color: '#B45309' },
  stalled: { label: 'Queue stalled', color: '#B4232F' },
}

function age(iso) {
  if (!iso) return '—'
  const seconds = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000))
  if (seconds < 60) return `${seconds}s`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`
}

export function queueConcentration(runs = []) {
  const byOwner = new Map()
  let total = 0
  for (const run of runs) {
    const queued = Number(run.queued || 0)
    total += queued
    byOwner.set(run.owner, (byOwner.get(run.owner) || 0) + queued)
  }
  const [owner, count] = [...byOwner.entries()].sort((a, b) => b[1] - a[1])[0] || []
  return { owner, count: count || 0, total, pct: total ? Math.round((count / total) * 100) : 0 }
}

export function workerServiceRows(summary = {}) {
  const roles = summary.worker_roles || {}
  const load = summary.by_stage || {}
  return ['discovery', 'assess', 'remediate'].filter((role) => roles[role]).map((role) => {
    const heartbeat = roles[role]
    const stage = role === 'discovery' ? 'discover' : role
    const active = Number(load[stage]?.running || 0)
    const slots = Number(heartbeat.pool_size || 0)
    return {
      role, stage, active, slots, available: Math.max(0, slots - active),
      alive: Boolean(heartbeat.alive), age_s: heartbeat.age_s, version: heartbeat.version,
    }
  })
}

function MiniTrend({ values = [], color }) {
  const points = values.slice(-18).map((value) => typeof value === 'number' ? value : value.completed)
  if (points.length < 2) return <span className="muted" style={{ fontSize: 11 }}>collecting activity…</span>
  const max = Math.max(...points, 1)
  const coords = points.map((v, i) => `${(i / (points.length - 1)) * 92},${25 - (v / max) * 22}`).join(' ')
  return <svg aria-label="Recent completed-item activity" viewBox="0 0 92 28" style={{ width: 92, height: 28 }}>
    <polyline points={coords} fill="none" stroke={color} strokeWidth="2" vectorEffect="non-scaling-stroke" />
  </svg>
}

export function MetricChart({ values = [], field, label, color }) {
  const points = values.map((value) => Number(typeof value === 'number' ? value : value[field]) || 0)
  const max = Math.max(...points, 1)
  const coords = points.length > 1
    ? points.map((value, index) => `${24 + (index / (points.length - 1)) * 246},${12 + (1 - value / max) * 82}`).join(' ')
    : ''
  return <div className="panel" style={{ padding: 10 }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}><b style={{ fontSize: 12 }}>{label}</b>
      <span style={{ color, fontWeight: 700 }}>{points.at(-1) ?? 0}</span></div>
    {points.length > 1 ? <svg role="img" aria-label={`${label} over recent live updates`} viewBox="0 0 282 116" style={{ width: '100%', height: 116 }}>
      <line x1="24" y1="12" x2="24" y2="94" stroke="var(--border)" />
      <line x1="24" y1="94" x2="270" y2="94" stroke="var(--border)" />
      <text x="2" y="17" fontSize="9" fill="var(--muted)">{max}</text>
      <text x="10" y="96" fontSize="9" fill="var(--muted)">0</text>
      <text x="24" y="109" fontSize="9" fill="var(--muted)">earlier</text>
      <text x="248" y="109" fontSize="9" fill="var(--muted)">now</text>
      <polyline points={coords} fill="none" stroke={color} strokeWidth="2" vectorEffect="non-scaling-stroke" />
    </svg> : <div className="muted" style={{ height: 116, display: 'grid', placeItems: 'center', fontSize: 12 }}>Collecting live samples…</div>}
  </div>
}

export function trendToggleLabel(expanded) {
  return expanded ? 'Hide live trends' : 'Show live trends'
}

function RunNode({ data }) {
  const cfg = STAGE[data.run.stage] || { label: data.run.stage, color: '#6B7280' }
  const pct = data.run.total ? Math.round((data.run.completed / data.run.total) * 100) : 0
  return <div title="Select for live run details; double-click to open charts"
    style={{ width: 225, padding: 12, background: 'var(--panel)', border: `2px solid ${cfg.color}`,
    borderRadius: 10, boxShadow: '0 3px 10px rgba(24,20,28,.10)' }}>
    <Handle type="target" position={Position.Left} />
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
      <b>{cfg.label}</b><span style={{ color: cfg.color, fontWeight: 700 }}>{data.run.status === 'recent' ? 'Complete' : `${pct}%`}</span>
    </div>
    <div className="muted" style={{ fontSize: 11, marginTop: 3 }}>{data.run.owner}</div>
    <div style={{ height: 5, background: 'var(--border)', borderRadius: 4, margin: '9px 0 7px' }}>
      <div style={{ width: `${pct}%`, height: '100%', background: cfg.color, borderRadius: 4 }} />
    </div>
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'end' }}>
      <span style={{ fontSize: 12 }}>{data.run.status === 'recent' ? `Finished ${age(data.run.updated_at)} ago` : `${data.run.completed}/${data.run.total} · ${data.run.running} active`}</span>
      <MiniTrend values={data.history} color={cfg.color} />
    </div>
    {!!data.run.queued && <div style={{ fontSize: 11, marginTop: 5, color: 'var(--muted)' }}>
      {data.run.queued} waiting{data.run.queue_position ? ` · queue position ${data.run.queue_position}` : ''}
    </div>}
    <Handle type="source" position={Position.Right} />
  </div>
}

const nodeTypes = { run: RunNode }

export function buildTrafficGraph(snapshot, historyMap = new Map()) {
  const runs = snapshot?.runs || []
  const sources = [...new Set(runs.map((r) => r.source || 'unknown'))]
  const stages = [...new Set(runs.map((r) => r.stage))]
  const nodes = []
  const edges = []
  sources.forEach((source, i) => nodes.push({ id: `source:${source}`, position: { x: 10, y: i * 135 + 30 },
    data: { label: source === 'drive' ? 'Google Drive' : source === 'sharepoint' ? 'SharePoint' : source },
    style: { borderRadius: 20, border: '1px solid var(--border)', fontWeight: 700 } }))
  stages.forEach((stage, i) => nodes.push({ id: `stage:${stage}`, position: { x: 720, y: i * 115 + 30 },
    data: { label: `${STAGE[stage]?.label || stage} workers` }, style: { borderRadius: 20,
      border: `2px solid ${STAGE[stage]?.color || '#6B7280'}`, fontWeight: 700 } }))
  runs.forEach((run, i) => {
    const key = `${run.scan_id}:${run.stage}`
    const series = historyMap.get(key) || []
    const sample = { at: snapshot?.generated_at || new Date().toISOString(), completed: Number(run.completed || 0),
      running: Number(run.running || 0), queued: Number(run.queued || 0) }
    const last = series.at(-1)
    if (!last || ['completed', 'running', 'queued'].some((field) => Number(last[field] || 0) !== sample[field])) series.push(sample)
    historyMap.set(key, series.slice(-30))
    nodes.push({ id: key, type: 'run', position: { x: 310, y: i * 125 + 10 }, data: { run, history: series } })
    edges.push({ id: `in:${key}`, source: `source:${run.source || 'unknown'}`, target: key,
      animated: run.running > 0, style: { stroke: STAGE[run.stage]?.color || '#6B7280' } })
    edges.push({ id: `out:${key}`, source: key, target: `stage:${run.stage}`,
      animated: run.running > 0, style: { stroke: STAGE[run.stage]?.color || '#6B7280' } })
  })
  return { nodes, edges }
}

export default function AdminLiveTraffic() {
  const [snapshot, setSnapshot] = useState(null)
  const [selectedKey, setSelectedKey] = useState(null)
  const [expanded, setExpanded] = useState(false)
  const [connection, setConnection] = useState('connecting')
  const history = useRef(new Map())

  useEffect(() => {
    let active = true
    getAdminActivity().then((d) => { if (active) { setSnapshot(d); setConnection('live') } })
      .catch(() => { if (active) setConnection('unavailable') })
    const stream = openAdminActivityStream({
      onMessage: (d) => { if (active) { setSnapshot(d); setConnection('live') } },
      onError: () => { if (active) setConnection('reconnecting') },
    })
    return () => { active = false; stream.close() }
  }, [])

  useEffect(() => {
    if (!selectedKey) return undefined
    const onKey = (event) => { if (event.key === 'Escape') setSelectedKey(null) }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [selectedKey])

  const graph = useMemo(() => buildTrafficGraph(snapshot, history.current), [snapshot])
  const selectedNode = graph.nodes.find((node) => node.id === selectedKey)?.data
  const selected = selectedNode?.run
  const selectedHistory = selectedNode?.history || []

  const summary = snapshot?.summary || {}
  const concentration = queueConcentration(snapshot?.runs)
  const pressure = PRESSURE[summary.pressure] || PRESSURE.healthy
  const stageRows = Object.entries(summary.by_stage || {})
  const services = workerServiceRows(summary)
  return <section className="panel" style={{ padding: 16, marginBottom: 20 }} aria-label="Live Azure processing traffic">
    <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', marginBottom: 10 }}>
      <div><b>Live Azure traffic</b><div className="muted" style={{ fontSize: 12 }}>Active worker flow plus the last 15 minutes</div></div>
      <span className="chip" style={{ marginLeft: 'auto' }}>● {connection}</span>
      <span className="chip">{summary.active_runs || 0} active · {summary.recent_runs || 0} recent</span>
      <span className="chip" style={{ color: pressure.color }}>● {pressure.label}</span>
    </div>
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(180px,1fr))', gap: 10, marginBottom: 12 }}>
      <div className="panel" style={{ padding: 12 }}><div className="muted" style={{ fontSize: 11 }}>WORKER CAPACITY</div>
        <b style={{ fontSize: 20 }}>{summary.running || 0} active</b><div className="muted">{summary.available_slots ?? '—'} available of {summary.worker_slots ?? '—'}</div></div>
      <div className="panel" style={{ padding: 12 }}><div className="muted" style={{ fontSize: 11 }}>SHARED QUEUE</div>
        <b style={{ fontSize: 20 }}>{summary.queued || 0} jobs</b><div className="muted">{summary.waiting_users || 0} users waiting · tenant-fair</div></div>
      <div className="panel" style={{ padding: 12 }}><div className="muted" style={{ fontSize: 11 }}>UTILIZATION</div>
        <b style={{ fontSize: 20 }}>{summary.utilization_pct ?? '—'}%</b><div className="muted">{summary.worker_tier_alive ? 'Worker tier online' : 'Worker tier unavailable'}</div></div>
    </div>
    {!!stageRows.length && <div aria-label="Load by processing stage" style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
      {stageRows.map(([stage, row]) => <span className="chip" key={stage} style={{ borderColor: STAGE[stage]?.color }}>
        <b>{STAGE[stage]?.label || stage}</b>&nbsp; {row.running} active · {row.queued} waiting
      </span>)}
    </div>}
    {!!services.length && <div className="panel" aria-label="Worker services" style={{ padding: 0, marginBottom: 12, overflow: 'hidden' }}>
      <div className="muted" style={{ fontSize: 11, padding: '9px 12px 5px' }}>WORKER SERVICES</div>
      {services.map((service) => <div key={service.role} style={{ display: 'grid',
        gridTemplateColumns: 'minmax(110px,1fr) minmax(180px,2fr) minmax(130px,1fr)', gap: 12,
        alignItems: 'center', padding: '8px 12px', borderTop: '1px solid var(--border)', fontSize: 12 }}>
        <span><b>{STAGE[service.stage]?.label || service.role}</b><br />
          <span style={{ color: service.alive ? PRESSURE.healthy.color : PRESSURE.stalled.color }}>
            ● {service.alive ? 'Online' : 'Offline'}
          </span>
        </span>
        <span>{service.active} active · {service.available} available of {service.slots}</span>
        <span className="muted">{service.version || 'Version unknown'} · heartbeat {service.age_s == null ? '—' : `${Math.round(service.age_s)}s ago`}</span>
      </div>)}
    </div>}
    {concentration.pct >= 70 && concentration.total > 1 && <div role="status" style={{ padding: '9px 11px', marginBottom: 12,
      borderLeft: `4px solid ${PRESSURE.busy.color}`, background: 'var(--page)', fontSize: 12 }}>
      <b>Queue concentration:</b> one user holds {concentration.pct}% of waiting jobs. Tenant-fair scheduling gives other waiting users the next equally prioritized capacity.
    </div>}
    <div style={{ height: Math.max(330, (snapshot?.runs?.length || 1) * 125 + 45), maxHeight: 650,
      border: '1px solid var(--border)', borderRadius: 10, overflow: 'hidden', background: 'var(--page)' }}>
      {snapshot?.runs?.length ? <ReactFlow nodes={graph.nodes} edges={graph.edges} nodeTypes={nodeTypes}
        fitView minZoom={0.35} maxZoom={1.5}
        onNodeClick={(_, node) => { if (node.type === 'run') { setSelectedKey(node.id); setExpanded(false) } }}
        onNodeDoubleClick={(_, node) => { if (node.type === 'run') { setSelectedKey(node.id); setExpanded(true) } }}>
        <Background gap={18} size={1} /><MiniMap pannable zoomable /><Controls showInteractive={false} />
      </ReactFlow> : <div className="muted" style={{ padding: 28 }}>No active or recently completed processing. Start a scan and this map will populate automatically.</div>}
    </div>
    {selected && <>
      <button type="button" aria-label="Close run details" onClick={() => setSelectedKey(null)}
        style={{ position: 'fixed', inset: 0, zIndex: 79, border: 0, padding: 0,
          background: 'rgba(28,22,32,.28)', cursor: 'default' }} />
      <aside role="dialog" aria-modal="true" aria-label={`${STAGE[selected.stage]?.label || selected.stage} run details`}
      style={{ position: 'fixed', zIndex: 80, top: 0, right: 0, bottom: 0,
        width: 'clamp(360px, 38vw, 560px)', maxWidth: '100vw', overflowY: 'auto',
        overflowX: 'hidden', boxSizing: 'border-box', padding: '0 20px 24px',
        background: 'var(--card, #fff)', color: 'var(--ink, #2b2330)',
        borderLeft: `5px solid ${STAGE[selected.stage]?.color || '#6B7280'}`,
        boxShadow: '-12px 0 35px rgba(24,20,28,.22)', isolation: 'isolate' }}>
      <div style={{ position: 'sticky', top: 0, zIndex: 1, display: 'grid',
        gridTemplateColumns: 'minmax(0,1fr) auto', alignItems: 'start', gap: 12,
        margin: '0 -20px', padding: '18px 20px 14px', background: 'var(--card, #fff)',
        borderBottom: '1px solid var(--border)' }}>
        <div style={{ minWidth: 0 }}>
          <h2 style={{ margin: 0, fontSize: 18, overflowWrap: 'anywhere' }}>{STAGE[selected.stage]?.label || selected.stage} run details</h2>
          <div className="muted" style={{ fontSize: 12, marginTop: 3 }}>Live SSE updates from this run</div>
        </div>
        <button className="ghost small" aria-label="Close run details" onClick={() => setSelectedKey(null)}>Close</button>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(155px,1fr))', gap: 10, marginTop: 14, fontSize: 13 }}>
        {[['User', selected.owner], ['Source', selected.source],
          ['Progress', `${selected.completed} of ${selected.total}`],
          ['Queue', `${selected.running} active · ${selected.queued} waiting`],
          ['Status', selected.status === 'recent' ? 'Recently completed' : (selected.queue_position ? `Queue position ${selected.queue_position}` : 'Running now')],
          ['Oldest wait', age(selected.oldest_queued_at)],
          ['Job type', selected.current_job_type?.replaceAll('_', ' ') || '—'],
          ['Last activity', `${age(selected.updated_at)} ago`]].map(([label, value]) =>
            <div className="panel" key={label} style={{ minWidth: 0, padding: 10, overflowWrap: 'anywhere' }}>
              <b style={{ display: 'block', fontSize: 11, marginBottom: 3 }}>{label}</b>{value}
            </div>)}
      </div>
      {selected.current_file && <div className="panel" style={{ minWidth: 0, marginTop: 12, padding: 12 }}>
        <b>Processing now</b><br /><code style={{ whiteSpace: 'normal', overflowWrap: 'anywhere' }}>{selected.current_file}</code>
      </div>}
      {selected.current_rule_id && <div style={{ marginTop: 10 }}><b>WCAG criterion</b><br />{selected.current_rule_id}</div>}
      <button className="ghost" style={{ width: '100%', marginTop: 14 }} aria-expanded={expanded} aria-controls="live-run-trends"
        onClick={() => setExpanded((value) => !value)}>{trendToggleLabel(expanded)}</button>
      {expanded && <div id="live-run-trends" style={{ marginTop: 14 }}>
        <div style={{ marginBottom: 8 }}><b>Live run trends</b><div className="muted" style={{ fontSize: 12 }}>SSE samples · oldest to newest</div></div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: 10 }}>
          <MetricChart values={selectedHistory} field="completed" label="Completed documents" color={STAGE[selected.stage]?.color} />
          <MetricChart values={selectedHistory} field="running" label="Active workers" color="#287C45" />
          <MetricChart values={selectedHistory} field="queued" label="Queued jobs" color="#A66A16" />
        </div>
      </div>}
      </aside>
    </>}
  </section>
}
