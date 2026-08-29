import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement, act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'

// Pure presentational tests for WorkerAvailability — the "how many workers are available to
// pick up scan jobs" strip extracted from AssessRunner's worker strip so Discover (and later
// Remediate) can show the same signal without re-deriving it. DOM wiring into Discover is
// covered separately in discoverWorkerAvailability.test.jsx.

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const { default: WorkerAvailability } = await import('./WorkerAvailability.jsx')

let container, root
const mount = async (props) => {
  ;({ container, root } = createTestRoot())
  await act(async () => { root.render(createElement(WorkerAvailability, props)) })
  return container
}
afterEach(unmountAll)

describe('WorkerAvailability', () => {
  it('renders nothing when no snapshot has loaded yet', async () => {
    const c = await mount({ snap: null })
    expect(c.textContent).toBe('')
  })

  it('shows the worker service online and the worker count', async () => {
    const c = await mount({ snap: { workers: 3, alive: true } })
    expect(c.textContent).toMatch(/online/i)
    expect(c.textContent).toMatch(/3 workers available to pick up jobs/i)
  })

  it('shows offline when the worker tier has no live heartbeat', async () => {
    const c = await mount({ snap: { workers: 0, alive: false } })
    expect(c.textContent).toMatch(/offline/i)
    expect(c.textContent).toMatch(/processing capacity is off/i)
  })

  it('does not say "online" and "0 workers available" in the same breath — that reads as a '
     + 'contradiction (found live 2026-08-29); zero capacity is said as one fact instead', async () => {
    const c = await mount({ snap: { workers: 0, alive: true } })
    expect(c.textContent).toMatch(/online/i)
    expect(c.textContent).toMatch(/processing capacity is off/i)
    expect(c.textContent).not.toMatch(/0 workers available/i)
  })

  it('singularizes "worker" for a count of one', async () => {
    const c = await mount({ snap: { workers: 1, alive: true } })
    expect(c.textContent).toMatch(/1 worker available to pick up jobs/i)
  })

  it('offers +/- controls that call onAdjust, and disables "-" at zero', async () => {
    const onAdjust = vi.fn()
    const c = await mount({ snap: { workers: 0, alive: false }, onAdjust })
    const minus = c.querySelector('button[aria-label="Remove a worker"]')
    const plus = c.querySelector('button[aria-label="Add a worker"]')
    expect(minus.disabled).toBe(true)
    expect(plus.disabled).toBe(false)
    await act(async () => { plus.click() })
    expect(onAdjust).toHaveBeenCalledWith(1)
  })

  it('disables both controls while an adjustment is in flight', async () => {
    const c = await mount({ snap: { workers: 2, alive: true }, busy: true, onAdjust: vi.fn() })
    const minus = c.querySelector('button[aria-label="Remove a worker"]')
    const plus = c.querySelector('button[aria-label="Add a worker"]')
    expect(minus.disabled).toBe(true)
    expect(plus.disabled).toBe(true)
  })

  it('shows the transient feedback message when set', async () => {
    const c = await mount({ snap: { workers: 4, alive: true }, msg: 'Starting 4 workers…', onAdjust: vi.fn() })
    expect(c.textContent).toMatch(/Starting 4 workers…/)
  })

  it('hides the +/- controls and explains externally-managed capacity for a distributed alive tier', async () => {
    const c = await mount({ snap: { workers: 8, alive: true, runtime_mode: 'distributed' }, onAdjust: vi.fn() })
    expect(c.querySelector('button[aria-label="Add a worker"]')).toBeFalsy()
    expect(c.textContent).toMatch(/managed by your deployment administrator/i)
  })

  it('does not render +/- controls when no onAdjust is given', async () => {
    const c = await mount({ snap: { workers: 2, alive: true } })
    expect(c.querySelector('button[aria-label="Add a worker"]')).toBeFalsy()
  })
})

// "online, but nothing is actually draining the queue" — the gap both #935 and #936 found live
// 2026-08-29 (a worker pool silently booted at zero threads; a Drive client with no socket
// timeout that could hang a claimed job forever). Both looked identical to "online" from the
// heartbeat alone; this is what makes that gap visible on screen instead of only in code.
describe('WorkerAvailability queue-stall warning', () => {
  it('is silent when alive and nothing is queued', async () => {
    const c = await mount({ snap: { workers: 4, alive: true, oldestQueuedCreatedAt: null } })
    expect(c.textContent).not.toMatch(/may not be actually claiming work/i)
  })

  it('is silent when alive and the oldest queued job is recent', async () => {
    const recent = new Date(Date.now() - 5_000).toISOString()
    const c = await mount({ snap: { workers: 4, alive: true, oldestQueuedCreatedAt: recent } })
    expect(c.textContent).not.toMatch(/may not be actually claiming work/i)
  })

  it('warns when alive but a queued job has waited past the stall threshold', async () => {
    const stale = new Date(Date.now() - 120_000).toISOString()
    const c = await mount({ snap: { workers: 4, alive: true, oldestQueuedCreatedAt: stale } })
    expect(c.textContent).toMatch(/reports online, but a queued job has been waiting 120s/i)
    expect(c.textContent).toMatch(/may not be actually claiming work/i)
    expect(c.querySelector('[role="alert"]')).toBeTruthy()
  })

  it('does not warn when offline — that is already a separate, visible problem', async () => {
    const stale = new Date(Date.now() - 120_000).toISOString()
    const c = await mount({ snap: { workers: 0, alive: false, oldestQueuedCreatedAt: stale } })
    expect(c.textContent).toMatch(/offline/i)
    expect(c.textContent).not.toMatch(/may not be actually claiming work/i)
  })
})
