import { useEffect, useMemo, useRef, useState } from 'react'
import { Background, Controls, Handle, MiniMap, Position, ReactFlow } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { getAdminActivity, getWorkerCapacity, openAdminActivityStream } from './api.js'
import { ensureResizeObserver } from './resizeObserverFallback.js'

ensureResizeObserver(typeof window === 'undefined' ? globalThis : window)

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

export function capacityValue(value, suffix = '') {
  return value == null || value === '' ? 'Not reported' : `${value}${suffix}`
}

function AzureCapacity({ capacity, state }) {
  if (state === 'loading' && !capacity) return <div className="panel muted" style={{ padding: 12, marginBottom: 12 }}>Loading Azure capacity…</div>
  if (state === 'unavailable') return <div className="panel" role="status" style={{ padding: 12, marginBottom: 12 }}>
    <b>Azure capacity telemetry unavailable</b><div className="muted" style={{ fontSize: 12 }}>Live job flow remains available; infrastructure measurements could not be refreshed.</div>
  </div>
  if (!capacity?.configured) return <div className="panel" style={{ padding: 12, marginBottom: 12 }}>
    <b>Azure capacity telemetry not configured</b><div className="muted" style={{ fontSize: 12 }}>Set AZURE_SUBSCRIPTION_ID and WORKER_APP_NAME to show replica size, storage, utilization, and revision health. WORKER_APP_NAME has no default: production runs three worker apps and naming one by guess would report the wrong app&rsquo;s size.</div>
  </div>
  // Distinct from "not configured" and from "no metrics yet": the app IS named, and the lookup
  // for it failed. Without this branch the panel renders its tiles full of dashes, which is what
  // let a name pointing at a retired app go unnoticed.
  if (capacity.app_unavailable) return <div className="panel" role="status" style={{ padding: 12, marginBottom: 12 }}>
    <b>Azure worker app could not be read</b>
    <div className="muted" style={{ fontSize: 12 }}>
      WORKER_APP_NAME is set to <code>{capacity.worker_app_name || '(not reported)'}</code> and the
      Container App lookup failed &mdash; the app may be renamed, deleted, or the identity may lack
      access. Replica size, storage and utilization are unavailable until it resolves; live job
      flow above is unaffected.
    </div>
  </div>
  const metricReason = capacity.metrics_available ? null : ({ permission: 'Monitoring Reader permission needed', no_data: 'Azure Monitor has not reported samples yet', error: 'Azure Monitor refresh failed' }[capacity.metrics_unavailable_reason] || 'Metrics not reported')
  const tiles = [
    ['RUNNING REPLICAS', capacityValue(capacity.current_replicas), `${capacityValue(capacity.min_replicas)} min · ${capacityValue(capacity.max_replicas)} max`],
    ['COMPUTE / REPLICA', capacityValue(capacity.cpu_cores_per_replica, ' vCPU'), `${capacityValue(capacity.memory_per_replica)} memory`],
    ['EPHEMERAL STORAGE / REPLICA', capacityValue(capacity.ephemeral_storage_per_replica), 'Temporary worker disk; corrected files use durable storage'],
    ['LIVE UTILIZATION', capacity.metrics_available ? `${capacityValue(capacity.cpu_percent, '%')} CPU` : 'Not reported', capacity.metrics_available ? `${capacityValue(capacity.memory_percent, '%')} memory · last 5 min` : metricReason],
    ['ACTIVE REVISION', capacityValue(capacity.revision_health), `${capacityValue(capacity.revision_provisioning_state)} · ${capacityValue(capacity.revision_traffic_percent, '%')} traffic`],
    ['ROLLOUT', capacityValue(capacity.draining_replicas), `${capacityValue(capacity.workload_profile_name)} profile · ${capacity.active_revision_name || 'revision not reported'}`],
  ]
  return <section className="panel" aria-label="Azure worker infrastructure" style={{ padding: 12, marginBottom: 12 }}>
    <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap', marginBottom: 9 }}>
      <div><b>Azure worker infrastructure</b><div className="muted" style={{ fontSize: 11 }}>Configured size and live Azure measurements</div></div>
      <span className="muted" style={{ fontSize: 11 }}>{capacity.measured_at ? `Measured ${age(capacity.measured_at)} ago` : 'Measurement time unavailable'}</span>
    </div>
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(190px,1fr))', gap: 8 }}>
      {tiles.map(([label, value, detail]) => <div key={label} style={{ minWidth: 0, padding: 10, border: '1px solid var(--border)', borderRadius: 9 }}>
        <div className="muted" style={{ fontSize: 10.5 }}>{label}</div>
        <b style={{ display: 'block', fontSize: 17, overflowWrap: 'anywhere' }}>{value}</b>
        <div className="muted" style={{ fontSize: 11, overflowWrap: 'anywhere' }}>{detail}</div>
      </div>)}
    </div>
  </section>
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

