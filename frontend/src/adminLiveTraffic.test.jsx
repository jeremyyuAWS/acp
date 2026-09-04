import { describe, expect, it } from 'vitest'
import { readFileSync, readdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { buildTrafficGraph, capacityValue, infrastructureDetail, queueConcentration, sizeScopeNote, trendToggleLabel, workerServiceRows } from './AdminLiveTraffic.jsx'

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
    expect(source).toContain('infrastructureDetail(selectedNode, snapshot, liveCapacity).facts')
    expect(drawer).toContain('facts.map(([label, value])')
    expect(source).toContain('Idle · select any tile to inspect the ready processing path')
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
      .toMatch(/Discover workers, online, 0 active of 3 slots/)
  })

  it('keeps worker tiles in non-overlapping lanes with dedicated queue and output ports', () => {
    const graph = buildTrafficGraph(snapshot, new Map(), capacity)
    const stages = ['discover', 'assess', 'remediate'].map((stage) =>
      graph.nodes.find((node) => node.id === `stage:${stage}`))
    const gaps = stages.slice(1).map((node, index) => node.position.y - stages[index].position.y)

    // Worker cards grow when compute/storage telemetry wraps. The old 105px lane put the next
    // card underneath it; 145px leaves a real gutter at the narrow fitView scale too.
    expect(gaps).toEqual([145, 145])
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
    expect(run.position.y - lastWorker.position.y).toBeGreaterThanOrEqual(125)
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
