// QueuePanel rolling-window throughput meter.
//
// THE GAP. The historyRef accumulation (5-min window, delta-done/elapsed-min computation) and
// the rendered "N/min throughput" stat are not tested anywhere. A one-line arithmetic error
// would silently display a wrong rate — or always null — on Monitor's busiest view.
//
// Strategy: mock subscribeJobs so onData can be called directly with controlled data, and spy
// on Date.now so elapsed time is deterministic without involving real timers.
import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement, act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const mockSubscribeJobs = vi.fn()
vi.mock('./jobsFeed.js', () => ({
  subscribeJobs: (...a) => mockSubscribeJobs(...a),
  resetJobsFeed: vi.fn(),
}))
vi.mock('./api.js', () => ({
  getJobs: vi.fn(),
  setWorkers: vi.fn(),
  clearDeadJobs: vi.fn(),
  getWorkerReplicas: vi.fn(),
  getWorkerCapacity: vi.fn(),
}))
vi.mock('./Transparency.jsx', () => ({ TraceChip: () => null }))

const { default: QueuePanel } = await import('./QueuePanel.jsx')

const baseQ = { workers: 1, worker_tier_alive: false, runtime_mode: 'auto', jobs: [], stats: {} }
const meta = { fetchedAt: 0, ageMs: 0, stale: false }

afterEach(async () => { await unmountAll(); mockSubscribeJobs.mockReset(); vi.restoreAllMocks() })

const mount = async () => {
  const { container, root } = createTestRoot()
  await act(async () => { root.render(createElement(QueuePanel)) })
  return container
}

describe('QueuePanel throughput meter', () => {
  it('displays jobs/min after two onData calls with elapsed time', async () => {
    const t0 = 1_700_000_000_000
    const dateSpy = vi.spyOn(Date, 'now').mockReturnValue(t0)

    let onData = null
    mockSubscribeJobs.mockImplementation((filter, cb) => { onData = cb; return () => {} })

    const c = await mount()

    await act(async () => { onData({ ...baseQ, stats: { done: 0, running: 1 } }, meta) })
    dateSpy.mockReturnValue(t0 + 60_000)   // advance 1 minute before second sample
    await act(async () => { onData({ ...baseQ, stats: { done: 10, running: 1 } }, meta) })

    // rate = (10 − 0) / 1.0 min = 10 — uses Math.round (≥ 10), no decimal
    expect(c.textContent).toMatch(/10\/min/)
  })

  it('does not display throughput when only one sample has been collected', async () => {
    let onData = null
    mockSubscribeJobs.mockImplementation((filter, cb) => { onData = cb; return () => {} })

    const c = await mount()
    await act(async () => { onData({ ...baseQ, stats: { done: 5, running: 1 } }, meta) })

    expect(c.textContent).not.toMatch(/\/min/)
  })

  it('displays a one-decimal rate when throughput is below 10/min', async () => {
    const t0 = 1_700_000_000_000
    const dateSpy = vi.spyOn(Date, 'now').mockReturnValue(t0)

    let onData = null
    mockSubscribeJobs.mockImplementation((filter, cb) => { onData = cb; return () => {} })

    const c = await mount()

    await act(async () => { onData({ ...baseQ, stats: { done: 0, running: 1 } }, meta) })
    dateSpy.mockReturnValue(t0 + 60_000)
    await act(async () => { onData({ ...baseQ, stats: { done: 3, running: 1 } }, meta) })

    // rate = 3 / 1.0 = 3 — uses toFixed(1) because 3 < 10
    expect(c.textContent).toMatch(/3\.0\/min/)
  })

  it('prunes samples older than 5 minutes from the window', async () => {
    const t0 = 1_700_000_000_000
    const dateSpy = vi.spyOn(Date, 'now').mockReturnValue(t0)

    let onData = null
    mockSubscribeJobs.mockImplementation((filter, cb) => { onData = cb; return () => {} })

    const c = await mount()

    // First sample: will be 6 min old at the third call — outside the 5-min window.
    await act(async () => { onData({ ...baseQ, stats: { done: 0, running: 1 } }, meta) })

    // Second sample: 1 min after t0. At the third call it will be exactly 5 min old (within window).
    dateSpy.mockReturnValue(t0 + 60_000)
    await act(async () => { onData({ ...baseQ, stats: { done: 10, running: 1 } }, meta) })

    // Third sample: 6 minutes after t0.
    // Sample 1 (t0) is 6 min old → pruned. Sample 2 (t0+60s) is exactly 5 min old → kept.
    // hist = [sample2, sample3]; rate = (20−10) / 5.0 min = 2.0/min
    dateSpy.mockReturnValue(t0 + 6 * 60_000)
    await act(async () => { onData({ ...baseQ, stats: { done: 20, running: 1 } }, meta) })

    // The display must NOT be the stale 10/min from the prior pair — pruning triggered a
    // re-calculation anchored at sample 2, giving 2.0/min.
    expect(c.textContent).toMatch(/2\.0\/min/)
  })
})
