import { act, createElement } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import useForecastDeltas from './useForecastDeltas.js'
import { createTestRoot, unmountAll } from './testRoots.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
function Harness(props) { return <output>{JSON.stringify(useForecastDeltas(props))}</output> }
afterEach(() => { unmountAll(); vi.useRealTimers() })
async function setup() {
  const { container, root } = createTestRoot()
  const render = async props => act(async () => root.render(createElement(Harness, {
    identity: 'run-1:all', ready: true, policyKey: '0:0', automatic: 0, human: 100, ...props,
  })))
  await render({})
  return { render, value: () => JSON.parse(container.textContent) }
}
describe('selection-relative forecast deltas', () => {
  it('skips initial load and same-policy refreshes, animates signed changes and expires', async () => {
    vi.useFakeTimers()
    const { render, value } = await setup()
    expect(value()).toBeNull()
    await render({ automatic: 2, human: 98 })
    expect(value()).toBeNull()
    await render({ ready: false })
    await render({ policyKey: '2:0', automatic: 40, human: 60 })
    expect(value()).toEqual({ automatic: 38, human: -38 })
    await act(async () => vi.advanceTimersByTime(2600))
    expect(value()).toBeNull()
    await render({ policyKey: '0:0', automatic: 2, human: 98 })
    expect(value()).toEqual({ automatic: -38, human: 38 })
  })
  it('compares the last settled selection after rapid pending changes', async () => {
    const { render, value } = await setup()
    await render({ ready: false, policyKey: '1:0' })
    await render({ ready: false, policyKey: '2:0' })
    expect(value()).toBeNull()
    await render({ policyKey: '2:0', automatic: 60, human: 40 })
    expect(value()).toEqual({ automatic: 60, human: -60 })
  })
  it('never compares counts across runs/scopes or invents deltas for missing counts', async () => {
    const { render, value } = await setup()
    await render({ identity: 'run-2:selected', ready: false })
    await render({ identity: 'run-2:selected', automatic: undefined, human: undefined })
    await render({ identity: 'run-2:selected', policyKey: '2:0', automatic: 4, human: 3 })
    expect(value()).toBeNull()
    await render({ identity: 'run-2:selected', policyKey: '1:0', automatic: 4, human: 3 })
    expect(value()).toBeNull()
  })
  it('keeps a selection badge for its full duration across same-policy background refreshes', async () => {
    vi.useFakeTimers()
    const { render, value } = await setup()
    await render({ policyKey: '2:0', automatic: 40, human: 60 })
    await act(async () => vi.advanceTimersByTime(800))
    await render({ policyKey: '2:0', automatic: 41, human: 59 })
    expect(value()).toEqual({ automatic: 40, human: -40 })
    await act(async () => vi.advanceTimersByTime(1799))
    expect(value()).toEqual({ automatic: 40, human: -40 })
    await act(async () => vi.advanceTimersByTime(1))
    expect(value()).toBeNull()
  })
  it('baselines a newly ready scope immediately so its first selection change animates', async () => {
    const { render, value } = await setup()
    await render({ identity: 'run-2:all', automatic: 10, human: 90 })
    expect(value()).toBeNull()
    await render({ identity: 'run-2:all', policyKey: '2:0', automatic: 40, human: 60 })
    expect(value()).toEqual({ automatic: 30, human: -30 })
  })
  it('keeps expiry measured from the selection through a loading refresh', async () => {
    vi.useFakeTimers()
    const { render, value } = await setup()
    await render({ policyKey: '2:0', automatic: 40, human: 60 })
    await act(async () => vi.advanceTimersByTime(500))
    await render({ ready: false, policyKey: '2:0', automatic: 40, human: 60 })
    expect(value()).toBeNull()
    await act(async () => vi.advanceTimersByTime(500))
    await render({ policyKey: '2:0', automatic: 40, human: 60 })
    expect(value()).toEqual({ automatic: 40, human: -40 })
    await act(async () => vi.advanceTimersByTime(1600))
    expect(value()).toBeNull()
  })
  it('does not carry an old badge into a new selection with unchanged or unavailable counts', async () => {
    const { render, value } = await setup()
    await render({ policyKey: '2:0', automatic: 40, human: 60 })
    await render({ policyKey: '2:1', automatic: 40, human: 60 })
    expect(value()).toBeNull()
    await render({ policyKey: '2:2', automatic: undefined, human: undefined })
    expect(value()).toBeNull()
    await render({ policyKey: '2:3', automatic: 50, human: 50 })
    expect(value()).toBeNull()
  })
  it('keeps changes readable without motion when reduced motion is requested', () => {
    const css = readFileSync(join(import.meta.dirname, 'remediation-impact-card.css'), 'utf8')
    expect(css).toMatch(/@media\(prefers-reduced-motion:reduce\)\{\.remediation-forecast-delta\{animation:none\}\}/)
  })
})
