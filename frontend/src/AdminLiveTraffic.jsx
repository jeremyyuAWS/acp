import { useEffect, useMemo, useRef, useState } from 'react'
import { Background, Controls, Handle, MarkerType, MiniMap, Position, ReactFlow } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { getAdminActivity, getWorkerCapacity, openAdminActivityStream } from './api.js'
import { ensureResizeObserver } from './resizeObserverFallback.js'
import LiveOpsDrawer from './LiveOpsDrawer.jsx'
import LiveOpsCostSummary from './LiveOpsCostSummary.jsx'
import LiveOpsAiSummary from './LiveOpsAiSummary.jsx'
import { appendSample, deriveEvents, formatDuration, mergeEvents, queueCapacityGauge,
  durableRunEvents, sampleForNode, secondsSince } from './liveOpsDrawer.js'

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

// `bezier` rather than the stepped router this replaced: one continuous curve per line, with no
// corners to round off, which is as smooth as this graph gets. `curvature` pushes the control
// points further out so the three lines fanning out of the shared queue separate before they turn
// — at the default they overlap for the first stretch and read as a single line.
const EDGE_ROUTING = { type: 'bezier', pathOptions: { curvature: 0.42 } }

// Worker cards grow with their live gauge and compute/storage line. At the narrow fitView scale
// that content can wrap to roughly 150px tall, so a 145px pitch lets adjacent borders touch (and
// at some browser zooms overlap). Keep the topology's vertical rhythm explicit and leave a real
// gutter after the tallest supported card. Active-run cards start below the whole service stack.
const WORKER_LANE_TOP = 20
const WORKER_LANE_GAP = 170
const RUN_LANE_TOP = 535

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
  const capacity = summary.worker_capacity_by_role || {}
  const load = summary.by_stage || {}
  const attribution = summary.worker_instance_attribution || {}
  return ['discovery', 'assess', 'remediate'].filter((role) => roles[role] || capacity[role]).map((role) => {
    const heartbeat = roles[role] || {}
    const measured = capacity[role]
    const stage = role === 'discovery' ? 'discover' : role
    // A role heartbeat is last-writer-wins across replicas. It can establish that an older worker
    // service is alive, but its pool_size is not fleet capacity and durable running rows are not
    // busy slots. Keep those facts visible without manufacturing a utilization ratio from them.
    const active = measured ? Number(measured.busy_slots || 0) : null
    const slots = measured ? Number(measured.worker_slots || 0) : null
    return {
      role, stage, active, slots, available: measured ? Math.max(0, slots - active) : null,
      alive: measured ? Number(measured.healthy_replicas || 0) > 0 : Boolean(heartbeat.alive),
      age_s: heartbeat.age_s, version: heartbeat.version,
      status: measured?.status || 'unavailable',
      ...(measured ? {
        jobs_in_flight: measured.jobs_in_flight,
        healthy_replicas: measured.healthy_replicas,
        stale_replicas: measured.stale_replicas,
        unattributed_running: measured.unattributed_running,
        utilization_pct: measured.utilization_pct,
        capacity_source: measured.capacity_source,
        measured_at: measured.measured_at,
        instances: measured.instances || [],
        alerts: measured.alerts || [],
        revision_distribution: measured.revision_distribution || {},
        recent_lifecycle_events: measured.recent_lifecycle_events || [],
        freshness_threshold_seconds: measured.freshness_threshold_seconds,
      } : {
        jobs_in_flight: Number(load[stage]?.running || 0),
        utilization_pct: null,
        capacity_source: heartbeat.alive ? 'legacy_role_heartbeat' : 'unavailable',
        measured_at: heartbeat.heartbeat_at || null,
        capacity_unavailable_reason: attribution.reason
          || 'Per-replica capacity is not yet reporting. Jobs in flight are available, but slot utilization cannot be calculated honestly.',
      }),
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

/**
 * RETIRED 2026-09-04, kept per the repo's retired-feature policy — no screen renders it.
 *
 * It was the old drawer's trend chart; `LiveOpsDrawer`'s trend strip replaced it with labelled
 * axes, a 15-minute window, focus/hover tooltips and deployment markers. Do NOT re-mount it as it
 * stands: `Number(...) || 0` turns an unreported measurement into a plotted zero, which is the one
 * thing the new drawer exists not to do. `liveOpsDrawer.chartModel` is the honest replacement.
 * `adminLiveTraffic.test.jsx` asserts nothing mounts it, so this comment cannot quietly go stale.
 */
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

/** RETIRED 2026-09-04 with MetricChart above: the trend strip is always visible in the redesigned
 *  drawer, so there is no show/hide toggle to label. Kept per the retired-feature policy. */
export function trendToggleLabel(expanded) {
  return expanded ? 'Hide live trends' : 'Show live trends'
}

export function capacityValue(value, suffix = '') {
  return value == null || value === '' ? 'Not reported' : `${value}${suffix}`
}

/** One Azure metric's newest one-minute sample, or "Not reported" — never a zero standing in for
 *  a metric Azure did not answer for. */
export function azureLatest(capacity, key, suffix = '') {
  const metric = capacity?.metrics?.[key]
  return metric?.available && metric.latest != null ? `${metric.latest}${suffix}` : 'Not reported'
}

export function azureBytes(capacity, key) {
  const metric = capacity?.metrics?.[key]
  if (!metric?.available || metric.latest == null) return 'Not reported'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let n = Number(metric.latest)
  let unit = 0
  while (n >= 1024 && unit < units.length - 1) { n /= 1024; unit += 1 }
  return `${Math.round(n * 10) / 10} ${units[unit]}`
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
    // The window is READ from the payload, not written here. It used to say "last 5 min" from a
    // string in this file while the actual timespan lived in routes/control.py — so widening the
    // window there would have left this label quietly describing the wrong average.
    ['LIVE UTILIZATION', capacity.metrics_available ? `${capacityValue(capacity.cpu_percent, '%')} CPU` : 'Not reported',
      capacity.metrics_available
        ? `${capacityValue(capacity.memory_percent, '%')} memory · average over ${capacityValue(capacity.metrics_window_minutes)} min`
        : metricReason],
    ['ACTIVE REVISION', capacityValue(capacity.revision_health), `${capacityValue(capacity.revision_provisioning_state)} · ${capacityValue(capacity.revision_traffic_percent, '%')} traffic`],
    ['ROLLOUT', capacityValue(capacity.draining_replicas), `${capacityValue(capacity.workload_profile_name)} profile · ${capacity.active_revision_name || 'revision not reported'}`],
    // What Azure Monitor reports beyond utilization. Each is null when Azure answered nothing for
    // it, and renders as "Not reported" rather than as a zero that would read as a healthy app
    // with no restarts and no traffic.
    ['REPLICA RESTARTS', azureLatest(capacity, 'restarts'), 'Azure metric RestartCount · cumulative'],
    ['NETWORK', `${azureBytes(capacity, 'network_in_bytes')} in`, `${azureBytes(capacity, 'network_out_bytes')} out · RxBytes / TxBytes`],
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

/**
 * TWO KINDS OF TILE, TOLD APART WITHOUT READING THEM.
 *
 * The map mixes things that persist with things that pass through, and they were rendered nearly
 * alike: a white card with a coloured border. That is what made "51 active" on a job tile beside
 * "2 slots" on a service tile read as one contradiction rather than two different measurements.
 *
 * A SCAN JOB is transient — one user's run, here for minutes. It is filled with its stage's colour
 * so it reads as a thing moving through the system, and carries a left accent bar.
 *
 * A DURABLE SERVICE is permanent infrastructure. It is backfilled with the flat surface tone, so a
 * row of services reads as the fixed pipeline the jobs travel along.
 *
 * Colour is never the only cue (WCAG 1.4.1): every tile also carries a typed label — ACTIVE JOB,
 * SERVICE, or DATA — and the map key spells the three out. The fill makes the grouping visible at
 * a glance; the label is what actually says which is which.
 */
export const TILE_KINDS = {
  job: { label: 'ACTIVE JOB', tint: 16, accent: 5, radius: 6 },
  service: { label: 'SERVICE', tint: 0, accent: 0, radius: 10 },
  data: { label: 'DATA', tint: 0, accent: 0, radius: 10 },
}

/** Which of the three a node is. Sources and outputs are where documents come from and go to —
 *  neither a job nor a service — so they are their own kind rather than being lumped in with the
 *  worker services they sit between. */
export function tileKind(kind) {
  if (kind === 'run') return 'job'
  if (kind === 'source' || kind === 'output') return 'data'
  return 'service'
}

export function tileStyle(kind, color) {
  const spec = TILE_KINDS[tileKind(kind)] || TILE_KINDS.service
  return {
    background: spec.tint
      ? `color-mix(in srgb, ${color} ${spec.tint}%, var(--panel))`
      : 'var(--panel)',
    borderLeft: spec.accent ? `${spec.accent}px solid ${color}` : undefined,
    borderRadius: spec.radius,
    label: spec.label,
  }
}

function RunNode({ data }) {
  const cfg = STAGE[data.run.stage] || { label: data.run.stage, color: '#6B7280' }
  const accent = data.workflowColor || cfg.color
  const pct = data.run.total ? Math.round((data.run.completed / data.run.total) * 100) : 0
  const statusLabel = data.run.status === 'recent' ? 'Complete'
    : data.run.status === 'failed' ? 'Failed' : `${pct}%`
  return <div title="Select for live run details; double-click to open charts"
    style={{ width: 225, padding: 12,
      ...tileStyle('run', accent),
      border: `2px solid ${cfg.color}`,
      borderLeft: `5px solid ${accent}`,
      boxShadow: `0 4px 12px color-mix(in srgb, ${accent} 18%, transparent)` }}>
    <Handle type="target" position={Position.Left} />
    <div style={{ color: cfg.color, fontSize: 9.5, fontWeight: 800, letterSpacing: '.09em',
      marginBottom: 4 }}>{TILE_KINDS.job.label}</div>
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
      <b>{cfg.label}</b><span style={{ color: data.run.status === 'failed' ? 'var(--error-fg)' : cfg.color,
        fontWeight: 700 }}>{statusLabel}</span>
    </div>
    <div className="muted" style={{ fontSize: 11, marginTop: 3 }}>{data.run.owner}</div>
    <div style={{ height: 5, background: 'var(--border)', borderRadius: 4, margin: '9px 0 7px' }}>
      <div style={{ width: `${pct}%`, height: '100%', background: cfg.color, borderRadius: 4 }} />
    </div>
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'end' }}>
      <span style={{ fontSize: 12 }}>{data.run.status === 'recent' ? `Finished ${age(data.run.updated_at)} ago`
        : data.run.status === 'failed' ? `${data.run.failed || 0} failed · updated ${age(data.run.updated_at)} ago`
          : `${data.run.completed}/${data.run.total} · ${data.run.running} active`}</span>
      <MiniTrend values={data.history} color={cfg.color} />
    </div>
    {!!data.run.queued && <div style={{ fontSize: 11, marginTop: 5, color: 'var(--muted)' }}>
      {data.run.queued} waiting{data.run.queue_position ? ` · queue position ${data.run.queue_position}` : ''}
    </div>}
    <Handle type="source" position={Position.Right} />
  </div>
}

function WorkflowNode({ data }) {
  return <div style={{ width: 225, minHeight: 112, padding: 12, borderRadius: 9,
    border: `2px solid ${data.color}`, borderLeft: `7px solid ${data.color}`,
    background: 'var(--panel)', boxShadow: '0 2px 8px rgba(24,20,28,.07)' }}>
    <div style={{ color: data.color, fontSize: 9.5, fontWeight: 800, letterSpacing: '.09em' }}>WORKFLOW</div>
    <b style={{ display: 'block', marginTop: 4, overflowWrap: 'anywhere' }}>{data.owner}</b>
    <div className="muted" style={{ fontSize: 11, marginTop: 4 }}>{data.source}</div>
    <div style={{ fontSize: 11, marginTop: 9, fontWeight: 700 }}>{data.status}</div>
    <div className="muted" style={{ fontSize: 10, marginTop: 3 }}>{data.workflowId}</div>
    <Handle type="source" position={Position.Right} />
  </div>
}

/**
 * The live bar on a map tile.
 *
 * The map answers "where is work" and the drawer answers "how much"; a tile with a fill answers
 * the second at a glance, so a saturated service is visible without opening anything. It updates
 * on every SSE snapshot because it is derived from the same node data the tile already renders.
 *
 * `fraction` is clamped to 1 and `over` is passed separately rather than letting the bar overflow:
 * more work in flight than slots is not a share of capacity (see gaugeModel), so it is drawn as a
 * full bar in the saturated tone and SAID in the label, never as a bar running past its own track.
 * A fraction of null draws no bar at all — an unmeasured value gets no fill, not an empty one that
 * reads as zero.
 */
function NodeGauge({ fraction, label, color, over = false, tone }) {
  const measured = typeof fraction === 'number' && Number.isFinite(fraction)
  const width = measured ? Math.min(1, Math.max(0, fraction)) * 100 : 0
  return <div style={{ marginTop: 6 }}>
    <div role="img" aria-label={label} style={{ height: 5, borderRadius: 3, background: 'var(--line)',
      overflow: 'hidden' }}>
      {measured && <div style={{ width: `${width}%`, height: '100%', borderRadius: 3,
        background: over ? 'var(--error-fg)' : (tone || color) }} />}
    </div>
    <div className="muted" style={{ fontSize: 10, marginTop: 2, overflowWrap: 'anywhere' }}>{label}</div>
  </div>
}

/**
 * What each tile's bar measures, or null when nothing on that tile is a ratio.
 *
 * Only two node kinds have an honest denominator: a worker service (busy slots against its own
 * slot count) and the shared queue (waiting work against the slots of the ROLE that can claim it
 * — not the fleet's total, which counts slots no such job is eligible for). A source connector
 * and the output store have no capacity to be a fraction of, so they get no bar rather than an
 * invented one.
 */
export function nodeGauge(data = {}, summary = {}) {
  if (data.kind === 'worker') {
    const service = data.service || {}
    if (service.capacity_source !== 'worker_instances') {
      return { fraction: null, label: 'Per-replica worker utilization unavailable', over: false }
    }
    const active = Number(service.active || 0)
    const slots = Number(service.slots || 0)
    if (!slots) return { fraction: null, label: 'Worker slots not reported', over: false }
    const over = active > slots
    return {
      fraction: Math.min(1, active / slots),
      over,
      label: over ? `${active} jobs against ${slots} reported slots`
        : `${active} of ${slots} slots busy (${Math.round((active / slots) * 100)}%)`,
    }
  }
  if (data.kind === 'queue') {
    // PER-ROLE, not the fleet total. A job is claimed only by workers for its own stage, so the
    // question "can this be picked up now" is answered by that stage's slots — see
    // queueCapacityGauge for the production reading that made this wrong answer visible.
    return queueCapacityGauge(summary)
  }
  if (data.kind === 'run') {
    const run = data.run || {}
    const total = Number(run.total || 0)
    if (!total) return { fraction: null, label: 'Run total not reported', over: false }
    return { fraction: Math.min(1, Number(run.completed || 0) / total), over: false,
      label: `${run.completed || 0} of ${total} documents complete` }
  }
  return null
}

function InfraNode({ data }) {
  const color = data.color || '#51606D'
  return <div title="Select for infrastructure details; double-click for telemetry"
    style={{ width: data.wide ? 205 : 175, minHeight: 68, padding: 11,
      ...tileStyle(data.kind, color),
      border: `2px solid ${color}`, boxShadow: '0 2px 8px rgba(24,20,28,.08)' }}>
    {data.inputPorts?.length
      ? data.inputPorts.map(({ id, top }) => <Handle key={id} id={id} type="target"
          position={Position.Left} style={{ top }} />)
      : data.hasInput !== false && <Handle type="target" position={Position.Left} />}
    <div style={{ color, fontSize: 9.5, fontWeight: 800, letterSpacing: '.09em',
      marginBottom: 4 }}>{tileStyle(data.kind, color).label}</div>
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 7, alignItems: 'start' }}>
      <b style={{ overflowWrap: 'anywhere' }}>{data.label}</b>
      <span style={{ color, fontSize: 11, fontWeight: 700, whiteSpace: 'nowrap' }}>{data.status}</span>
    </div>
    <div className="muted" style={{ fontSize: 11, marginTop: 4, lineHeight: 1.3, overflowWrap: 'anywhere' }}>{data.detail}</div>
    {data.gauge && <NodeGauge {...data.gauge} color={color} />}
    {data.metric && <div style={{ fontSize: 11, marginTop: 5, fontWeight: 700, overflowWrap: 'anywhere' }}>{data.metric}</div>}
    {data.outputPorts?.length
      ? data.outputPorts.map(({ id, top }) => <Handle key={id} id={id} type="source"
          position={Position.Right} style={{ top }} />)
      : data.hasOutput !== false && <Handle type="source" position={Position.Right} />}
  </div>
}

