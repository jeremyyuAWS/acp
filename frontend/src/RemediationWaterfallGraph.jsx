import { Component, useEffect, useRef, useState } from 'react'
import { Background, Handle, MarkerType, Position, ReactFlow } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { recordedRunGraphGroups } from './remediationRunGraphPresentation.js'
import WaterfallCount from './WaterfallCount.jsx'
import { waterfallStageStatus } from './WaterfallRunNotice.jsx'
import './remediation-waterfall-graph.css'

const ORDER = ['rules', 'first', 'next', 'approval', 'verify']
// The same restrained workflow colors used by LiveOps, paired with textual roles.
const COLORS = { rules: '#246B79', first: '#5269A8', next: '#7B4D91', next2: '#6D4C86', approval: '#A65A2E', verify: '#356B3F', review: '#9A3F62', unknown: '#51606D' }
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

function StageButton({ data }) {
  return <button type="button" className={`wf-graph-node nodrag nopan${data.selected ? ' wf-graph-node-selected' : ''}${data.active ? ' wf-graph-node-active' : ''}`}
      aria-pressed={data.selected} data-stage={data.stage} data-node-id={data.id} onClick={() => data.onSelect?.(data.id, { tier: data.tier, model: data.model, provider: data.provider, stage: data.stage, stepId: data.stepId, attemptIds: data.attemptIds, identityKind: data.identityKind, purpose: data.purpose, detail: data.explanation || data.detail })}
      onKeyDown={event => data.onKeyDown(event, data.id)} style={{ minHeight: data.height, '--stage-color': COLORS[data.stage] }}>
      <span className="wf-graph-node-role"><span>{String(data.groupIndex + 1).padStart(2, '0')}</span>{data.role}</span>
      <strong>{data.title}</strong>
      <span className="wf-graph-node-provider">{data.identityKind === 'configured' ? 'Configured · ' : ''}{data.provider || 'Provider not recorded'}</span>
      {data.metric && <span className="wf-graph-node-metric">{data.tier && !count(data.value) ? 'Activity count unavailable' : <><WaterfallCount value={data.value} identity={`${data.identity}:${data.id}`} paused={data.paused} /> {data.metric}</>}</span>}
      <span className={`wf-graph-node-state${data.active ? ' wf-graph-node-working' : ''}`}>{data.active ? <><i aria-hidden="true" />{data.id === 'verify' ? 'Verification in progress' : 'Request dispatched'}</> : data.detail}</span>
    </button>
}

function WaterfallNode({ data }) {
  return <>
    {data.target && <Handle type="target" position={data.target} isConnectable={false} />}
    <StageButton data={data} />
    {data.source && <Handle type="source" position={data.source} isConnectable={false} />}
  </>
}
const nodeTypes = { waterfall: WaterfallNode }
const CALM_STATES = ['processing_complete', 'completed', 'failed', 'cancelled', 'stopped', 'paused', 'stalled']
export function waterfallRunLabel(snapshot = {}) {
  return ({ processing_complete: 'Completed', completed: 'Completed', failed: 'Failed', cancelled: 'Stopped', stopped: 'Stopped', paused: 'Paused', stalled: 'Stalled' })[snapshot.state]
    || (snapshot.terminal ? 'Finished' : snapshot.state === 'running' ? 'Live' : 'Recorded activity')
}
class GraphBoundary extends Component {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  componentDidCatch() { this.props.onFailure() }
  render() { return this.state.failed ? null : this.props.children }
}

