import { describe, expect, it } from 'vitest'
import { readFileSync, readdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { TILE_KINDS, azureBytes, azureLatest, buildTrafficGraph, capacityValue, flowEdge, infrastructureDetail, nodeGauge, queueConcentration, sizeScopeNote, tileKind, tileStyle, trafficEdgeStyle, trafficGraphForTab, trendToggleLabel, workerServiceRows, workflowColor } from './AdminLiveTraffic.jsx'

const here = dirname(fileURLToPath(import.meta.url))
const source = readFileSync(join(here, 'AdminLiveTraffic.jsx'), 'utf8')
// The drawer moved to its own module in the 2026-09-04 redesign; these assertions follow the
// markup they were written to protect rather than the file it used to live in.
const drawer = readFileSync(join(here, 'LiveOpsDrawer.jsx'), 'utf8')
const a11y = readFileSync(join(here, 'a11y.js'), 'utf8')

const run = {
  scan_id: 's1', owner: 'operator@example.org', source: 'drive', stage: 'assess',
  completed: 8, total: 20, running: 2, queued: 10, current_file: 'Report.docx',
}

describe('Admin live traffic graph', () => {
  it('keeps the complete processing topology visible while idle', () => {
    const graph = buildTrafficGraph({ runs: [], summary: {} })
    expect(graph.nodes.map((node) => node.id)).toEqual([
      'source:drive', 'source:sharepoint', 'infra:intake', 'infra:queue',
      'stage:discover', 'stage:assess', 'stage:remediate', 'infra:output',
    ])
    expect(graph.edges).toHaveLength(9)
    expect(graph.nodes.every((node) => node.type === 'infra')).toBe(true)
  })

  it('carries unique replica rows from the measured service into its drawer model', () => {
    const instances = [{ replica_id: 'assess-r1', process_count: 2 }]
    const [assess] = workerServiceRows({
      worker_capacity_by_role: { assess: { healthy_replicas: 1, worker_slots: 4,
        busy_slots: 3, instances } },
    })
    expect(assess.instances).toEqual(instances)
  })

  it('connects each live run to its worker stage within the persistent topology', () => {
    const graph = buildTrafficGraph({ runs: [run] })
    expect(graph.nodes.map((node) => node.id)).toContain('s1:assess')
    expect(graph.edges.find((edge) => edge.id === 'out:s1:assess').style.strokeWidth).toBe(3)
    expect(graph.nodes.find((node) => node.id === 's1:assess').data.run.current_file).toBe('Report.docx')
  })

  it('separates the stable infrastructure map from the running-job board', () => {
    const recent = { ...run, scan_id: 'done', status: 'recent', completed: 20, running: 0, queued: 0 }
    const graph = buildTrafficGraph({ runs: [run, recent], summary: { active_runs: 1 } })
    const infrastructure = trafficGraphForTab(graph, 'infrastructure')
    const jobs = trafficGraphForTab(graph, 'jobs')

    expect(infrastructure.nodes.every((node) => node.type === 'infra')).toBe(true)
    expect(infrastructure.edges.every((edge) =>
      infrastructure.nodes.some((node) => node.id === edge.source)
      && infrastructure.nodes.some((node) => node.id === edge.target))).toBe(true)
    expect(jobs.nodes.map((node) => node.id)).toEqual([
      'workflow:s1', 's1:assess', 'workflow:done', 'done:assess',
    ])
    expect(jobs.edges).toHaveLength(2)
    expect(jobs.nodes[0].position).toEqual({ x: 25, y: 45 })
  })

  it('exposes named tabs for infrastructure and running jobs', () => {
    expect(source).toContain('aria-label="Live Operations flow views"')
    expect(source).toContain("['infrastructure', 'Infrastructure map']")
    expect(source).toContain("['jobs', `Running jobs (${summary.active_workflows ?? summary.active_runs ?? 0})`]")
  })

  it('visually and verbally separates active jobs from worker services', () => {
    // Same subject as when this landed; asserted through tileStyle rather than through the literal
    // strings it used to inline, so the separation can be strengthened without the test reading as
    // a regression. The fill went from 8% to 16% with a left accent bar, because at 8% a job tile
    // and a service tile still read as the same white card on a real screen.
    expect(TILE_KINDS.job.label).toBe('ACTIVE JOB')
    expect(TILE_KINDS.service.label).toBe('SERVICE')
    expect(tileStyle('run', '#4C78C2').background).toMatch(/^color-mix\(in srgb, #4C78C2 \d+%/)
    expect(tileStyle('worker', '#4C78C2').background).toBe('var(--panel)')
    expect(TILE_KINDS.job.radius).toBe(6)
    expect(TILE_KINDS.service.radius).toBeGreaterThan(TILE_KINDS.job.radius)
    expect(source).toContain('SERVICE</b> · capacity')
    expect(source).toContain('Running jobs (${summary.active_workflows ?? summary.active_runs ?? 0})')
    expect(source).toContain('DATA</b> · sources and outputs')
    expect(source).toContain('aria-label="Map key"')
  })

  it('assigns a stable workflow accent and keeps simultaneous lanes separate', () => {
    expect(workflowColor('scan-one')).toBe(workflowColor('scan-one'))
    const graph = buildTrafficGraph({ generated_at: '2026-09-05T10:00:00Z', summary: {}, runs: [
      { scan_id: 'one', stage: 'discover', owner: 'a', source: 'drive', status: 'recent', completed: 1, total: 1 },
      { scan_id: 'one', stage: 'assess', owner: 'a', source: 'drive', status: 'active', running: 1, completed: 0, total: 1 },
      { scan_id: 'two', stage: 'discover', owner: 'b', source: 'sharepoint', status: 'active', running: 1, completed: 0, total: 1 },
    ] })
    const jobs = trafficGraphForTab(graph, 'jobs')
    const lanes = jobs.nodes.filter((node) => node.type === 'workflow')
    expect(lanes).toHaveLength(2)
    expect(lanes[1].position.y - lanes[0].position.y).toBe(185)
    expect(jobs.edges).toHaveLength(3)
    expect(jobs.nodes.find((node) => node.id === 'one:discover').position.x)
      .toBeLessThan(jobs.nodes.find((node) => node.id === 'one:assess').position.x)
  })

  it('filters whole workflows from an infrastructure stage', () => {
    const graph = buildTrafficGraph({ summary: {}, runs: [
      { scan_id: 'one', stage: 'discover', owner: 'a', source: 'drive', status: 'recent' },
      { scan_id: 'one', stage: 'assess', owner: 'a', source: 'drive', status: 'active' },
      { scan_id: 'two', stage: 'discover', owner: 'b', source: 'drive', status: 'active' },
    ] })
    const jobs = trafficGraphForTab(graph, 'jobs', { stage: 'assess' })
    expect(jobs.nodes.some((node) => node.id === 'one:discover')).toBe(true)
    expect(jobs.nodes.some((node) => node.id === 'one:assess')).toBe(true)
    expect(jobs.nodes.some((node) => node.id === 'two:discover')).toBe(false)
  })

  it('uses crisp non-scaling paths at every zoom', () => {
    // #1329's subject, kept: a line's GEOMETRY should not blur or thicken as the map scales.
    //
    // Its blanket "no animation anywhere" assertion is deliberately gone. That PR removed the
    // dashes as fuzzy; the owner then asked for movement on the lines carrying work, so the two
    // requirements are reconciled rather than one overriding the other — the stroke stays crisp
    // and non-scaling, and only an ACTIVE line moves. `.react-flow__edge.animated` is stopped
    // outright under prefers-reduced-motion (styles.css), and activity is also carried by weight
    // and opacity, so nothing depends on the motion alone.
    expect(trafficEdgeStyle('#123456', true)).toMatchObject({
      stroke: '#123456', strokeWidth: 3, opacity: 1,
      vectorEffect: 'non-scaling-stroke', shapeRendering: 'geometricPrecision',
    })
    const graph = buildTrafficGraph({ runs: [run], summary: { active_runs: 1 } })
    expect(graph.edges.every((edge) => edge.style.vectorEffect === 'non-scaling-stroke')).toBe(true)
    expect(graph.edges.every((edge) => edge.style.shapeRendering === 'geometricPrecision')).toBe(true)
    // Idle lines still do not move.
    expect(buildTrafficGraph({ runs: [], summary: {} }).edges.every((edge) => !edge.animated)).toBe(true)
  })

  it('builds a bounded sparkline history from successive SSE snapshots', () => {
    const history = new Map()
    for (let completed = 0; completed < 25; completed += 1) {
      buildTrafficGraph({ runs: [{ ...run, completed }] }, history)
    }
    expect(history.get('s1:assess')).toHaveLength(25)
    expect(history.get('s1:assess').at(-1)).toMatchObject({ completed: 24, running: 2, queued: 10 })
  })

  it('gives every input method a clear way to reveal live trends', () => {
    expect(trendToggleLabel(false)).toBe('Show live trends')
    expect(trendToggleLabel(true)).toBe('Hide live trends')
  })

  it('opens run tiles in a non-overlapping right drawer with single and double-click detail', () => {
    expect(source).toMatch(/onNodeClick=.*setSelectedKey/)
    expect(source).toMatch(/onNodeDoubleClick=.*setSelectedKey/)
    expect(drawer).toMatch(/<aside role="dialog" aria-modal="true"/)
    expect(drawer).toContain("background: 'var(--card, #fff)'")
    expect(drawer).toContain("width: 'clamp(360px, 38vw, 560px)'")
    expect(drawer).toMatch(/position: 'sticky', top: 0/)
    expect(drawer).toMatch(/rgba\(28,22,32,.28\)/)
    expect(drawer).toMatch(/overflowWrap: 'anywhere'/)
    // Escape now comes with focus trapping and focus restoration, from the shared dialog hook —
    // and AdminLiveTraffic no longer keeps a second listener that would double-handle it.
    expect(drawer).toContain('useDialog(panelRef, onClose)')
    expect(a11y).toContain("e.key === 'Escape'")
    expect(source).not.toContain("event.key === 'Escape'")
  })

  it('identifies when one user dominates the shared waiting queue', () => {
    expect(queueConcentration([
      { owner: 'a@example.org', queued: 8 },
      { owner: 'b@example.org', queued: 2 },
    ])).toEqual({ owner: 'a@example.org', count: 8, total: 10, pct: 80 })
  })

  it('keeps recently completed stages in the graph without animating them', () => {
    const graph = buildTrafficGraph({ runs: [{ ...run, status: 'recent', completed: 20, running: 0, queued: 0 }] })
    expect(graph.nodes.find((node) => node.type === 'run').data.run.status).toBe('recent')
    expect(graph.edges.every((edge) => !edge.animated)).toBe(true)
  })

  it('keeps legacy role heartbeats separate from unavailable per-replica capacity', () => {
    expect(workerServiceRows({
      by_stage: { discover: { running: 1 }, assess: { running: 2 }, remediate: { running: 0 } },
      worker_roles: {
        discovery: { alive: true, pool_size: 3, age_s: 1.2, version: 'v10' },
        assess: { alive: true, pool_size: 2, age_s: 4.6, version: 'v10' },
        remediate: { alive: false, pool_size: 2, age_s: 130, version: 'v9' },
      },
    })).toEqual([
      { role: 'discovery', stage: 'discover', active: null, slots: null, available: null,
        alive: true, age_s: 1.2, version: 'v10', status: 'unavailable', jobs_in_flight: 1,
        utilization_pct: null, capacity_source: 'legacy_role_heartbeat', measured_at: null,
        capacity_unavailable_reason: 'Per-replica capacity is not yet reporting. Jobs in flight are available, but slot utilization cannot be calculated honestly.' },
      { role: 'assess', stage: 'assess', active: null, slots: null, available: null,
        alive: true, age_s: 4.6, version: 'v10', status: 'unavailable', jobs_in_flight: 2,
        utilization_pct: null, capacity_source: 'legacy_role_heartbeat', measured_at: null,
        capacity_unavailable_reason: 'Per-replica capacity is not yet reporting. Jobs in flight are available, but slot utilization cannot be calculated honestly.' },
      { role: 'remediate', stage: 'remediate', active: null, slots: null, available: null,
        alive: false, age_s: 130, version: 'v9', status: 'unavailable', jobs_in_flight: 0,
        utilization_pct: null, capacity_source: 'unavailable', measured_at: null,
        capacity_unavailable_reason: 'Per-replica capacity is not yet reporting. Jobs in flight are available, but slot utilization cannot be calculated honestly.' },
    ])
  })

  it('does not turn legacy slots and durable running rows into a utilization gauge', () => {
    const [assess] = workerServiceRows({
      by_stage: { assess: { running: 40 } },
      worker_roles: { assess: { alive: true, pool_size: 2, heartbeat_at: '2026-09-05T12:00:00Z' } },
      worker_instance_attribution: { available: false, reason: 'Per-replica telemetry unavailable.' },
    })
    expect(assess).toMatchObject({ active: null, slots: null, jobs_in_flight: 40,
      utilization_pct: null, capacity_source: 'legacy_role_heartbeat',
      capacity_unavailable_reason: 'Per-replica telemetry unavailable.' })
    expect(nodeGauge({ kind: 'worker', service: assess })).toEqual({
      fraction: null, label: 'Per-replica worker utilization unavailable', over: false,
    })
  })

  it('uses per-replica busy slots without turning extra running rows into utilization', () => {
    const [assess] = workerServiceRows({
      worker_capacity_by_role: { assess: { capacity_source: 'worker_instances', worker_slots: 20,
        busy_slots: 20, jobs_in_flight: 40, healthy_replicas: 10, stale_replicas: 0,
        unattributed_running: 20, utilization_pct: 100, measured_at: '2026-09-05T12:00:00Z' } },
    })
    expect(assess).toMatchObject({ active: 20, slots: 20, available: 0, jobs_in_flight: 40,
      healthy_replicas: 10, unattributed_running: 20, utilization_pct: 100 })
  })

  it('shows authoritative Azure sizing without turning missing data into zero', () => {
    expect(capacityValue(2, ' vCPU')).toBe('2 vCPU')
    expect(capacityValue('4Gi')).toBe('4Gi')
    expect(capacityValue(null, '%')).toBe('Not reported')
    expect(source).toContain('Azure worker infrastructure')
    expect(source).toContain('EPHEMERAL STORAGE / REPLICA')
    expect(source).toContain('getWorkerCapacity')
    // Azure now arrives on the live stream's own `azure` event, so the reading reaches the page
    // when the server takes it rather than up to a poll interval later. The poll is kept, slower,
    // as the fallback for a backend that does not push it and as a recovery path after a drop —
    // deleting it would make "the SSE path works" an assumption the browser cannot check.
    expect(source).toContain('onAzure: takeAzure')
    expect(source).toContain('window.setInterval(refresh, 60000)')
  })

  it('puts reported compute, memory, storage, replicas, and health in worker drilldown', () => {
    const capacity = {
      configured: true, cpu_cores_per_replica: 2, memory_per_replica: '4Gi',
      ephemeral_storage_per_replica: '8Gi', current_replicas: 2, min_replicas: 1,
      max_replicas: 10, metrics_available: true, cpu_percent: 54, memory_percent: 67,
      active_revision_name: 'worker--v12', revision_health: 'Healthy', revision_traffic_percent: 100,
    }
    const graph = buildTrafficGraph({ runs: [], summary: { worker_roles: {
      assess: { alive: true, pool_size: 2, age_s: 3, version: 'v12' },
    } } }, new Map(), capacity, 'live')
    const worker = graph.nodes.find((node) => node.id === 'stage:assess').data
    // Loosened from toBe by the scope fix: the node metric now carries a `Tier:` qualifier,
    // because one container app's size is drawn on all three stage nodes. Still asserts the
    // measured size reaches the node, which is what this test was protecting.
    expect(worker.metric).toContain('2 vCPU · 4Gi RAM · 8Gi temporary disk')
    const detail = infrastructureDetail(worker, { summary: {} }, capacity)
    expect(detail.facts).toContainEqual(['Replica size', '2 vCPU · 4Gi RAM · 8Gi temporary disk'])
    expect(detail.facts).toContainEqual(['Replicas', '2 running · 1 min · 10 max'])
    expect(detail.facts).toContainEqual(['Live utilization', '54% CPU · 67% memory'])
  })

  it('opens both run and infrastructure tiles through the same accessible drawer', () => {
    expect(source).toContain("type: 'infra'")
    expect(source).toMatch(/onNodeClick=.*setSelectedKey/)
    expect(source).toContain('infrastructureDetail(selectedNode, snapshot, liveCapacity).facts')
    // The drawer no longer maps the flat `facts` array directly: it groups it first
    // (Capacity / Processing / Deployment / Source / Audit / Other) and renders each group behind
    // its own `<button aria-expanded>`. What this line was protecting — the SAME drawer consumes
    // the `facts` prop the tile handed it — is asserted by the wiring below. That every fact
    // actually reaches the reader, including one whose label the group map does not know, is
    // asserted at the DOM level in liveOpsDrawerRender.test.jsx, which is the better place for it:
    // a source grep for one expression cannot tell a rendered fact from a dropped one.
    expect(drawer).toContain('factGroups(facts)')
    expect(drawer).toContain('group.facts.map(')
    expect(source).toContain('Idle · select any tile to inspect the ready processing path')
  })
})

describe('The Azure panel reports what Azure reported, and states its own window', () => {
  const metrics = {
    restarts: { available: true, latest: 3, azure_metric: 'RestartCount' },
    network_in_bytes: { available: true, latest: 1572864, azure_metric: 'RxBytes' },
    network_out_bytes: { available: false, latest: null, azure_metric: 'TxBytes' },
  }

  it('renders a metric Azure answered and names one it did not', () => {
    expect(azureLatest({ metrics }, 'restarts')).toBe('3')
    expect(azureBytes({ metrics }, 'network_in_bytes')).toBe('1.5 MB')
    // The one that matters: a metric with no data is "Not reported", never a zero that would read
    // as an app which has never restarted and moved no traffic.
    expect(azureBytes({ metrics }, 'network_out_bytes')).toBe('Not reported')
    expect(azureLatest({ metrics }, 'requests')).toBe('Not reported')
    expect(azureLatest(null, 'restarts')).toBe('Not reported')
  })

  it('reads the averaging window from the payload rather than hardcoding it', () => {
    // It used to say "last 5 min" from a string in this file while the real timespan lived in
    // routes/control.py — widening the window there would have left this label wrong and silent.
    expect(source).toContain('average over ${capacityValue(capacity.metrics_window_minutes)} min')
    expect(source).not.toContain('memory · last 5 min')
  })
})

describe('The lines carry direction, activity and a way in', () => {
  const styles = readFileSync(join(here, 'styles.css'), 'utf8')
  const busy = { runs: [{ scan_id: 's1', owner: 'a@example.org', source: 'drive', stage: 'assess',
    completed: 8, total: 20, running: 2, queued: 4, status: 'active' }],
    summary: { active_runs: 1, by_stage: { assess: { running: 2 } }, worker_roles: {
      assess: { alive: true, pool_size: 3, age_s: 2 } } } }

  it('draws one continuous curve per line rather than a stepped route', () => {
    // The stepped router this replaced put right-angle corners around every node; a bezier has
    // no corners to round, which is what "as smooth as possible" means for this graph.
    expect(source).toContain("const EDGE_ROUTING = { type: 'bezier', pathOptions: { curvature: 0.42 } }")
    expect(source).toContain('defaultEdgeOptions={EDGE_ROUTING}')
    expect(source).not.toContain("type: 'smoothstep'")
  })

  it('points every line in the direction work actually flows', () => {
    const edges = buildTrafficGraph(busy).edges
    expect(edges.every((edge) => edge.markerEnd?.type === 'arrowclosed')).toBe(true)
    // Drawn in the line's own colour, so converging paths stay separable at the arrowhead.
    const assess = edges.find((edge) => edge.id === 'queue:assess')
    expect(assess.markerEnd.color).toBe(assess.style.stroke)
  })

  it('animates only the lines that have work on them', () => {
    const edges = buildTrafficGraph(busy).edges
    expect(edges.find((edge) => edge.id === 'in:s1:assess').animated).toBe(true)
    expect(edges.find((edge) => edge.id === 'queue:assess').animated).toBe(true)
    expect(edges.find((edge) => edge.id === 'sharepoint:intake').animated).toBe(false)
    expect(buildTrafficGraph({ runs: [], summary: {} }).edges.every((edge) => !edge.animated)).toBe(true)
  })

  it('says a line is live by weight as well as by motion', () => {
    // WCAG 1.4.1: animation is the only activity cue for a reader who has motion turned off, and
    // the global reduced-motion rule shortens rather than stops an infinite animation — so the
    // map needs both the static cue and a rule that actually stops the dashes.
    const live = flowEdge({ id: 'e', source: 'a', target: 'b', color: '#000', active: true })
    const quiet = flowEdge({ id: 'e', source: 'a', target: 'b', color: '#000' })
    expect(live.style.strokeWidth).toBeGreaterThan(quiet.style.strokeWidth)
    expect(live.style.opacity).toBeGreaterThan(quiet.style.opacity)
    expect(styles).toMatch(/prefers-reduced-motion: reduce\)\s*\{\s*\.react-flow__edge\.animated path/)
  })

  it('sends a click on a line to the drawer that explains the work on it', () => {
    const edges = buildTrafficGraph(busy).edges
    // Both of a run's lines resolve to that run, not to the stage one of them ends at.
    expect(edges.find((edge) => edge.id === 'in:s1:assess').data.detail).toBe('s1:assess')
    expect(edges.find((edge) => edge.id === 'out:s1:assess').data.detail).toBe('s1:assess')
    expect(edges.find((edge) => edge.id === 'queue:assess').data.detail).toBe('stage:assess')
    expect(edges.find((edge) => edge.id === 'drive:intake').data.detail).toBe('source:drive')
    expect(source).toContain("if (flowTab === 'infrastructure' && edge.data?.active)")
    expect(source).toContain("setFlowTab('jobs')")
    expect(edges.every((edge) => edge.interactionWidth >= 20)).toBe(true)
  })

  it('never leaves a line as the only route to what it explains', () => {
    // An edge is not keyboard-focusable in ReactFlow, so clicking one has to be a shortcut, never
    // the sole path. Every detail target is a node on the map, and nodes are tab-reachable.
    const graph = buildTrafficGraph(busy)
    const ids = new Set(graph.nodes.map((node) => node.id))
    expect(graph.edges.filter((edge) => !ids.has(edge.data.detail))).toEqual([])
  })

  it('tells the reader the running job cards are selectable', () => {
    expect(source).toContain('Select a stage to inspect progress; connected cards belong to one workflow')
  })
})

describe('The old drawer chart is retired, and stays unmounted', () => {
  // CLAUDE.md's retired-feature policy: keep the code so restoring it is one commit, but assert
  // the orphan so it cannot be mistaken for live code. This one matters more than most — it plots
  // `Number(...) || 0`, so an unreported measurement becomes a drawn zero, which is exactly what
  // the redesigned drawer exists not to do.
  it('is not rendered by any screen', () => {
    const screens = readdirSync(here).filter((f) => f.endsWith('.jsx') && !f.includes('.test.'))
    const mounts = screens.filter((f) => /<MetricChart[\s/>]/.test(readFileSync(join(here, f), 'utf8')))
    expect(mounts).toEqual([])
  })

  it('is marked retired where it lives, with the reason not to re-mount it', () => {
    expect(source).toMatch(/RETIRED 2026-09-04/)
    expect(source).toMatch(/turns an unreported measurement into a plotted zero/)
  })
})

describe('Idle map: scope and announcement', () => {
  const snapshot = { runs: [], summary: { queued: 0, worker_roles: {
    discovery: { alive: true, pool_size: 3, age_s: 8 }, assess: { alive: true, pool_size: 2, age_s: 2 },
    remediate: { alive: true, pool_size: 2, age_s: 3 } }, by_stage: {} } }
  const capacity = { configured: true, worker_app_name: 'acp-worker', cpu_cores_per_replica: 2,
    memory_per_replica: '4Gi', ephemeral_storage_per_replica: '8Gi', current_replicas: 1 }

  it('does not present one container app reading as each stage own size', () => {
    // api/routes/control.py reads a single app (WORKER_APP_NAME), and the same figure is attached
    // to every stage node. Unqualified, Discover/Assess/Remediate each claim it as their own.
    const detail = infrastructureDetail(
      { kind: 'worker', label: 'Assess workers', service: { alive: true, active: 0, available: 2, slots: 2 } },
      snapshot, capacity)
    const labels = detail.facts.map(([label]) => label)
    expect(labels).toContain('Replica size')
    expect(detail.facts.find(([l]) => l === 'Size measured from')[1])
      .toMatch(/Measured from acp-worker, which is not one of the 3 reporting worker services/)
  })

  it('marks the on-node size as the tier figure it is', () => {
    const stage = buildTrafficGraph(snapshot, new Map(), capacity).nodes.find((n) => n.id === 'stage:assess')
    expect(stage.data.metric).toMatch(/^acp-worker: /)
  })

  it('names every node for a screen reader', () => {
    // ReactFlow gives nodes tabIndex 0 and routes Enter/Space through the click handler, so the
    // map is keyboard-operable; with no ariaLabel each tile announces only as "node".
    const nodes = buildTrafficGraph(snapshot, new Map(), capacity).nodes
    const unlabelled = nodes.filter((n) => n.type === 'infra' && !n.ariaLabel)
    expect(unlabelled.map((n) => n.id)).toEqual([])
    expect(nodes.find((n) => n.id === 'stage:discover').ariaLabel)
      .toMatch(/Discover workers, unavailable, slot utilization unavailable/)
  })

  it('keeps worker tiles in non-overlapping lanes with dedicated queue and output ports', () => {
    const graph = buildTrafficGraph(snapshot, new Map(), capacity)
    const stages = ['discover', 'assess', 'remediate'].map((stage) =>
      graph.nodes.find((node) => node.id === `stage:${stage}`))
    const gaps = stages.slice(1).map((node, index) => node.position.y - stages[index].position.y)

    // Worker cards grow when gauge and compute/storage telemetry wrap. A 145px lane still let
    // their borders touch in production; 170px preserves a visible gutter at fitView scale.
    expect(gaps).toEqual([170, 170])
    const queue = graph.nodes.find((node) => node.id === 'infra:queue')
    const output = graph.nodes.find((node) => node.id === 'infra:output')
    expect(queue.data.outputPorts.map((port) => port.id)).toEqual(['discover', 'assess', 'remediate'])
    expect(output.data.inputPorts.map((port) => port.id)).toEqual(['discover', 'assess', 'remediate'])
    for (const stage of ['discover', 'assess', 'remediate']) {
      expect(graph.edges.find((edge) => edge.id === `queue:${stage}`).sourceHandle).toBe(stage)
      expect(graph.edges.find((edge) => edge.id === `${stage}:output`).targetHandle).toBe(stage)
    }
  })

  it('keeps run cards below the always-visible infrastructure topology', () => {
    const active = { ...snapshot, runs: [{ scan_id: 'scan-1', stage: 'assess', source: 'sharepoint',
      owner: 'owner@example.com', total: 20, completed: 5, running: 2, queued: 13 }] }
    const graph = buildTrafficGraph(active, new Map(), capacity)
    const lastWorker = graph.nodes.find((node) => node.id === 'stage:remediate')
    const run = graph.nodes.find((node) => node.id === 'scan-1:assess')
    expect(run.position.y - lastWorker.position.y).toBeGreaterThanOrEqual(175)
  })
})

describe('Worker app misconfiguration is legible', () => {
  it('distinguishes an unreadable app from telemetry that has not reported', () => {
    // Backend returns configured:true with every field None when the Container App lookup fails,
    // so without a dedicated branch this renders as a full panel of dashes — the same thing a
    // healthy app awaiting Azure Monitor samples shows. That is how a WORKER_APP_NAME pointing
    // at the retired acp-worker app stayed invisible.
    expect(source).toMatch(/capacity\.app_unavailable/)
    expect(source).toMatch(/Azure worker app could not be read/)
    expect(source).toMatch(/renamed, deleted, or the identity may lack/)
  })

  it('names the variable an operator has to set, and says why it has no default', () => {
    expect(source).toMatch(/Set AZURE_SUBSCRIPTION_ID and WORKER_APP_NAME/)
    expect(source).toMatch(/WORKER_APP_NAME has no default/)
  })
})

describe('The size figure says whose size it is', () => {
  const roles = { discovery: { alive: true, pool_size: 3, age_s: 1 },
    assess: { alive: true, pool_size: 2, age_s: 1 }, remediate: { alive: true, pool_size: 2, age_s: 1 } }
  const services = workerServiceRows({ worker_roles: roles, by_stage: {} })
  const cap = (name) => ({ configured: true, worker_app_name: name, cpu_cores_per_replica: 2,
    memory_per_replica: '4Gi', ephemeral_storage_per_replica: '8Gi' })

  it('names the one service it measured, and how many it did not', () => {
    // deploy/public/rightsize-production.sh: acp-discovery is 1 CPU / 2Gi while acp-assess and
    // acp-remediate are 2 CPU / 4Gi, so a reading from one app is wrong for a differently sized
    // sibling. "Covering the worker tier" — what this said before — was false.
    expect(sizeScopeNote(cap('acp-assess'), services))
      .toBe('Measured from acp-assess (Assess) only — 1 of 3 reporting worker services; the others may be sized differently')
  })

  it('says so when the named app is not one of the reporting services', () => {
    expect(sizeScopeNote(cap('acp-worker'), services))
      .toMatch(/not one of the 3 reporting worker services — it may not describe any of them/)
  })

  it('does not claim a comparison when only one service reports', () => {
    const one = workerServiceRows({ worker_roles: { assess: roles.assess }, by_stage: {} })
    expect(sizeScopeNote(cap('acp-assess'), one)).toBe('Measured from acp-assess (Assess), the only reporting worker service')
  })

  it('degrades honestly with nothing to go on', () => {
    expect(sizeScopeNote(null, services)).toBe('Not reported')
    expect(sizeScopeNote({ configured: true }, services))
      .toBe('Azure did not report which container app was measured')
    expect(sizeScopeNote(cap('acp-assess'), []))
      .toMatch(/no worker services are reporting to compare it against/)
  })

  it('never claims tier-wide coverage from a single app reading', () => {
    expect(source).not.toMatch(/covering the worker tier/)
  })
})


describe('The map tiles carry a live gauge', () => {
  it('fills a worker tile by the share of its own slots that are busy', () => {
    const gauge = nodeGauge({ kind: 'worker', service: {
      active: 2, slots: 4, capacity_source: 'worker_instances',
    } })
    expect(gauge).toEqual({ fraction: 0.5, over: false, label: '2 of 4 slots busy (50%)' })
  })

  it('never draws a bar past its own track, and says so instead', () => {
    // The bug this exists for: against a real deployment the drawer read "51 of 2 worker slots
    // active (2550%)". More work in flight than slots is not a share of capacity — the slot count
    // comes from a last-writer-wins heartbeat describing ONE replica while the job count covers
    // them all, and a stale lease looks identical.
    const gauge = nodeGauge({ kind: 'worker', service: {
      active: 51, slots: 2, capacity_source: 'worker_instances',
    } })
    expect(gauge.fraction).toBe(1)
    expect(gauge.over).toBe(true)
    expect(gauge.label).toBe('51 jobs against 2 reported slots')
    expect(gauge.label).not.toContain('%')
  })

  it('measures the queue against the slots of the ROLE that could pick it up', () => {
    // This test kept its subject and changed its expectation, deliberately. It used to assert
    // `worker_slots` — the FLEET total — which was the bug: seen in production 2026-09-05, the
    // tile read "132 waiting, more than the 7 slots that could pick them up" when five of those
    // seven belonged to Discover and Assess and no remediate job was eligible for any of them.
    // A job is claimed only by workers for its own stage, so the denominator is that stage's.
    expect(nodeGauge({ kind: 'queue' }, {
      queued: 3, worker_slots: 60,
      by_stage: { assess: { queued: 3 } },
      worker_roles: { assess: { alive: true, pool_size: 6 } },
    })).toMatchObject({ fraction: 0.5, over: false })

    const blocked = nodeGauge({ kind: 'queue' }, {
      queued: 184, worker_slots: 7,
      by_stage: { remediate: { queued: 184 } },
      worker_roles: { remediate: { alive: true, pool_size: 2 },
        assess: { alive: true, pool_size: 5 } },
    })
    expect(blocked.over).toBe(true)
    expect(blocked.label).toContain('remediate')
    expect(blocked.label).not.toContain('7')
  })

  it('draws no bar at all when there is no denominator to be a share of', () => {
    // An unmeasured value gets no fill — not an empty one that reads as zero.
    expect(nodeGauge({ kind: 'worker', service: {
      active: 2, slots: 0, capacity_source: 'worker_instances',
    } }))
      .toEqual({ fraction: null, over: false, label: 'Worker slots not reported' })
    expect(nodeGauge({ kind: 'queue' }, { queued: 4 }).fraction).toBe(null)
    // A connector and the output store have no capacity to be a fraction of.
    expect(nodeGauge({ kind: 'source' })).toBe(null)
    expect(nodeGauge({ kind: 'output' })).toBe(null)
  })

  it('attaches the gauge to the worker and queue tiles, and updates it from each snapshot', () => {
    const graph = buildTrafficGraph({ runs: [], summary: { queued: 5, worker_slots: 10,
      by_stage: { assess: { running: 1 } },
      worker_roles: { assess: { alive: true, pool_size: 2, age_s: 1 } },
      worker_capacity_by_role: { assess: { capacity_source: 'worker_instances', worker_slots: 2,
        busy_slots: 1, jobs_in_flight: 1, healthy_replicas: 1 } } } })
    expect(graph.nodes.find((n) => n.id === 'stage:assess').data.gauge)
      .toMatchObject({ fraction: 0.5, label: '1 of 2 slots busy (50%)' })
    // The queue's waiting work now has to be attributed to a stage to be measured at all —
    // `queued: 5` with no stage owning it is work nobody is eligible for, and the tile says so
    // instead of dividing it by the fleet.
    expect(graph.nodes.find((n) => n.id === 'infra:queue').data.gauge)
      .toMatchObject({ fraction: null, label: '5 waiting · not attributed to a stage' })
    // The next snapshot rebuilds the graph, so the bar is as live as the tile it sits on.
    const busier = buildTrafficGraph({ runs: [], summary: { queued: 9, worker_slots: 10,
      by_stage: { assess: { running: 2, queued: 9 } },
      worker_roles: { assess: { alive: true, pool_size: 2, age_s: 1 } },
      worker_capacity_by_role: { assess: { capacity_source: 'worker_instances', worker_slots: 2,
        busy_slots: 2, jobs_in_flight: 2, healthy_replicas: 1 } } } })
    expect(busier.nodes.find((n) => n.id === 'stage:assess').data.gauge.fraction).toBe(1)
    // 9 waiting against assess's OWN 2 slots is over capacity — where the fleet's 10 would have
    // rendered it as a comfortable 0.9.
    expect(busier.nodes.find((n) => n.id === 'infra:queue').data.gauge)
      .toMatchObject({ fraction: 1, over: true })
  })

  it('does not put a second progress bar on a run tile that already has one', () => {
    const graph = buildTrafficGraph({ runs: [{ scan_id: 's1', stage: 'assess', source: 'drive',
      owner: 'a@example.org', completed: 5, total: 20, running: 1, queued: 2 }] })
    expect(graph.nodes.find((n) => n.id === 's1:assess').data.gauge).toBeUndefined()
  })
})


describe('A scan job and a durable service do not look alike', () => {
  it('fills a job with its stage colour and leaves a service flat', () => {
    // The two were nearly identical white cards, which is what made "51 active" on a job tile
    // beside "2 slots" on a service tile read as one contradiction rather than two measurements.
    const job = tileStyle('run', '#4C78C2')
    const service = tileStyle('worker', '#4C78C2')
    expect(job.background).toBe('color-mix(in srgb, #4C78C2 16%, var(--panel))')
    expect(service.background).toBe('var(--panel)')
    expect(job.borderLeft).toBe('5px solid #4C78C2')
    expect(service.borderLeft).toBeUndefined()
  })

  it('groups the map into the three kinds a reader actually distinguishes', () => {
    // Sources and outputs are where documents come from and go to — neither transient work nor
    // the services that process it — so they are their own kind.
    expect(tileKind('run')).toBe('job')
    expect(['worker', 'queue', 'intake'].map(tileKind)).toEqual(['service', 'service', 'service'])
    expect(['source', 'output'].map(tileKind)).toEqual(['data', 'data'])
    expect(tileKind('something-new')).toBe('service')
  })

  it('never leaves colour as the only cue', () => {
    // WCAG 1.4.1. The fill makes the grouping visible at a glance; the typed label is what says
    // which is which, and the map key spells all three out.
    expect(Object.values(TILE_KINDS).map((spec) => spec.label))
      .toEqual(['ACTIVE JOB', 'SERVICE', 'DATA'])
    expect(tileStyle('run', '#000').label).toBe('ACTIVE JOB')
    expect(tileStyle('source', '#000').label).toBe('DATA')
    expect(source).toContain('{tileStyle(data.kind, color).label}')
    expect(source).toContain('<b style={{ color: \'var(--ink)\' }}>DATA</b>')
  })
})
