import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, createElement } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'
import RemediationWaterfallGraph, { waterfallGraphModel } from './RemediationWaterfallGraph.jsx'
import { readFileSync } from 'node:fs'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
vi.mock('@xyflow/react', () => ({
  Position: { Left: 'left', Right: 'right', Top: 'top', Bottom: 'bottom' }, MarkerType: { ArrowClosed: 'arrowclosed' },
  Handle: () => null, Background: () => null,
  ReactFlow: ({ nodes, edges, nodeTypes, children }) => createElement('div', { 'data-testid': 'flow' },
    ...nodes.map(node => createElement(nodeTypes[node.type], { key: node.id, data: node.data })),
    createElement('span', { 'data-testid': 'moving-edges' }, edges.filter(edge => edge.animated).map(edge => edge.target).join(',')), children),
}))
const stages = [
  { tier: 1, operations: 4, models: [{ provider: 'provider-one', model: 'recorded-first-v2' }] },
  { tier: 2, operations: 2, models: [{ provider: 'provider-two', model: 'recorded-fallback-version-20250514' }] },
]
beforeEach(() => { vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }))) })
afterEach(async () => { await unmountAll(); vi.unstubAllGlobals() })
async function mount(props = {}) {
  const { root, container } = createTestRoot()
  await act(async () => root.render(createElement(RemediationWaterfallGraph, { stages, ...props })))
  return { root, container }
}

describe('the connected remediation waterfall', () => {
  it('shows recorded model names and providers, with attempt units distinct from changes', async () => {
    const { container } = await mount({ reviewCount: 8, verifiedCount: 404 })
    expect(container.querySelectorAll('button')).toHaveLength(5)
    expect(container.querySelector('[data-stage=first]').textContent).toContain('recorded-first-v2')
    expect(container.querySelector('[data-stage=first]').textContent).toContain('provider-one')
    expect(container.querySelector('[data-stage=next]').textContent).toContain('recorded-fallback-version-20250514')
    expect(container.querySelector('[data-stage=next]').textContent).toContain('provider-two')
    expect(container.querySelector('[data-stage=next]').textContent).toContain('2 recorded operations')
    expect(container.querySelector('[data-stage=approval]').textContent).toContain('8 review items')
    expect(container.querySelector('[data-stage=verify]').textContent).toContain('404 verified changes')
  })

  it('does not invent identities or turn unavailable counts into zero', async () => {
    const { container } = await mount({ stages: [{ tier: 1, operations: 0 }], aiEnabled: false })
    expect(container.querySelector('[data-stage=first]').textContent).toContain('Not used yet')
    expect(container.querySelector('[data-stage=next]').textContent).toContain('Model not recorded')
    expect(container.querySelector('[data-stage=next]').textContent).toContain('AI disabled for this run')
    expect(container.querySelector('[data-stage=approval]').textContent).toContain('Unavailable')
  })

  it('moves only the connection into the confirmed active stage', () => {
    const graph = waterfallGraphModel({ stages, motion: { documents: 22, stage: 'next' } })
    expect(graph.edges.map(edge => `${edge.source}->${edge.target}`)).toEqual(['rules->first', 'first->next', 'next->approval', 'approval->verify'])
    expect(graph.edges.filter(edge => edge.animated).map(edge => edge.target)).toEqual(['next'])
    expect(graph.nodes.filter(node => node.data.active).map(node => node.id)).toEqual(['next'])
    expect(waterfallGraphModel({ stages, motion: { documents: 22, stage: null } }).edges.some(edge => edge.animated)).toBe(false)
  })

  it.each([{ paused: true }, { error: true }, { motion: { stage: 'first', hidden: true } }])('holds the graph static when activity is paused or unavailable: %j', async props => {
    const { container } = await mount({ motion: { stage: 'first' }, ...props })
    expect(container.querySelector('[data-testid=moving-edges]').textContent).toBe('')
    expect(container.querySelector('.wf-graph-node-active')).toBeNull()
  })

  it('honors reduced motion in React Flow edges and stylesheet fallbacks', async () => {
    matchMedia.mockReturnValue({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() })
    const { container } = await mount({ motion: { stage: 'verify' } })
    expect(container.querySelector('[data-testid=moving-edges]').textContent).toBe('')
    expect(container.querySelector('[data-stage=verify] .wf-graph-node-working').textContent).toContain('Verification in progress')
    const css = readFileSync(`${import.meta.dirname}/remediation-waterfall-graph.css`, 'utf8')
    expect(css).toMatch(/prefers-reduced-motion:reduce[\s\S]*animation:none/)
  })

  it('offers native stage buttons and arrow/Home/End selection without moving focus to a panel', async () => {
    const onSelect = vi.fn()
    const { container } = await mount({ selection: 'first', onSelect })
    const first = container.querySelector('[data-stage=first]')
    expect(first.getAttribute('aria-pressed')).toBe('true')
    await act(async () => first.click())
    expect(onSelect).toHaveBeenLastCalledWith('first')
    await act(async () => first.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true })))
    expect(document.activeElement).toBe(container.querySelector('[data-stage=next]'))
    expect(onSelect).toHaveBeenLastCalledWith('next')
    await act(async () => document.activeElement.dispatchEvent(new KeyboardEvent('keydown', { key: 'Home', bubbles: true })))
    expect(document.activeElement).toBe(container.querySelector('[data-stage=rules]'))
    await act(async () => document.activeElement.dispatchEvent(new KeyboardEvent('keydown', { key: 'End', bubbles: true })))
    expect(document.activeElement).toBe(container.querySelector('[data-stage=verify]'))
  })

  it.each([360, 1100])('keeps full-size nodes within a %spx canvas', width => {
    const graph = waterfallGraphModel({ stages, width })
    graph.nodes.forEach(node => {
      expect(node.position.x).toBeGreaterThanOrEqual(0)
      expect(node.position.x + node.style.width).toBeLessThanOrEqual(width)
      expect(node.position.y + node.data.height).toBeLessThanOrEqual(graph.height)
    })
    expect(graph.height).toBeLessThan(width === 360 ? 750 : 300)
  })
})