// This graph is the configured path, not evidence that every finding visits every stage.
// Only the parent's confirmed motion stage can illuminate a connection.
export function waterfallGraphModel({ stages = [], aiEnabled, selection = 'rules', motion = {}, paused = false,
  runGraph, identity, reviewCount, verifiedCount, snapshot = {}, viewAvailable, reducedMotion = false, width = 1100, onSelect, onKeyDown = () => {} }) {
  paused = paused || snapshot.terminal || CALM_STATES.includes(snapshot.state)
  const aiNodes = tier => {
    const stage = stages.find(item => item.tier === tier)
    const models = (stage?.models || []).filter(item => typeof item.model === 'string' && item.model.trim())
    const key = tier === 1 ? 'first' : 'next'
    const common = {
      stage: key, tier,
      role: tier === 1 ? 'Initial AI' : 'Fallback / review · if needed',
      detail: waterfallStageStatus(stage, { aiEnabled, terminal: snapshot.terminal, unavailable: viewAvailable === false }),
    }
    if (!models.length) return [{ ...common, id: key,
      title: stage?.operations === 0 ? (snapshot.terminal ? 'Not used' : 'Not used yet') : 'Model not recorded',
      provider: aiEnabled === false ? 'AI disabled for this run' : 'Recorded identity unavailable',
      value: stage?.operations, metric: 'recorded operations',
    }]
    return models.map(model => ({ ...common,
      id: `${key}:${encodeURIComponent(model.provider || '')}:${encodeURIComponent(model.model)}`,
      title: model.model, model: model.model, provider: model.provider || 'Provider not recorded',
      value: models.length === 1 ? stage?.operations : model.recorded_attempts,
      metric: models.length === 1 ? 'recorded operations' : 'recorded attempts',
      // A tier total cannot identify which of several models is currently dispatched.
      detail: models.length === 1 ? common.detail : 'Same tier · sequence unavailable',
      canAnimate: models.length === 1,
    }))
  }
  const recorded = recordedRunGraphGroups(runGraph)
  // Older runs can contain a draft record without a saved three-position chain.
  // Keep the second fallback visible so the graph never makes the configured
  // capability look like it ends after the first recorded model. A saved,
  // linked fallback_2 replaces this placeholder automatically.
  const recordedWithFallback = recorded && aiEnabled !== false
    && !recorded.some(group => group.some(fact => fact.stepId === 'fallback_2'))
    ? [...recorded, [{ id: 'configured:fallback_2:placeholder', stage: 'next2', role: 'Fallback 2',
        title: 'Second fallback', provider: 'Available for supported text findings',
        detail: 'Not configured for this saved run · enable it in the remediation plan',
        identityKind: 'configured', stepId: 'fallback_2', attemptIds: [], canAnimate: false, in_flight: false }]]
    : recorded
  const groups = [
    [{ id: 'rules', stage: 'rules', role: 'Rules', title: 'Rule-based fixes', provider: 'No LLM call required', detail: 'Supported corrections under your plan' }],
    ...(recordedWithFallback || [aiNodes(1), aiNodes(2)]),
    [{ id: 'approval', stage: 'approval', role: 'Your approval', title: 'Human review', provider: 'You decide what is applied', value: reviewCount, metric: 'review items', detail: 'Suggestions are not verified fixes' }],
    [{ id: 'verify', stage: 'verify', role: 'Verify', title: 'Check the changes', provider: 'Evidence of completion', value: verifiedCount, metric: 'verified changes', detail: 'Across all correction origins' }],
  ]
  const narrow = width < 850
  const columns = width < 420 ? 1 : narrow ? 2 : groups.length
  const nodeWidth = Math.max(1, (width - 32 - (columns - 1) * 26) / columns)
  const facts = groups.flatMap((group, groupIndex) => group.map(fact => ({ ...fact, groupIndex })))
  // Long recorded model names grow the rows; text is never clipped or replaced by an alias.
  const lines = (text, averageWidth, inset = 30) => {
    const capacity = Math.max(8, Math.floor((nodeWidth - inset) / averageWidth))
    let rows = 1, used = 0
    for (const token of String(text || '').split(/(?<=[\s-])/u)) {
      const length = token.length
      if (used && used + length > capacity) { rows += 1; used = 0 }
      const pieces = Math.max(1, Math.ceil(length / capacity))
      rows += pieces - 1
      used += length - (pieces - 1) * capacity
    }
    return rows
  }
  // Account for word/hyphen wrapping, status pills and the configured-identity prefix.
  // Seven readable columns must not clip the last line of a long model name.
  const height = Math.max(174, ...facts.map(item => 30 + (item.metric ? 32 : 24)
    + lines(item.role, 5.8) * 13 + lines(item.title, 8.4) * 19
    + lines(`${item.identityKind === 'configured' ? 'Configured · ' : ''}${item.provider || 'Provider not recorded'}`, 5.8) * 15
    + (item.metric ? 28 : 0) + lines(item.detail, 5.5, 44) * 15 + 10))
  const coords = narrow ? facts.map((_, index) => {
    const row = Math.floor(index / columns)
    return [row % 2 ? columns - 1 - index % columns : index % columns, row]
  }) : groups.flatMap((group, column) => group.map((_, row) => [column, row]))
  const nodes = facts.map((fact, index) => ({
    id: fact.id, type: 'waterfall', position: { x: 16 + coords[index][0] * (nodeWidth + 26), y: 16 + coords[index][1] * (height + 36) },
    initialWidth: nodeWidth, initialHeight: height,
    // Supplying known handle geometry keeps connectors present even if a browser drops
    // node ResizeObserver deliveries. Native measurements replace these when available.
    handles: [
      ...(fact.stage === 'rules' ? [] : [{ type: 'target', position: narrow ? Position.Top : Position.Left, x: narrow ? nodeWidth / 2 - 2.5 : -2.5, y: narrow ? -2.5 : height / 2 - 2.5, width: 5, height: 5 }]),
      ...(fact.stage === 'verify' ? [] : [{ type: 'source', position: narrow ? Position.Bottom : Position.Right, x: narrow ? nodeWidth / 2 - 2.5 : nodeWidth - 2.5, y: narrow ? height - 2.5 : height / 2 - 2.5, width: 5, height: 5 }]),
    ],
    style: { width: nodeWidth }, draggable: false, selectable: false, focusable: false,
    data: { ...fact, index, identity, height, selected: selection === fact.id,
      active: !paused && fact.canAnimate !== false && motion.stage === fact.stage,
      paused: paused || reducedMotion, onSelect, onKeyDown,
      source: fact.stage === 'verify' ? null : narrow ? Position.Bottom : Position.Right,
      target: fact.stage === 'rules' ? null : narrow ? Position.Top : Position.Left,
    },
  }))
  // Models recorded within one tier are alternatives, not an invented fallback chain.
  const edges = groups.slice(1).flatMap((targets, index) => groups[index].flatMap(source => targets.map(target => {
    const active = !paused && !reducedMotion && target.canAnimate !== false && motion.stage === target.stage
    return {
      id: `${source.id}-${target.id}`, source: source.id, target: target.id, type: 'default',
      animated: active, className: active ? 'wf-graph-edge-working' : '',
      markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16, color: COLORS[target.stage] },
      style: { stroke: COLORS[target.stage], strokeWidth: active ? 2.5 : 1.7, opacity: active ? 1 : 0.75 },
      focusable: false,
    }
  })))
  const rowCount = Math.max(...coords.map(coord => coord[1])) + 1
  return { nodes, edges, height: height * rowCount + (rowCount - 1) * 36 + 32 }

}

