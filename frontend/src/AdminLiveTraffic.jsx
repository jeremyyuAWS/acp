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

function MiniTrend({ values = [], color }) {
  const points = values.slice(-18)
  if (points.length < 2) return <span className="muted" style={{ fontSize: 11 }}>collecting activity…</span>
  const max = Math.max(...points, 1)
  const coords = points.map((v, i) => `${(i / (points.length - 1)) * 92},${25 - (v / max) * 22}`).join(' ')
  return <svg aria-label="Recent completed-item activity" viewBox="0 0 92 28" style={{ width: 92, height: 28 }}>
    <polyline points={coords} fill="none" stroke={color} strokeWidth="2" vectorEffect="non-scaling-stroke" />
  </svg>
}

function RunNode({ data }) {
  const cfg = STAGE[data.run.stage] || { label: data.run.stage, color: '#6B7280' }
  const pct = data.run.total ? Math.round((data.run.completed / data.run.total) * 100) : 0
  return <div style={{ width: 225, padding: 12, background: 'var(--panel)', border: `2px solid ${cfg.color}`,
    borderRadius: 10, boxShadow: '0 3px 10px rgba(24,20,28,.10)' }}>
    <Handle type="target" position={Position.Left} />
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
      <b>{cfg.label}</b><span style={{ color: cfg.color, fontWeight: 700 }}>{pct}%</span>
    </div>
    <div className="muted" style={{ fontSize: 11, marginTop: 3 }}>{data.run.owner}</div>
    <div style={{ height: 5, background: 'var(--border)', borderRadius: 4, margin: '9px 0 7px' }}>
      <div style={{ width: `${pct}%`, height: '100%', background: cfg.color, borderRadius: 4 }} />
    </div>
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'end' }}>
      <span style={{ fontSize: 12 }}>{data.run.completed}/{data.run.total} · {data.run.running} active</span>
      <MiniTrend values={data.history} color={cfg.color} />
    </div>
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
    if (series.at(-1) !== run.completed) series.push(run.completed)
    historyMap.set(key, series.slice(-18))
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
  const [selected, setSelected] = useState(null)
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

  const graph = useMemo(() => buildTrafficGraph(snapshot, history.current), [snapshot])

  const summary = snapshot?.summary || {}
  return <section className="panel" style={{ padding: 16, marginBottom: 20 }} aria-label="Live Azure processing traffic">
    <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', marginBottom: 10 }}>
      <div><b>Live Azure traffic</b><div className="muted" style={{ fontSize: 12 }}>All active scans and worker flow</div></div>
      <span className="chip" style={{ marginLeft: 'auto' }}>● {connection}</span>
      <span className="chip">{summary.active_runs || 0} runs</span>
      <span className="chip">{summary.running || 0} active jobs</span>
      <span className="chip">{summary.worker_slots ?? '—'} worker slots</span>
    </div>
    <div style={{ height: Math.max(330, (snapshot?.runs?.length || 1) * 125 + 45), maxHeight: 650,
      border: '1px solid var(--border)', borderRadius: 10, overflow: 'hidden', background: 'var(--page)' }}>
      {snapshot?.runs?.length ? <ReactFlow nodes={graph.nodes} edges={graph.edges} nodeTypes={nodeTypes}
        fitView minZoom={0.35} maxZoom={1.5} onNodeClick={(_, node) => node.type === 'run' && setSelected(node.data.run)}>
        <Background gap={18} size={1} /><MiniMap pannable zoomable /><Controls showInteractive={false} />
      </ReactFlow> : <div className="muted" style={{ padding: 28 }}>No scans are actively processing. This map will populate automatically.</div>}
    </div>
    {selected && <div className="panel" style={{ marginTop: 12, padding: 14, borderLeft: `4px solid ${STAGE[selected.stage]?.color || '#6B7280'}` }}>
      <div style={{ display: 'flex', justifyContent: 'space-between' }}><b>{STAGE[selected.stage]?.label || selected.stage} run details</b>
        <button className="ghost small" onClick={() => setSelected(null)}>Close</button></div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(160px,1fr))', gap: 8, marginTop: 8, fontSize: 13 }}>
        <span><b>User</b><br />{selected.owner}</span><span><b>Source</b><br />{selected.source}</span>
        <span><b>Progress</b><br />{selected.completed} of {selected.total}</span><span><b>Queue</b><br />{selected.running} active · {selected.queued} waiting</span>
      </div>
      {selected.current_file && <div style={{ marginTop: 10 }}><b>Processing now</b><br /><code>{selected.current_file}</code></div>}
    </div>}
  </section>
}
