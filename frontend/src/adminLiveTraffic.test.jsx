import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { buildTrafficGraph, capacityValue, queueConcentration, trendToggleLabel, workerServiceRows } from './AdminLiveTraffic.jsx'

const source = readFileSync(join(dirname(fileURLToPath(import.meta.url)), 'AdminLiveTraffic.jsx'), 'utf8')

const run = {
  scan_id: 's1', owner: 'operator@example.org', source: 'drive', stage: 'assess',
  completed: 8, total: 20, running: 2, queued: 10, current_file: 'Report.docx',
}

describe('Admin live traffic graph', () => {
  it('connects each live run from its source to its worker stage', () => {
    const graph = buildTrafficGraph({ runs: [run] })
    expect(graph.nodes.map((node) => node.id)).toEqual(['source:drive', 'stage:assess', 's1:assess'])
    expect(graph.edges).toHaveLength(2)
    expect(graph.edges.every((edge) => edge.animated)).toBe(true)
    expect(graph.nodes[2].data.run.current_file).toBe('Report.docx')
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
})