export default function RemediationWaterfallGraph({ stages, aiEnabled, selection, onSelect, motion = {}, paused = false,
  runGraph, error = false, identity, reviewCount, verifiedCount, snapshot = {}, viewAvailable }) {
  const host = useRef(null)
  const flow = useRef(null)
  const expectedNodes = useRef(5)
  const [width, setWidth] = useState(1100)
  const reduced = useReducedMotion()
  const [generation, setGeneration] = useState(0)
  const [fallback, setFallback] = useState(false)
  const stopped = paused || error || motion.hidden || snapshot.terminal || CALM_STATES.includes(snapshot.state)
  useEffect(() => { setFallback(false); setGeneration(value => value + 1) }, [identity])
  useEffect(() => {
    let wasVisible = false
    let frame = null
    const measure = () => {
      const next = host.current?.clientWidth || 0
      if (next > 0) {
        setWidth(next)
        // A fresh flow store after reveal discards zero-size measurements from hidden panels.
        if (!wasVisible) setGeneration(value => value + 1)
      }
      wasVisible = next > 0
    }
    const schedule = () => { cancelAnimationFrame(frame); frame = requestAnimationFrame(measure) }
    measure()
    const observer = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(schedule) : null
    if (host.current) observer?.observe(host.current)
    const visibility = new MutationObserver(schedule)
    for (let ancestor = host.current?.parentElement; ancestor; ancestor = ancestor.parentElement) {
      visibility.observe(ancestor, { attributes: true, attributeFilter: ['hidden', 'style', 'class'] })
    }
    window.addEventListener('resize', schedule)
    document.addEventListener('visibilitychange', schedule)
    return () => {
      cancelAnimationFrame(frame)
      observer?.disconnect(); visibility.disconnect()
      window.removeEventListener('resize', schedule)
      document.removeEventListener('visibilitychange', schedule)
    }
  }, [])
  useEffect(() => {
    if (fallback) return undefined
    // Check the rendered buttons, not the configured node array. A populated store can still
    // leave a dotted-only canvas when node measurement or third-party styles fail.
    const timer = setInterval(() => {
      const canvas = host.current?.querySelector('.wf-graph-canvas')
      if (!canvas || !canvas.getBoundingClientRect().width || document.hidden) return
      const bounds = canvas.getBoundingClientRect()
      const nodes = [...canvas.querySelectorAll('[data-stage]')]
      const visible = nodes.length === expectedNodes.current && nodes.every(node => {
        const rect = node.getBoundingClientRect()
        for (let ancestor = node; ancestor && ancestor !== canvas; ancestor = ancestor.parentElement) {
          const style = getComputedStyle(ancestor)
          if (style.visibility !== 'visible' || style.opacity === '0' || style.display === 'none') return false
        }
        return rect.width > 0 && rect.height > 0
      })
      const inView = nodes.some(node => { const r = node.getBoundingClientRect(); return r.right > bounds.left && r.left < bounds.right && r.bottom > bounds.top && r.top < bounds.bottom })
      if (!visible || !inView) setFallback(true)
    }, 1000)
    return () => clearInterval(timer)
  }, [fallback, generation])
  const onKeyDown = (event, id) => {
    if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) return
    event.preventDefault()
    const order = graph.nodes.map(node => node.id)
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? order.length - 1 : (order.indexOf(id) + (['ArrowRight', 'ArrowDown'].includes(event.key) ? 1 : -1) + order.length) % order.length
    // Navigation must not invoke the parent's drawer-opening action. Native Enter/Space
    // activates the focused button when the reader chooses to inspect it.
    host.current?.querySelectorAll('[data-stage]')[next]?.focus()
  }
  const graph = waterfallGraphModel({ stages, runGraph, aiEnabled, snapshot, viewAvailable, selection, onSelect, motion, paused: stopped, reducedMotion: reduced, identity,
    reviewCount: count(reviewCount) ? reviewCount : undefined, verifiedCount: count(verifiedCount) ? verifiedCount : undefined, width, onKeyDown })
  expectedNodes.current = graph.nodes.length
  return <section ref={host} className={`wf-graph${stopped || reduced ? ' wf-graph-stopped' : ''}`} aria-label="Remediation waterfall stages">
    <div className="wf-graph-heading"><h4>AI waterfall <span className="wf-graph-run-status">{waterfallRunLabel(snapshot)}</span></h4><span>Select a stage to explore</span></div>
    {fallback ? <div className="wf-graph-fallback">
      <p role="status">The diagram could not be displayed. Your saved stages are available below.</p>
      <button type="button" className="ghost" onClick={() => { setGeneration(value => value + 1); setFallback(false) }}>Retry diagram</button>
      <ol aria-label="Saved run stages">{graph.nodes.map(node => <li key={node.id}><StageButton data={node.data} /></li>)}</ol>
    </div> : <GraphBoundary key={`${identity}:${generation}`} onFailure={() => setFallback(true)}>
    <div className="wf-graph-canvas" style={{ height: graph.height }}>
      <ReactFlow nodes={graph.nodes} edges={graph.edges} nodeTypes={nodeTypes}
        defaultViewport={{ x: 0, y: 0, zoom: 1 }} minZoom={0.5} maxZoom={1.25} onInit={instance => { flow.current = instance }}
        nodesDraggable={false} nodesConnectable={false} nodesFocusable={false} edgesFocusable={false}
        panActivationKeyCode={null} selectionKeyCode={null} zoomActivationKeyCode={null}
        elementsSelectable={false} panOnDrag={false} zoomOnScroll={false} zoomOnPinch={false}
        zoomOnDoubleClick={false} preventScrolling={false} proOptions={{ hideAttribution: true }}>
        <Background gap={20} size={1} color="#d9cee4" />
      </ReactFlow>
    </div>
    <div className="wf-graph-controls" aria-label="Diagram controls"><button type="button" aria-label="Zoom in" onClick={() => flow.current?.zoomIn()}>+</button><button type="button" aria-label="Zoom out" onClick={() => flow.current?.zoomOut()}>−</button><button type="button" onClick={() => flow.current?.setViewport({ x: 0, y: 0, zoom: 1 })}>Reset view</button></div>
    </GraphBoundary>}
    <p className="wf-graph-caption">{viewAvailable === false ? 'Activity history unavailable for this run. Select a stage for the evidence that remains.' : 'Available paths: rules → AI when needed → approval → verification. Fallback is conditional.'} {stopped ? 'Recorded results remain available.' : 'Motion marks confirmed activity.'}</p>
  </section>
}
