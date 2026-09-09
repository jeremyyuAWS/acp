import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, createElement } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'
import RemediationWaterfallGraph, { waterfallGraphModel } from './RemediationWaterfallGraph.jsx'
import { readFileSync } from 'node:fs'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
vi.mock('@xyflow/react', () => ({
  Position: { Left: 'left', Right: 'right', Top: 'top', Bottom: 'bottom' }, MarkerType: { ArrowClosed: 'arrowclosed' },
  Controls: () => null, Handle: () => null, Background: () => null,
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
    expect(container.querySelectorAll('[data-stage]')).toHaveLength(5)
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
    expect(graph.edges.map(edge => `${edge.source}->${edge.target}`)).toEqual(['rules->first:provider-one:recorded-first-v2', 'first:provider-one:recorded-first-v2->next:provider-two:recorded-fallback-version-20250514', 'next:provider-two:recorded-fallback-version-20250514->approval', 'approval->verify'])
    expect(graph.edges.filter(edge => edge.animated).map(edge => edge.target)).toEqual(['next:provider-two:recorded-fallback-version-20250514'])
    expect(graph.nodes.filter(node => node.data.active).map(node => node.id)).toEqual(['next:provider-two:recorded-fallback-version-20250514'])
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

  it('moves keyboard focus without opening the stage drawer until a button is activated', async () => {
    const onSelect = vi.fn()
    const { container } = await mount({ selection: 'first:provider-one:recorded-first-v2', onSelect })
    const first = container.querySelector('[data-stage=first]')
    expect(first.getAttribute('aria-pressed')).toBe('true')
    await act(async () => first.click())
    expect(onSelect).toHaveBeenLastCalledWith('first:provider-one:recorded-first-v2', expect.objectContaining({ model: 'recorded-first-v2', tier: 1 }))
    onSelect.mockClear()
    await act(async () => first.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true })))
    expect(document.activeElement).toBe(container.querySelector('[data-stage=next]'))
    expect(onSelect).not.toHaveBeenCalled()
    await act(async () => document.activeElement.dispatchEvent(new KeyboardEvent('keydown', { key: 'Home', bubbles: true })))
    expect(document.activeElement).toBe(container.querySelector('[data-stage=rules]'))
    await act(async () => document.activeElement.dispatchEvent(new KeyboardEvent('keydown', { key: 'End', bubbles: true })))
    expect(document.activeElement).toBe(container.querySelector('[data-stage=verify]'))
    expect(onSelect).not.toHaveBeenCalled()
    await act(async () => document.activeElement.click())
    expect(onSelect).toHaveBeenLastCalledWith('verify', expect.objectContaining({ stage: 'verify' }))
  })

  it.each([240, 280, 360, 600, 1100])('keeps full-size nodes within a %spx canvas', width => {
    const graph = waterfallGraphModel({ stages, width })
    graph.nodes.forEach(node => {
      expect(node.position.x).toBeGreaterThanOrEqual(0)
      expect(node.position.x + node.style.width).toBeLessThanOrEqual(width)
      expect(node.position.y + node.data.height).toBeLessThanOrEqual(graph.height)
    })
    const columns = new Set(graph.nodes.map(node => node.position.x)).size
    expect(columns).toBe(width < 420 ? 1 : width < 850 ? 2 : 5)
  })
})

 it('separates recorded models within one tier without inventing a sequential fallback chain', async () => {
   const models = [{ provider: 'a', model: 'fallback-one', recorded_attempts: 2 }, { provider: 'b', model: 'fallback-two', recorded_attempts: 3 }]
   const input = { stages: [{ tier: 2, operations: 5, active: 1, models }], motion: { stage: 'next' } }
   const graph = waterfallGraphModel(input)
   const alternatives = graph.nodes.filter(node => node.data.tier === 2)
   expect(alternatives.map(node => node.data.title)).toEqual(['fallback-one', 'fallback-two'])
   expect(new Set(graph.nodes.map(node => node.id)).size).toBe(6)
   expect(alternatives.every(node => !node.data.active)).toBe(true)
   expect(graph.edges.some(edge => alternatives.some(node => node.id === edge.source) && alternatives.some(node => node.id === edge.target))).toBe(false)
   expect(alternatives.map(node => node.data.value)).toEqual([2, 3])
   const { container } = await mount(input)
   const buttons = container.querySelectorAll('[data-stage]')
   await act(async () => buttons[2].dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true })))
   expect(document.activeElement).toBe(buttons[3])
   await act(async () => buttons[3].dispatchEvent(new KeyboardEvent('keydown', { key: 'End', bubbles: true })))
   expect(document.activeElement).toBe(buttons[5])
 })
 it.each(['processing_complete', 'failed', 'cancelled', 'paused', 'stalled'])('retains calm nodes after %s even with stale active motion', async state => {
   const { container } = await mount({ snapshot: { state, terminal: true }, motion: { stage: 'first' } })
   expect(container.querySelectorAll('[data-stage]')).toHaveLength(5)
   expect(container.querySelector('.wf-graph-node-active')).toBeNull()
   expect(container.querySelector('[data-testid=moving-edges]').textContent).toBe('')
 })

 it('keeps each model identity stable when another recorded model arrives', () => {
   const model = { provider: 'provider', model: 'model-one' }
   const single = waterfallGraphModel({ stages: [{ tier: 2, models: [model] }] })
   const multiple = waterfallGraphModel({ stages: [{ tier: 2, models: [model, { provider: 'other', model: 'model-two' }] }] })
   expect(single.nodes.find(node => node.data.model === 'model-one').id).toBe(multiple.nodes.find(node => node.data.model === 'model-one').id)
   expect(single.nodes.every(node => node.initialWidth > 0 && node.initialHeight > 0 && node.handles.length)).toBe(true)
 })