function InfraNode({ data }) {
  const color = data.color || '#51606D'
  return <div title="Select for infrastructure details; double-click for telemetry"
    style={{ width: data.wide ? 205 : 175, minHeight: 68, padding: 11, background: 'var(--panel)',
      border: `2px solid ${color}`, borderRadius: 10, boxShadow: '0 2px 8px rgba(24,20,28,.08)' }}>
    {data.inputPorts?.length
      ? data.inputPorts.map(({ id, top }) => <Handle key={id} id={id} type="target"
          position={Position.Left} style={{ top }} />)
      : data.hasInput !== false && <Handle type="target" position={Position.Left} />}
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 7, alignItems: 'start' }}>
      <b style={{ overflowWrap: 'anywhere' }}>{data.label}</b>
      <span style={{ color, fontSize: 11, fontWeight: 700, whiteSpace: 'nowrap' }}>{data.status}</span>
    </div>
    <div className="muted" style={{ fontSize: 11, marginTop: 4, lineHeight: 1.3, overflowWrap: 'anywhere' }}>{data.detail}</div>
    {data.metric && <div style={{ fontSize: 11, marginTop: 5, fontWeight: 700, overflowWrap: 'anywhere' }}>{data.metric}</div>}
    {data.outputPorts?.length
      ? data.outputPorts.map(({ id, top }) => <Handle key={id} id={id} type="source"
          position={Position.Right} style={{ top }} />)
      : data.hasOutput !== false && <Handle type="source" position={Position.Right} />}
  </div>
}

const nodeTypes = { run: RunNode, infra: InfraNode }

// React Flow's `animated` flag renders a moving dashed stroke. At the fitView zoom those dashes
// repeatedly land between device pixels, which makes an otherwise healthy path look fuzzy. Keep
// every route solid and communicate activity with a slightly stronger, non-scaling stroke; the
// nodes already state active/online status in text, so motion is not carrying information.
export function trafficEdgeStyle(color, active = false) {
  return {
    stroke: color,
    strokeWidth: active ? 2 : 1.35,
    opacity: active ? 0.95 : 0.72,
    vectorEffect: 'non-scaling-stroke',
    shapeRendering: 'geometricPrecision',
  }
}