const nodeTypes = { run: RunNode, infra: InfraNode, workflow: WorkflowNode }

const WORKFLOW_COLORS = ['#246B79', '#7B4D91', '#A65A2E', '#356B3F', '#9A3F62', '#5269A8']

export function workflowColor(workflowId = '') {
  let hash = 0
  for (const char of String(workflowId)) hash = ((hash * 31) + char.charCodeAt(0)) >>> 0
  return WORKFLOW_COLORS[hash % WORKFLOW_COLORS.length]
}

// React Flow's `animated` flag renders a moving dashed stroke. At the fitView zoom those dashes
// repeatedly land between device pixels, which makes an otherwise healthy path look fuzzy. Keep
// every route solid and communicate activity with a slightly stronger, non-scaling stroke; the
// nodes already state active/online status in text, so motion is not carrying information.
export function trafficEdgeStyle(color, active = false) {
  return {
    stroke: color,
    strokeWidth: active ? 3 : 2,
    opacity: active ? 1 : 0.9,
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
        ['Service health', service.status || (service.alive ? 'Online' : 'Offline')],
        ['Worker slots', service.slots == null ? 'Not reported'
          : `${service.active || 0} busy · ${service.available || 0} available of ${service.slots}`],
        ['Healthy replicas', service.healthy_replicas ?? 'Not reported'],
        ['Stale replicas', service.stale_replicas ?? 'Not reported'],
        ['Jobs recorded in flight', service.jobs_in_flight ?? 'Not reported'],
        ['Unattributed running', service.unattributed_running ?? 'Not reported'],
        ['Capacity source', service.capacity_source || 'Not reported'],
        ['Capacity measured', service.measured_at || 'Not reported'],
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

/**
 * The detailed run facts the drawer keeps for inspection. These were the drawer's PRIMARY content
 * before the redesign; they are retained verbatim under "Operational facts" so replacing the fact
 * wall with a visualization removes nothing an operator was relying on (PRD goal: "Preserve
 * detailed operational facts for inspection").
 */
export function runFacts(run = {}, nowMs = Date.now()) {
  const wait = secondsSince(run.oldest_queued_at, nowMs)
  const updated = secondsSince(run.updated_at, nowMs)
  return [
    ['User', run.owner || 'Not reported'],
    ['Source', run.source || 'Not reported'],
    ['Progress', `${run.completed ?? 0} of ${run.total ?? 0}`],
    ['Queue', `${run.running ?? 0} active · ${run.queued ?? 0} waiting`],
    ['Status', run.status === 'recent' ? 'Recently completed'
      : (run.queue_position ? `Queue position ${run.queue_position}` : 'Running now')],
    ['Oldest wait', wait == null ? 'Not reported' : formatDuration(wait)],
    ['Job type', run.current_job_type?.replaceAll('_', ' ') || 'Not reported'],
    ['Last activity', updated == null ? 'Not reported' : `${formatDuration(updated)} ago`],
  ]
}

/**
 * One line on the map. Three things every edge needs and none of them are decoration:
 *
 * · A DIRECTION a reader can see. Work flows one way through this topology and a plain line does
 *   not say which — the arrowhead does, and it is drawn in the line's own colour so a stage's
 *   path stays followable where several converge on the same node.
 *
 * · ACTIVITY carried by more than the animation. `animated` alone fails WCAG 1.4.1's motion
 *   equivalent and disappears entirely under prefers-reduced-motion, which is exactly when a
 *   reader still needs to know which lines have work on them. A live line is thicker and more
 *   opaque, so it reads as live in a screenshot and with animation off.
 *
 * · A DESTINATION for a click. `detail` names the node whose drawer explains the work on this
 *   line, so selecting the line that is moving answers "what is that?" — the question the motion
 *   provokes. `interactionWidth` widens the hit area well past the stroke; the same drawer is
 *   reachable from either node the line joins, so a pointer is never the only way to it.
 *
 * The stroke itself comes from `trafficEdgeStyle`, so the crisp non-scaling geometry that landed
 * in #1329 survives: that change was about how a line RENDERS at any zoom, this one is about what
 * a line MEANS, and the two are independent.
 */
export function flowEdge({ id, source, target, color, active = false, detail, ...rest }) {
  return {
    id, source, target, animated: active, focusable: true, interactionWidth: 20,
    data: { detail: detail || target, active },
    style: { ...trafficEdgeStyle(color, active), cursor: 'pointer' },
    markerEnd: { type: MarkerType.ArrowClosed, color, width: 15, height: 15 },
    ...rest,
  }
}

export function buildTrafficGraph(snapshot, historyMap = new Map(), capacity = null, connection = 'connecting') {
  const runs = snapshot?.runs || []
  const services = workerServiceRows(snapshot?.summary || {})
  const serviceByStage = new Map(services.map((service) => [service.stage, service]))
  const sourceKinds = ['drive', 'sharepoint']
  const sourceLabel = { drive: 'Google Drive', sharepoint: 'SharePoint' }
  const nodes = sourceKinds.map((source, index) => {
    const mine = runs.filter((run) => run.source === source)
    // SHAREPOINT COVERAGE, when a run is actually reporting it. A 30-site walk is one long
    // "discovering" bar on this map otherwise: the file count ticks and nothing says which sites
    // are done, which are still queued, or that one is blocked on a consent that lapsed this
    // morning. Summed across concurrent runs because this map is cross-tenant — it answers "what
    // is the estate doing", not "what is my scan doing".
    //
    // Only when at least one run carries the fields. A Drive run has none, and rendering "0 of 0
    // sites" under Google Drive would be a fact about this component rather than about anything
    // an operator could act on.
    const covered = mine.filter((run) => Number.isFinite(run.sites_total))
    const sitesTotal = covered.reduce((n, r) => n + (r.sites_total || 0), 0)
    const sitesDone = covered.reduce((n, r) => n + (r.sites_done || 0), 0)
    const sitesUnread = covered.reduce((n, r) => n + (r.sites_unread || 0), 0)
    const libraries = covered.reduce((n, r) => n + (r.libraries_total || 0), 0)
    const coverage = sitesTotal
      ? `${sitesDone} of ${sitesTotal} site${sitesTotal === 1 ? '' : 's'}`
        + `${libraries ? `, ${libraries} librar${libraries === 1 ? 'y' : 'ies'}` : ''}`
        + `${sitesUnread ? ` · ${sitesUnread} not read` : ''}`
      : null
    return { id: `source:${source}`, type: 'infra', position: { x: 0, y: 70 + index * 135 },
      ariaLabel: `${sourceLabel[source]} connector, ${mine.length ? 'active' : 'ready'}.`
        + `${coverage ? ` ${coverage}.` : ''} Select for details.`,
      data: { kind: 'source', label: sourceLabel[source], status: mine.length ? 'active' : 'ready',
        detail: coverage || 'Authorized document connector', color: '#246B79', hasInput: false,
        coverage,
        active: mine.filter((run) => run.status !== 'recent').length } }
  })
  nodes.push(
    { id: 'infra:intake', type: 'infra', position: { x: 230, y: 138 },
      ariaLabel: `ACP intake and orchestration, ${connection}. Select for details.`,
      data: { kind: 'intake', label: 'ACP intake', status: connection,
      detail: 'Authentication · scope · orchestration', color: '#51404E', connection } },
    { id: 'infra:queue', type: 'infra', position: { x: 470, y: 138 },
      ariaLabel: `Shared queue, ${snapshot?.summary?.queued || 0} waiting. Select for details.`,
      data: { kind: 'queue', label: 'Shared queue',
      status: `${snapshot?.summary?.queued || 0} waiting`, detail: 'Durable · tenant-fair scheduling', color: '#A66A16',
      gauge: nodeGauge({ kind: 'queue' }, snapshot?.summary || {}),
      outputPorts: [
        { id: 'discover', top: '22%' }, { id: 'assess', top: '50%' }, { id: 'remediate', top: '78%' },
      ] } },
  )
  ;['discover', 'assess', 'remediate'].forEach((stage, index) => {
    const service = serviceByStage.get(stage) || { stage, active: 0, available: 0, slots: 0, alive: false }
    // ariaLabel sits on the NODE, not in `data` — ReactFlow reads node.ariaLabel when it renders
    // the wrapper (index.js: "aria-label": node.ariaLabel). Nested in data it is silently ignored,
    // which is how this was first written and what the announcement test caught.
    nodes.push({ id: `stage:${stage}`, type: 'infra',
      position: { x: 720, y: WORKER_LANE_TOP + index * WORKER_LANE_GAP },
      ariaLabel: `${STAGE[stage].label} workers, ${service.status || (service.alive ? 'online' : 'standby')}, `
        + (service.capacity_source === 'worker_instances'
          ? `${service.active} busy of ${service.slots} slots. `
          : `slot utilization unavailable. ${service.jobs_in_flight || 0} jobs recorded in flight. `)
        + `${service.healthy_replicas != null ? `${service.healthy_replicas} healthy replicas. ` : ''}`
        + `${service.capacity_source === 'worker_instances' && service.jobs_in_flight != null
          ? `${service.jobs_in_flight} jobs recorded in flight. ` : ''}`
        + 'Select for details.',
      data: { kind: 'worker',
      label: `${STAGE[stage].label} workers`, status: service.status || (service.alive ? 'online' : 'standby'),
      detail: service.capacity_source === 'worker_instances' ? `${service.active} / ${service.slots} slots busy`
        + `${service.healthy_replicas != null ? ` · ${service.healthy_replicas} healthy replicas` : ''}`
        + `${service.jobs_in_flight != null ? ` · ${service.jobs_in_flight} jobs recorded in flight` : ''}`
        + `${service.unattributed_running ? ` · ${service.unattributed_running} running job records are not attributed to live worker slots` : ''}`
        : `${service.jobs_in_flight || 0} jobs recorded in flight · ${service.capacity_unavailable_reason}`,
      // Named rather than "Tier:", which claimed a coverage one container app does not have.
      // The app name is what makes a figure repeated on all three stage nodes readable: it says
      // whose size this is, so a stage it does not describe is visibly not describing itself.
      metric: capacity?.configured && capacity.worker_app_name
        ? `${capacity.worker_app_name}: ${reportedWorkerSize(capacity)}`
        : reportedWorkerSize(capacity),
      color: STAGE[stage].color, service, gauge: nodeGauge({ kind: 'worker', service }) } })
  })
  nodes.push({ id: 'infra:output', type: 'infra', position: { x: 1000, y: 158 },
    ariaLabel: 'Durable outputs, protected. Select for details.',
    data: { kind: 'output', label: 'Durable outputs',
    status: 'protected', detail: 'Results · corrected copies · audit trail', color: '#287C45', hasOutput: false, wide: true,
    inputPorts: [
      { id: 'discover', top: '22%' }, { id: 'assess', top: '50%' }, { id: 'remediate', top: '78%' },
    ] } })
  const edges = [
    ...sourceKinds.map((source) => flowEdge({ id: `${source}:intake`, source: `source:${source}`,
      target: 'infra:intake', color: '#246B79',
      active: runs.some((run) => run.source === source && run.running > 0),
      detail: `source:${source}` })),
    flowEdge({ id: 'intake:queue', source: 'infra:intake', target: 'infra:queue', color: '#51404E',
      active: Boolean(snapshot?.summary?.active_runs), detail: 'infra:queue' }),
    ...['discover', 'assess', 'remediate'].flatMap((stage) => [
      flowEdge({ id: `queue:${stage}`, source: 'infra:queue', sourceHandle: stage,
        target: `stage:${stage}`, color: STAGE[stage].color,
        active: Boolean(serviceByStage.get(stage)?.active || serviceByStage.get(stage)?.jobs_in_flight),
        detail: `stage:${stage}` }),
      flowEdge({ id: `${stage}:output`, source: `stage:${stage}`, target: 'infra:output',
        targetHandle: stage, color: STAGE[stage].color,
        active: Boolean(serviceByStage.get(stage)?.active || serviceByStage.get(stage)?.jobs_in_flight),
        detail: `stage:${stage}` }),
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
    nodes.push({ id: key, type: 'run',
      position: { x: 335 + (i % 3) * 255, y: RUN_LANE_TOP + Math.floor(i / 3) * 145 },
      data: { kind: 'run', run, history: series } })
    // Both of a run's lines resolve to the RUN's own drawer, not to the stage they end at: the
    // work moving along them belongs to this run, and the stage node answers a different question
    // (that service's capacity) that its own line already reaches.
    edges.push(flowEdge({ id: `in:${key}`,
      source: sourceKinds.includes(run.source) ? `source:${run.source}` : 'infra:intake',
      target: key, color: STAGE[run.stage]?.color || '#6B7280', active: run.running > 0, detail: key }))
    edges.push(flowEdge({ id: `out:${key}`, source: key, target: `stage:${run.stage}`,
      color: STAGE[run.stage]?.color || '#6B7280', active: run.running > 0, detail: key }))
  })
  return { nodes, edges }
}

/** Keep the stable service topology and the changing run inventory in separate views. Mixing the
 * two creates an edge from every source to every run and from every run to a worker, which becomes
 * unreadable as soon as several scans overlap. The jobs view deliberately has no edges: each card
 * already names its stage, source, owner, progress and queue position, and remains selectable for
 * the full live drawer. */
export function trafficGraphForTab(graph = { nodes: [], edges: [] }, tab = 'infrastructure', filter = null) {
  if (tab === 'jobs') {
    const allRuns = graph.nodes.filter((node) => node.type === 'run')
    const matchingIds = new Set(allRuns.filter((node) =>
      (!filter?.stage || node.data?.run?.stage === filter.stage)
      && (!filter?.source || node.data?.run?.source === filter.source))
      .map((node) => node.data?.run?.scan_id))
    const runs = filter ? allRuns.filter((node) => matchingIds.has(node.data?.run?.scan_id)) : allRuns
    const byWorkflow = new Map()
    for (const node of runs) {
      const id = node.data?.run?.scan_id
      if (!byWorkflow.has(id)) byWorkflow.set(id, [])
      byWorkflow.get(id).push(node)
    }
    const ordered = [...byWorkflow.entries()].sort(([, a], [, b]) => {
      const aActive = a.some((node) => node.data.run.status !== 'recent')
      const bActive = b.some((node) => node.data.run.status !== 'recent')
      if (aActive !== bActive) return aActive ? -1 : 1
      return String(b[0]?.data.run.updated_at || '').localeCompare(String(a[0]?.data.run.updated_at || ''))
    })
    const nodes = []
    const edges = []
    const stageX = { discover: 310, assess: 580, remediate: 850, release: 1120 }
    ordered.forEach(([workflowId, workflowRuns], lane) => {
      const y = 45 + lane * 185
      const color = workflowColor(workflowId)
      const first = workflowRuns[0]?.data.run || {}
      const active = workflowRuns.filter((node) => node.data.run.status === 'active')
      const failed = workflowRuns.some((node) => node.data.run.status === 'failed')
      nodes.push({ id: `workflow:${workflowId}`, type: 'workflow', position: { x: 25, y },
        ariaLabel: `Workflow ${workflowId}, ${first.owner || 'owner not reported'}, ${active.length ? 'active' : 'recently completed'}.`,
        data: { workflowId, owner: first.owner || 'Owner not reported', source: first.source || 'Source not reported',
          status: active.length ? `${active.at(-1).data.run.stage} in progress`
            : failed ? 'Needs attention' : 'Recently completed', color } })
      const stages = workflowRuns.sort((a, b) => (stageX[a.data.run.stage] || 1390) - (stageX[b.data.run.stage] || 1390))
      stages.forEach((node, index) => {
        nodes.push({ ...node, position: { x: stageX[node.data.run.stage] || 1390, y },
          data: { ...node.data, workflowColor: color } })
        const prior = index ? stages[index - 1].id : `workflow:${workflowId}`
        const live = Number(node.data.run.running || 0) > 0 || Number(node.data.run.queued || 0) > 0
        edges.push(flowEdge({ id: `workflow-edge:${prior}:${node.id}`, source: prior, target: node.id,
          color, active: live, detail: node.id }))
      })
    })
    return { nodes, edges }
  }
  const nodes = graph.nodes.filter((node) => node.type === 'infra')
  const ids = new Set(nodes.map((node) => node.id))
  return { nodes, edges: graph.edges.filter((edge) => ids.has(edge.source) && ids.has(edge.target)) }
}

export default function AdminLiveTraffic() {
  const [snapshot, setSnapshot] = useState(null)
  const [selectedKey, setSelectedKey] = useState(null)
  const [connection, setConnection] = useState('connecting')
  const [capacity, setCapacity] = useState(null)
  const [capacityState, setCapacityState] = useState('loading')
  const [flowTab, setFlowTab] = useState('infrastructure')
  const [flowFilter, setFlowFilter] = useState(null)
  const history = useRef(new Map())
  // Per-node metric samples over the drawer's 15-minute window, and the operational events derived
  // from the differences between consecutive live snapshots. Both are session state: there is no
  // events endpoint, and Azure Monitor is not queried per node, so what the drawer can honestly
  // show is what this browser has actually observed since the tab opened.
  const trends = useRef(new Map())
  const eventLog = useRef([])
  const lastContext = useRef(null)

  // Azure arrives on the SAME stream as the job topology, on its own `azure` event, so an
  // infrastructure reading reaches the page the moment the server takes it rather than up to
  // thirty seconds later. The first GET carries it too, so a tab that has just loaded is not
  // blank while it waits for the first Azure frame.
  useEffect(() => {
    let active = true
    const takeAzure = (block) => { if (active && block) { setCapacity(block); setCapacityState('live') } }
    getAdminActivity().then((d) => {
      if (!active) return
      setSnapshot(d); setConnection('live'); takeAzure(d.azure)
    }).catch(() => { if (active) setConnection('unavailable') })
    const stream = openAdminActivityStream({
      onMessage: (d) => { if (active) { setSnapshot(d); setConnection('live') } },
      onAzure: takeAzure,
      onError: () => { if (active) setConnection('reconnecting') },
    })
    return () => { active = false; stream.close() }
  }, [])

  // The poll stays as the fallback for a backend that does not push `azure` on the stream, and as
  // a recovery path if the stream drops. It is deliberately slower than the stream's own cadence:
  // when the stream is delivering, this changes nothing, and when it is not, this is the only
  // source. Kept rather than deleted because "the SSE path works" is a claim about the server the
  // browser cannot make on its own.
  useEffect(() => {
    let active = true
    const refresh = () => getWorkerCapacity()
      .then((data) => { if (active) { setCapacity((held) => held || data); setCapacityState((s) => s === 'live' ? s : 'live') } })
      .catch(() => { if (active) setCapacityState((s) => s === 'live' ? s : 'unavailable') })
    refresh()
    const timer = window.setInterval(refresh, 60000)
    return () => { active = false; window.clearInterval(timer) }
  }, [])

  // Escape, focus trapping and focus restoration are the drawer's own (a11y.useDialog), so there
  // is no second keydown listener here to fight it.

  const graph = useMemo(() => buildTrafficGraph(snapshot, history.current, capacity, connection), [snapshot, capacity, connection])
  const visibleGraph = useMemo(() => trafficGraphForTab(graph, flowTab, flowFilter),
    [graph, flowTab, flowFilter])

  // One pass per live snapshot: sample every node for the trend strip, and diff this snapshot
  // against the previous one for the timeline. Both write into refs the same way the sparkline
  // history above already does, so the drawer reads the series the map was drawn from rather than
  // one snapshot behind it.
  const observedAt = snapshot?.generated_at || null
  useMemo(() => {
    if (!snapshot) return null
    const now = Date.now()
    for (const node of graph.nodes) {
      const sample = sampleForNode(node.data, { snapshot, capacity, at: observedAt || new Date(now).toISOString() })
      trends.current.set(node.id, appendSample(trends.current.get(node.id) || [], sample, { nowMs: now }))
    }
    const context = { snapshot, capacity, connection }
    eventLog.current = mergeEvents(eventLog.current, [
      ...durableRunEvents(snapshot),
      ...deriveEvents(lastContext.current, context, { nowIso: observedAt || new Date(now).toISOString() }),
    ])
    lastContext.current = context
    return null
  }, [graph, snapshot, capacity, connection, observedAt])

  // One capacity value for the whole drawer. Passing the last good reading to the fact tiles while
  // telling the visualizations it is unavailable would put a measured figure and "Not reported"
  // side by side in the same panel, describing the same thing.
  const liveCapacity = capacityState === 'unavailable' ? null : capacity
  const selectedNode = graph.nodes.find((node) => node.id === selectedKey)?.data
  const selected = selectedNode?.run
  const selectedFacts = selectedNode
    ? (selected ? runFacts(selected) : infrastructureDetail(selectedNode, snapshot, liveCapacity).facts)
    : []
  const selectedAccent = selected
    ? (STAGE[selected.stage]?.color || '#6B7280')
    : (selectedNode?.kind === 'worker' ? (STAGE[selectedNode.service?.stage]?.color || selectedNode.color)
      : selectedNode?.color) || 'var(--plum)'

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
    <LiveOpsCostSummary />
    <LiveOpsAiSummary />
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
    <div role="tablist" aria-label="Live Operations flow views" style={{ display: 'flex', gap: 6, marginBottom: 8 }}>
      {[['infrastructure', 'Infrastructure map'], ['jobs', `Running jobs (${summary.active_workflows ?? summary.active_runs ?? 0})`]].map(([id, label]) =>
        <button key={id} type="button" role="tab" aria-selected={flowTab === id}
          className={flowTab === id ? '' : 'ghost'}
          onClick={() => { setFlowTab(id); setFlowFilter(null); setSelectedKey(null) }}
          style={{ padding: '7px 12px', fontSize: 12 }}>{label}</button>)}
    </div>
    {flowTab === 'jobs' && flowFilter && <div role="status" className="chip" style={{ marginBottom: 8 }}>
      Showing workflows for {flowFilter.stage ? `${STAGE[flowFilter.stage]?.label || flowFilter.stage} activity` : flowFilter.source}
      <button type="button" className="ghost" onClick={() => setFlowFilter(null)} style={{ marginLeft: 8 }}>Clear filter</button>
    </div>}
    <div style={{ height: flowTab === 'infrastructure' ? 590
      : Math.max(360, 100 + visibleGraph.nodes.filter((node) => node.type === 'workflow').length * 185), maxHeight: 760,
      border: '1px solid var(--border)', borderRadius: 10, overflow: 'hidden', background: 'var(--page)' }}>
      <ReactFlow key={flowTab} nodes={visibleGraph.nodes} edges={visibleGraph.edges} nodeTypes={nodeTypes}
        defaultEdgeOptions={EDGE_ROUTING}
        fitView minZoom={0.35} maxZoom={1.5}
        onNodeClick={(_, node) => setSelectedKey(node.id)}
        onNodeDoubleClick={(_, node) => setSelectedKey(node.id)}
        onEdgeClick={(_, edge) => {
          if (flowTab === 'infrastructure' && edge.data?.active) {
            const detail = String(edge.data?.detail || '')
            setFlowFilter(detail.startsWith('stage:') ? { stage: detail.slice(6) }
              : detail.startsWith('source:') ? { source: detail.slice(7) } : null)
            setFlowTab('jobs')
            setSelectedKey(null)
          } else setSelectedKey(edge.data?.detail || edge.target)
        }}>
        <Background gap={18} size={1} /><MiniMap pannable zoomable /><Controls showInteractive={false} />
        {flowTab === 'infrastructure' && <div aria-label="Map key" style={{ position: 'absolute', zIndex: 3, right: 12, top: 12,
          display: 'flex', gap: 12, padding: '6px 9px', border: '1px solid var(--border)',
          borderRadius: 7, background: 'var(--panel)', boxShadow: '0 2px 7px rgba(24,20,28,.07)',
          color: 'var(--muted)', fontSize: 10.5 }}>
          <span><b style={{ color: 'var(--ink)' }}>SERVICE</b> · capacity</span>
          <span><b style={{ color: 'var(--ink)' }}>DATA</b> · sources and outputs</span>
        </div>}
        {flowTab === 'infrastructure' && <div className="chip" style={{ position: 'absolute', zIndex: 3, left: 12, bottom: 12 }}>
          Idle · select any tile to inspect the ready processing path
        </div>}
        {flowTab === 'jobs' && !visibleGraph.nodes.length && <div className="chip" style={{ position: 'absolute', zIndex: 3, left: 12, top: 12 }}>
          No active or recently completed workflows match this view
        </div>}
        {flowTab === 'jobs' && !!visibleGraph.nodes.length && <div className="chip" style={{ position: 'absolute', zIndex: 3, left: 12, bottom: 12 }}>
          Select a stage to inspect progress; connected cards belong to one workflow
        </div>}
      </ReactFlow>
    </div>
    {selectedNode && <LiveOpsDrawer nodeId={selectedKey} node={selectedNode} snapshot={snapshot}
      capacity={liveCapacity} connection={connection}
      samples={trends.current.get(selectedKey) || []} events={eventLog.current}
      facts={selectedFacts} accent={selectedAccent} onClose={() => setSelectedKey(null)} />}
  </section>
}
