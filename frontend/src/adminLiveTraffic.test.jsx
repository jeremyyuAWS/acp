import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { buildTrafficGraph, capacityValue, infrastructureDetail, queueConcentration, trendToggleLabel, workerServiceRows } from './AdminLiveTraffic.jsx'

const source = readFileSync(join(dirname(fileURLToPath(import.meta.url)), 'AdminLiveTraffic.jsx'), 'utf8')

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

  it('connects each live run to its worker stage within the persistent topology', () => {
    const graph = buildTrafficGraph({ runs: [run] })
    expect(graph.nodes.map((node) => node.id)).toContain('s1:assess')
    expect(graph.edges.find((edge) => edge.id === 'out:s1:assess').animated).toBe(true)
    expect(graph.nodes.find((node) => node.id === 's1:assess').data.run.current_file).toBe('Report.docx')
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
    expect(source).toMatch(/<aside role="dialog" aria-modal="true"/)
    expect(source).toContain("background: 'var(--card, #fff)'")
    expect(source).toContain("width: 'clamp(360px, 38vw, 560px)'")
    expect(source).toMatch(/position: 'sticky', top: 0/)
    expect(source).toMatch(/rgba\(28,22,32,.28\)/)
    expect(source).toMatch(/overflowWrap: 'anywhere'/)
    expect(source).toContain("event.key === 'Escape'")
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

  it('shows dedicated worker capacity by service rather than one last-writer heartbeat', () => {
    expect(workerServiceRows({
      by_stage: { discover: { running: 1 }, assess: { running: 2 }, remediate: { running: 0 } },
      worker_roles: {
        discovery: { alive: true, pool_size: 3, age_s: 1.2, version: 'v10' },
        assess: { alive: true, pool_size: 2, age_s: 4.6, version: 'v10' },
        remediate: { alive: false, pool_size: 2, age_s: 130, version: 'v9' },
      },
    })).toEqual([
      { role: 'discovery', stage: 'discover', active: 1, slots: 3, available: 2, alive: true, age_s: 1.2, version: 'v10' },
      { role: 'assess', stage: 'assess', active: 2, slots: 2, available: 0, alive: true, age_s: 4.6, version: 'v10' },
      { role: 'remediate', stage: 'remediate', active: 0, slots: 2, available: 2, alive: false, age_s: 130, version: 'v9' },
    ])
  })

  it('shows authoritative Azure sizing without turning missing data into zero', () => {
    expect(capacityValue(2, ' vCPU')).toBe('2 vCPU')
    expect(capacityValue('4Gi')).toBe('4Gi')
    expect(capacityValue(null, '%')).toBe('Not reported')
    expect(source).toContain('Azure worker infrastructure')
    expect(source).toContain('EPHEMERAL STORAGE / REPLICA')
    expect(source).toContain('getWorkerCapacity')
    expect(source).toContain('window.setInterval(refresh, 30000)')
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
    expect(source).toContain('selectedInfrastructure.facts.map')
    expect(source).toContain('Idle · select any tile to inspect the ready processing path')
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
      .toMatch(/One Azure Container App \(acp-worker\) covering the worker tier — not measured per service/)
  })

  it('marks the on-node size as the tier figure it is', () => {
    const stage = buildTrafficGraph(snapshot, new Map(), capacity).nodes.find((n) => n.id === 'stage:assess')
    expect(stage.data.metric).toMatch(/^Tier: /)
  })

  it('names every node for a screen reader', () => {
    // ReactFlow gives nodes tabIndex 0 and routes Enter/Space through the click handler, so the
    // map is keyboard-operable; with no ariaLabel each tile announces only as "node".
    const nodes = buildTrafficGraph(snapshot, new Map(), capacity).nodes
    const unlabelled = nodes.filter((n) => n.type === 'infra' && !n.ariaLabel)
    expect(unlabelled.map((n) => n.id)).toEqual([])
    expect(nodes.find((n) => n.id === 'stage:discover').ariaLabel)
      .toMatch(/Discover workers, online, 0 active of 3 slots/)
  })
})