// THE SCOPE OF THIS NUMBER IS NOT THE STAGE IT IS DRAWN ON. api/routes/control.py reads ONE
// container app — WORKER_APP_NAME, defaulting to `acp-worker` — so this is a tier-wide reading,
// and it is attached to every stage node. Without the qualifier, Discover, Assess and Remediate
// each display the same vCPU/RAM/disk figures as though they were that service's own allocation.
//
// The per-service numbers that ARE per-service (slots, active, available, heartbeat, version)
// come from that role's own heartbeat and are shown alongside.
// What the size figure actually describes, said in terms of the services that ARE reporting.
//
// WORKER_APP_NAME names ONE container app, and production runs three worker services of two
// different sizes (deploy/public/rightsize-production.sh: acp-discovery 1 CPU / 2Gi, acp-assess
// and acp-remediate 2 CPU / 4Gi). So a reading taken from one of them is right for itself,
// possibly right for a same-sized sibling, and wrong for the rest. An earlier version of this
// row claimed the reading covered the whole worker tier, which is false whenever the sizes
// differ — and they do.
//
// `services` comes from the role heartbeats, so the count is what is actually reporting rather
// than a hardcoded 3, and `stage` is named when the app can be matched to one of them.
export function sizeScopeNote(capacity, services = []) {
  if (!capacity?.configured) return 'Not reported'
  const app = capacity.worker_app_name
  if (!app) return 'Azure did not report which container app was measured'
  const total = services.length
  // `acp-assess` -> the assess role; `acp-discovery` -> discovery. Anything else stays unmatched.
  const matched = services.find((s) => app === `acp-${s.role}` || app.endsWith(`-${s.role}`))
  if (!total) return `Measured from ${app} only — no worker services are reporting to compare it against`
  if (matched) {
    const label = STAGE[matched.stage]?.label || matched.stage
    return total === 1
      ? `Measured from ${app} (${label}), the only reporting worker service`
      : `Measured from ${app} (${label}) only — 1 of ${total} reporting worker services; the others may be sized differently`
  }
  return `Measured from ${app}, which is not one of the ${total} reporting worker services — it may not describe any of them`
}

function reportedWorkerSize(capacity) {
  if (!capacity?.configured) return 'Size telemetry not configured'
  const cpu = capacityValue(capacity.cpu_cores_per_replica, ' vCPU')
  const memory = capacityValue(capacity.memory_per_replica)
  const storage = capacityValue(capacity.ephemeral_storage_per_replica)
  return `${cpu} · ${memory} RAM · ${storage} temporary disk`
}

export function infrastructureDetail(data, snapshot = {}, capacity = null) {
  const summary = snapshot?.summary || {}
  if (data.kind === 'worker') {
    const service = data.service || {}
    return {
      title: `${data.label} infrastructure`, subtitle: 'Live worker capacity and Azure configuration', color: data.color,
      facts: [
        ['Service health', service.alive ? 'Online' : 'Offline'],
        ['Worker slots', `${service.active || 0} active · ${service.available || 0} available of ${service.slots || 0}`],
        ['Replica size', reportedWorkerSize(capacity)],
        // Adjacent to the size deliberately: the figure above is ONE container app's, drawn on
        // every stage node, so the row that says whose it is has to sit next to it rather than
        // at the bottom of the list.
        ['Size measured from', sizeScopeNote(capacity, workerServiceRows(snapshot?.summary || {}))],
        ['Replicas', capacity?.configured ? `${capacityValue(capacity.current_replicas)} running · ${capacityValue(capacity.min_replicas)} min · ${capacityValue(capacity.max_replicas)} max` : 'Not reported'],
        ['Live utilization', capacity?.metrics_available ? `${capacityValue(capacity.cpu_percent, '%')} CPU · ${capacityValue(capacity.memory_percent, '%')} memory` : 'Not reported'],
        ['Active revision', capacity?.active_revision_name || 'Not reported'],
        ['Revision health', capacity?.configured ? `${capacityValue(capacity.revision_health)} · ${capacityValue(capacity.revision_traffic_percent, '%')} traffic` : 'Not reported'],
        ['Heartbeat', service.age_s == null ? 'Not reported' : `${Math.round(service.age_s)}s ago · ${service.version || 'version unknown'}`],
      ],
    }
  }
  const details = {
    source: { title: `${data.label} connector`, subtitle: 'Authenticated source path into ACP', color: data.color,
      facts: [['Role', 'Enumerates authorized documents without changing source files'], ['Live runs', `${data.active || 0}`], ['Connection path', data.label]] },
    intake: { title: 'ACP intake and orchestration', subtitle: 'Validates requests and routes durable work', color: data.color,
      facts: [['Active runs', `${summary.active_runs || 0}`], ['Recent runs', `${summary.recent_runs || 0}`], ['SSE connection', data.connection || 'Connecting']] },
    queue: { title: 'Shared tenant-fair queue', subtitle: 'Durable work waiting for worker capacity', color: data.color,
      facts: [['Queued jobs', `${summary.queued || 0}`], ['Users waiting', `${summary.waiting_users || 0}`], ['Scheduling', 'Tenant-fair'], ['Pressure', PRESSURE[summary.pressure]?.label || PRESSURE.healthy.label]] },
    output: { title: 'Durable outputs and audit trail', subtitle: 'Corrected copies, conformance results, and provenance', color: data.color,
      facts: [['Storage class', 'Durable application storage'], ['Source safety', 'Original source documents remain unchanged'], ['Traceability', 'Run, rule, decision, and validation evidence retained']] },
  }
  return details[data.kind] || { title: data.label, subtitle: data.detail, color: data.color, facts: [] }
}

