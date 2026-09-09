import { useEffect, useRef, useState } from 'react'
import { Background, Handle, MarkerType, Position, ReactFlow } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import WaterfallCount from './WaterfallCount.jsx'
import './remediation-waterfall-graph.css'

const ORDER = ['rules', 'first', 'next', 'approval', 'verify']
const count = value => Number.isSafeInteger(value) && value >= 0

function useReducedMotion() {
  const [reduced, setReduced] = useState(() => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches || false)
  useEffect(() => {
    const query = window.matchMedia?.('(prefers-reduced-motion: reduce)')
    const update = () => setReduced(!!query?.matches)
    query?.addEventListener?.('change', update)
    return () => query?.removeEventListener?.('change', update)
  }, [])
  return reduced
}

function WaterfallNode({ data }) {
  return <>
    {data.target && <Handle type="target" position={data.target} isConnectable={false} />}
    <button type="button" className={`wf-graph-node nodrag nopan${data.selected ? ' wf-graph-node-selected' : ''}${data.active ? ' wf-graph-node-active' : ''}`}
      aria-pressed={data.selected} data-stage={data.id} onClick={() => data.onSelect?.(data.id)}
      onKeyDown={event => data.onKeyDown(event, data.id)} style={{ minHeight: data.height }}>
      <span className="wf-graph-node-role"><span>{String(data.index + 1).padStart(2, '0')}</span>{data.role}</span>
      <strong>{data.title}</strong>
      <span className="wf-graph-node-provider">{data.provider}</span>
      {data.metric && <span className="wf-graph-node-metric"><WaterfallCount value={data.value} identity={`${data.identity}:${data.id}`} paused={data.paused} /> {data.metric}</span>}
      <span className={`wf-graph-node-state${data.active ? ' wf-graph-node-working' : ''}`}>{data.active ? <><i aria-hidden="true" />{data.id === 'verify' ? 'Verification in progress' : 'Request dispatched'}</> : data.detail}</span>
    </button>
    {data.source && <Handle type="source" position={data.source} isConnectable={false} />}
  </>
}
const nodeTypes = { waterfall: WaterfallNode }

// This graph is the configured path, not evidence that every finding visits every stage.
// Only the parent's confirmed motion stage can illuminate a connection.
export function waterfallGraphModel({ stages = [], aiEnabled, selection = 'rules', motion = {}, paused = false,
  identity, reviewCount, verifiedCount, width = 1100, onSelect, onKeyDown = () => {} }) {
  const narrow = width < 850
  const columns = narrow ? 2 : 5
  const nodeWidth = Math.max(120, (width - 32 - (columns - 1) * 26) / columns)
  const aiNode = tier => {
    const stage = stages.find(item => item.tier === tier)
    const models = (stage?.models || []).filter(item => typeof item.model === 'string' && item.model.trim())
    return {
      role: tier === 1 ? 'First AI attempt' : 'Fallback · if needed',
      title: models.length ? [...new Set(models.map(item => item.model))].join(' + ') : stage?.operations === 0 ? 'Not used yet' : 'Model not recorded',
      provider: models.length ? [...new Set(models.map(item => item.provider || 'Provider not recorded'))].join(' · ') : aiEnabled === false ? 'AI disabled for this run' : 'Recorded identity unavailable',
      value: stage?.operations, metric: 'recorded operations',
      detail: aiEnabled === false ? 'Not requested by this plan' : 'AI suggestions need approval',
    }
  }
  const facts = [
    { role: 'Rules', title: 'Rule-based fixes', provider: 'No LLM call required', detail: 'Supported corrections under your plan' },
    aiNode(1), aiNode(2),
    { role: 'Your approval', title: 'Human review', provider: 'You decide what is applied', value: reviewCount, metric: 'review items', detail: 'Suggestions are not verified fixes' },
    { role: 'Verify', title: 'Check the changes', provider: 'Evidence of completion', value: verifiedCount, metric: 'verified changes', detail: 'Across all correction origins' },
  ]
  // Long recorded model names grow the rows; text is never clipped or replaced by an alias.
  const charsPerLine = Math.max(12, Math.floor((nodeWidth - 24) / 7))
  const height = Math.max(174, ...facts.map(item => 130 + Math.ceil(item.title.length / charsPerLine) * 18 + Math.ceil(item.provider.length / charsPerLine) * 14))
  const coords = narrow ? [[0, 0], [1, 0], [1, 1], [0, 1], [0, 2]] : ORDER.map((_, index) => [index, 0])
  const side = (from, to) => from[1] < to[1] ? Position.Bottom : from[0] < to[0] ? Position.Right : Position.Left
  const nodes = ORDER.map((id, index) => ({
    id, type: 'waterfall', position: { x: 16 + coords[index][0] * (nodeWidth + 26), y: 16 + coords[index][1] * (height + 36) },
    style: { width: nodeWidth }, draggable: false, selectable: false, focusable: false,
    data: { ...facts[index], id, index, identity, height, selected: selection === id, active: !paused && motion.stage === id,
      paused, onSelect, onKeyDown,
      source: index < 4 ? side(coords[index], coords[index + 1]) : null,
      target: index > 0 ? (coords[index - 1][1] < coords[index][1] ? Position.Top : coords[index - 1][0] < coords[index][0] ? Position.Left : Position.Right) : null,
    },
  }))
  const edges = ORDER.slice(1).map((target, index) => ({
    id: `${ORDER[index]}-${target}`, source: ORDER[index], target, type: 'smoothstep',
    animated: !paused && motion.stage === target,
    className: !paused && motion.stage === target ? 'wf-graph-edge-working' : '',
    markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16, color: !paused && motion.stage === target ? '#8359ab' : '#c5b8d0' },
    style: { stroke: !paused && motion.stage === target ? '#8359ab' : '#c5b8d0', strokeWidth: !paused && motion.stage === target ? 2.5 : 1.5 },
    focusable: false,
  }))
  return { nodes, edges, height: narrow ? height * 3 + 104 : height + 32 }
}

