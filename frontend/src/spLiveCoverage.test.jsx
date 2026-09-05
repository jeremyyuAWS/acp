// SharePoint coverage on the Live Operations map.
//
// A 30-site walk is one long "discovering" bar there: the file count ticks up and nothing says
// which sites are done, which are still queued, or that one is blocked on a consent that lapsed
// this morning.
//
// The judgement worth pinning is the negative one — a Drive run carries no site fields, and
// rendering "0 of 0 sites" under Google Drive would be a fact about this component rather than
// anything an operator could act on.
import { describe, it, expect } from 'vitest'
import { buildTrafficGraph } from './AdminLiveTraffic.jsx'

const run = (over = {}) => ({ scan_id: 's1', owner: 'o@example.com', source: 'sharepoint',
  stage: 'discover', status: 'active', queued: 0, running: 1, completed: 0, total: 1, ...over })

const sourceNode = (graph, source) =>
  graph.nodes.find((n) => n.id === `source:${source}`)

describe('SharePoint coverage on the operations map', () => {
  it('says how many sites are done, out of how many', () => {
    const g = buildTrafficGraph({ runs: [run({ sites_total: 30, sites_done: 12,
                                               libraries_total: 41 })] })
    expect(sourceNode(g, 'sharepoint').data.coverage).toBe('12 of 30 sites, 41 libraries')
  })

  it('names the sites it could not read', () => {
    // The number an operator acts on: a consent to chase, or a cap to raise.
    const g = buildTrafficGraph({ runs: [run({ sites_total: 30, sites_done: 27,
                                               sites_unread: 3, libraries_total: 40 })] })
    expect(sourceNode(g, 'sharepoint').data.coverage).toMatch(/3 not read/)
  })

  it('says nothing about coverage for a source that reports none', () => {
    // THE negative case. "0 of 0 sites" under Google Drive is a fact about the component.
    const g = buildTrafficGraph({ runs: [run({ source: 'drive' })] })
    expect(sourceNode(g, 'drive').data.coverage).toBeNull()
    expect(sourceNode(g, 'drive').data.detail).toBe('Authorized document connector')
  })

  it('says nothing when a SharePoint run has not reached its first site yet', () => {
    const g = buildTrafficGraph({ runs: [run()] })
    expect(sourceNode(g, 'sharepoint').data.coverage).toBeNull()
  })

  it('sums across concurrent runs, because this map is cross-tenant', () => {
    // It answers "what is the estate doing", not "what is my scan doing".
    const g = buildTrafficGraph({ runs: [
      run({ scan_id: 'a', sites_total: 10, sites_done: 10, libraries_total: 10 }),
      run({ scan_id: 'b', sites_total: 5, sites_done: 2, libraries_total: 6 }),
    ] })
    expect(sourceNode(g, 'sharepoint').data.coverage).toBe('12 of 15 sites, 16 libraries')
  })

  it('announces the coverage to a screen reader, not only to the eye', () => {
    // ariaLabel sits on the NODE — ReactFlow reads node.ariaLabel, and nesting it in data is
    // silently ignored (the mistake this file's neighbour already caught once).
    const g = buildTrafficGraph({ runs: [run({ sites_total: 30, sites_done: 12,
                                               libraries_total: 41 })] })
    expect(sourceNode(g, 'sharepoint').ariaLabel).toMatch(/12 of 30 sites/)
  })

  it('pluralises one site and one library', () => {
    const g = buildTrafficGraph({ runs: [run({ sites_total: 1, sites_done: 1,
                                               libraries_total: 1 })] })
    expect(sourceNode(g, 'sharepoint').data.coverage).toBe('1 of 1 site, 1 library')
  })
})