export function buildTrafficGraph(snapshot, historyMap = new Map(), capacity = null, connection = 'connecting') {
  const runs = snapshot?.runs || []
  const services = workerServiceRows(snapshot?.summary || {})
  const serviceByStage = new Map(services.map((service) => [service.stage, service]))
  const sourceKinds = ['drive', 'sharepoint']
  const sourceLabel = { drive: 'Google Drive', sharepoint: 'SharePoint' }
  const nodes = sourceKinds.map((source, index) => ({ id: `source:${source}`, type: 'infra', position: { x: 0, y: 70 + index * 135 },
    ariaLabel: `${sourceLabel[source]} connector, ${runs.some((run) => run.source === source) ? 'active' : 'ready'}. Select for details.`,
    data: { kind: 'source', label: sourceLabel[source], status: runs.some((run) => run.source === source) ? 'active' : 'ready',
      detail: 'Authorized document connector', color: '#246B79', hasInput: false,
      active: runs.filter((run) => run.source === source && run.status !== 'recent').length } }))
  nodes.push(
    { id: 'infra:intake', type: 'infra', position: { x: 230, y: 138 },
      ariaLabel: `ACP intake and orchestration, ${connection}. Select for details.`,
      data: { kind: 'intake', label: 'ACP intake', status: connection,
      detail: 'Authentication · scope · orchestration', color: '#51404E', connection } },
    { id: 'infra:queue', type: 'infra', position: { x: 470, y: 138 },
      ariaLabel: `Shared queue, ${snapshot?.summary?.queued || 0} waiting. Select for details.`,
      data: { kind: 'queue', label: 'Shared queue',
      status: `${snapshot?.summary?.queued || 0} waiting`, detail: 'Durable · tenant-fair scheduling', color: '#A66A16',
      outputPorts: [
        { id: 'discover', top: '22%' }, { id: 'assess', top: '50%' }, { id: 'remediate', top: '78%' },
      ] } },
  )
  ;['discover', 'assess', 'remediate'].forEach((stage, index) => {
    const service = serviceByStage.get(stage) || { stage, active: 0, available: 0, slots: 0, alive: false }
    // ariaLabel sits on the NODE, not in `data` — ReactFlow reads node.ariaLabel when it renders
    // the wrapper (index.js: "aria-label": node.ariaLabel). Nested in data it is silently ignored,
    // which is how this was first written and what the announcement test caught.
    nodes.push({ id: `stage:${stage}`, type: 'infra', position: { x: 720, y: 20 + index * 145 },
      ariaLabel: `${STAGE[stage].label} workers, ${service.alive ? 'online' : 'standby'}, `
        + `${service.active} active of ${service.slots} slots. Select for details.`,
      data: { kind: 'worker',
      label: `${STAGE[stage].label} workers`, status: service.alive ? 'online' : 'standby',
      detail: `${service.active} active · ${service.available} available of ${service.slots}`,
      // Named rather than "Tier:", which claimed a coverage one container app does not have.
      // The app name is what makes a figure repeated on all three stage nodes readable: it says
      // whose size this is, so a stage it does not describe is visibly not describing itself.
      metric: capacity?.configured && capacity.worker_app_name
        ? `${capacity.worker_app_name}: ${reportedWorkerSize(capacity)}`
        : reportedWorkerSize(capacity),
      color: STAGE[stage].color, service } })
  })
  nodes.push({ id: 'infra:output', type: 'infra', position: { x: 1000, y: 158 },
    ariaLabel: 'Durable outputs, protected. Select for details.',
    data: { kind: 'output', label: 'Durable outputs',
    status: 'protected', detail: 'Results · corrected copies · audit trail', color: '#287C45', hasOutput: false, wide: true,
    inputPorts: [
      { id: 'discover', top: '22%' }, { id: 'assess', top: '50%' }, { id: 'remediate', top: '78%' },
    ] } })
  const edges = [
    ...sourceKinds.map((source) => ({ id: `${source}:intake`, source: `source:${source}`, target: 'infra:intake',
      style: trafficEdgeStyle('#246B79', runs.some((run) => run.source === source && run.status !== 'recent')) })),
    { id: 'intake:queue', source: 'infra:intake', target: 'infra:queue',
      style: trafficEdgeStyle('#51404E', Boolean(snapshot?.summary?.active_runs)) },
    ...['discover', 'assess', 'remediate'].flatMap((stage) => [
      { id: `queue:${stage}`, source: 'infra:queue', sourceHandle: stage, target: `stage:${stage}`,
        style: trafficEdgeStyle(STAGE[stage].color, Boolean(serviceByStage.get(stage)?.active)) },
      { id: `${stage}:output`, source: `stage:${stage}`, target: 'infra:output', targetHandle: stage,
        style: trafficEdgeStyle(STAGE[stage].color, Boolean(serviceByStage.get(stage)?.active)) },
    ]),
  ]
  runs.forEach((run, i) => {
    const key = `${run.scan_id}:${run.stage}`
    const series = historyMap.get(key) || []
    const sample = { at: snapshot?.generated_at || new Date().toISOString(), completed: Number(run.completed || 0),
      running: Number(run.running || 0), queued: Number(run.queued || 0) }
    const last = series.at(-1)
    if (!last || ['completed', 'running', 'queued'].some((field) => Number(last[field] || 0) !== sample[field])) series.push(sample)
    historyMap.set(key, series.slice(-30))
    nodes.push({ id: key, type: 'run', position: { x: 335 + (i % 3) * 255, y: 455 + Math.floor(i / 3) * 145 }, data: { kind: 'run', run, history: series } })
    edges.push({ id: `in:${key}`, source: sourceKinds.includes(run.source) ? `source:${run.source}` : 'infra:intake', target: key,
      style: trafficEdgeStyle(STAGE[run.stage]?.color || '#6B7280', run.running > 0) })
    edges.push({ id: `out:${key}`, source: key, target: `stage:${run.stage}`,
      style: trafficEdgeStyle(STAGE[run.stage]?.color || '#6B7280', run.running > 0) })
  })
  return { nodes, edges }
}