export default function RemediationWaterfallGraph({ stages, aiEnabled, selection, onSelect, motion = {}, paused = false,
  error = false, identity, reviewCount, verifiedCount }) {
  const host = useRef(null)
  const [width, setWidth] = useState(1100)
  const reduced = useReducedMotion()
  const stopped = paused || error || motion.hidden || reduced
  useEffect(() => {
    const measure = () => { const next = host.current?.clientWidth; if (next > 0) setWidth(next) }
    measure()
    const observer = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(measure) : null
    if (host.current) observer?.observe(host.current)
    return () => observer?.disconnect()
  }, [])
  const onKeyDown = (event, id) => {
    if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) return
    event.preventDefault()
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? 4 : (ORDER.indexOf(id) + (['ArrowRight', 'ArrowDown'].includes(event.key) ? 1 : -1) + 5) % 5
    onSelect?.(ORDER[next])
    host.current?.querySelector(`[data-stage="${ORDER[next]}"]`)?.focus()
  }
  const graph = waterfallGraphModel({ stages, aiEnabled, selection, onSelect, motion, paused: stopped, identity,
    reviewCount: count(reviewCount) ? reviewCount : undefined, verifiedCount: count(verifiedCount) ? verifiedCount : undefined, width, onKeyDown })
  return <section ref={host} className={`wf-graph${stopped ? ' wf-graph-stopped' : ''}`} aria-label="Remediation waterfall stages">
    <div className="wf-graph-heading"><h4>Live AI waterfall</h4><span>Select a stage to inspect its evidence</span></div>
    <div className="wf-graph-canvas" style={{ height: graph.height }}>
      <ReactFlow nodes={graph.nodes} edges={graph.edges} nodeTypes={nodeTypes}
        defaultViewport={{ x: 0, y: 0, zoom: 1 }} minZoom={1} maxZoom={1}
        nodesDraggable={false} nodesConnectable={false} nodesFocusable={false} edgesFocusable={false}
        elementsSelectable={false} panOnDrag={false} zoomOnScroll={false} zoomOnPinch={false}
        zoomOnDoubleClick={false} preventScrolling={false} proOptions={{ hideAttribution: true }}>
        <Background gap={20} size={1} color="#d9cee4" />
      </ReactFlow>
    </div>
    <p className="wf-graph-caption">The path shows available steps. Fallback runs only when needed; findings can skip AI. Moving lines mark confirmed activity, not a completed fix.</p>
  </section>
}
