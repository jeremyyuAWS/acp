import { describe, expect, it } from 'vitest'
import { buildTrafficGraph } from './AdminLiveTraffic.jsx'

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
    expect(history.get('s1:assess')).toHaveLength(18)
    expect(history.get('s1:assess').at(-1)).toBe(24)
  })
})