export default function AdminLiveTraffic() {
  const [snapshot, setSnapshot] = useState(null)
  const [selectedKey, setSelectedKey] = useState(null)
  const [expanded, setExpanded] = useState(false)
  const [connection, setConnection] = useState('connecting')
  const [capacity, setCapacity] = useState(null)
  const [capacityState, setCapacityState] = useState('loading')
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
    let active = true
    const refresh = () => getWorkerCapacity()
      .then((data) => { if (active) { setCapacity(data); setCapacityState('live') } })
      .catch(() => { if (active) setCapacityState('unavailable') })
    refresh()
    const timer = window.setInterval(refresh, 30000)
    return () => { active = false; window.clearInterval(timer) }
  }, [])

  useEffect(() => {
    if (!selectedKey) return undefined
    const onKey = (event) => { if (event.key === 'Escape') setSelectedKey(null) }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [selectedKey])

  const graph = useMemo(() => buildTrafficGraph(snapshot, history.current, capacity, connection), [snapshot, capacity, connection])
  const selectedNode = graph.nodes.find((node) => node.id === selectedKey)?.data
  const selected = selectedNode?.run
  const selectedInfrastructure = selectedNode && !selected ? infrastructureDetail(selectedNode, snapshot, capacity) : null
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
    <AzureCapacity capacity={capacity} state={capacityState} />
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
    <div style={{ height: Math.max(540, 495 + Math.ceil((snapshot?.runs?.length || 0) / 3) * 145), maxHeight: 760,
      border: '1px solid var(--border)', borderRadius: 10, overflow: 'hidden', background: 'var(--page)' }}>
      <ReactFlow nodes={graph.nodes} edges={graph.edges} nodeTypes={nodeTypes}
        defaultEdgeOptions={{ type: 'smoothstep', pathOptions: { borderRadius: 12, offset: 18 } }}
        fitView minZoom={0.35} maxZoom={1.5}
        onNodeClick={(_, node) => { setSelectedKey(node.id); setExpanded(false) }}
        onNodeDoubleClick={(_, node) => { setSelectedKey(node.id); setExpanded(true) }}>
        <Background gap={18} size={1} /><MiniMap pannable zoomable /><Controls showInteractive={false} />
        {!snapshot?.runs?.length && <div className="chip" style={{ position: 'absolute', zIndex: 3, left: 12, bottom: 12 }}>
          Idle · select any tile to inspect the ready processing path
        </div>}
      </ReactFlow>
    </div>
    {(selected || selectedInfrastructure) && <>
      <button type="button" aria-label="Close run details" onClick={() => setSelectedKey(null)}
        style={{ position: 'fixed', inset: 0, zIndex: 79, border: 0, padding: 0,
          background: 'rgba(28,22,32,.28)', cursor: 'default' }} />
      <aside role="dialog" aria-modal="true" aria-label={selected ? `${STAGE[selected.stage]?.label || selected.stage} run details` : selectedInfrastructure.title}
      style={{ position: 'fixed', zIndex: 80, top: 0, right: 0, bottom: 0,
        width: 'clamp(360px, 38vw, 560px)', maxWidth: '100vw', overflowY: 'auto',
        overflowX: 'hidden', boxSizing: 'border-box', padding: '0 20px 24px',
        background: 'var(--card, #fff)', color: 'var(--ink, #2b2330)',
        borderLeft: `5px solid ${selected ? (STAGE[selected.stage]?.color || '#6B7280') : selectedInfrastructure.color}`,
        boxShadow: '-12px 0 35px rgba(24,20,28,.22)', isolation: 'isolate' }}>
      <div style={{ position: 'sticky', top: 0, zIndex: 1, display: 'grid',
        gridTemplateColumns: 'minmax(0,1fr) auto', alignItems: 'start', gap: 12,
        margin: '0 -20px', padding: '18px 20px 14px', background: 'var(--card, #fff)',
        borderBottom: '1px solid var(--border)' }}>
        <div style={{ minWidth: 0 }}>
          <h2 style={{ margin: 0, fontSize: 18, overflowWrap: 'anywhere' }}>{selected ? `${STAGE[selected.stage]?.label || selected.stage} run details` : selectedInfrastructure.title}</h2>
          <div className="muted" style={{ fontSize: 12, marginTop: 3 }}>{selected ? 'Live SSE updates from this run' : selectedInfrastructure.subtitle}</div>
        </div>
        <button className="ghost small" aria-label="Close run details" onClick={() => setSelectedKey(null)}>Close</button>
      </div>
      {selected ? <><div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(155px,1fr))', gap: 10, marginTop: 14, fontSize: 13 }}>
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
      </div>}</> : <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(175px,1fr))', gap: 10, marginTop: 14, fontSize: 13 }}>
        {selectedInfrastructure.facts.map(([label, value]) => <div className="panel" key={label}
          style={{ minWidth: 0, padding: 11, overflowWrap: 'anywhere' }}>
          <b style={{ display: 'block', fontSize: 11, marginBottom: 4 }}>{label}</b>{value}
        </div>)}
        <div className="panel" style={{ gridColumn: '1 / -1', padding: 12 }}>
          <b>Live transparency</b><div className="muted" style={{ marginTop: 4, fontSize: 12 }}>
            This view continues updating from ACP and Azure while the drawer is open. Values marked “Not reported” are never estimated.
          </div>
        </div>
      </div>}
      </aside>
    </>}
  </section>
}
