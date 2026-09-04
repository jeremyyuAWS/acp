// QueuePanel "stalled?" per-job chip — DOM rendering path.
//
// THE GAP. isStalled() is tested as a pure function in workerStallSignal.test.js, but
// the QueuePanel DOM path that renders the yellow "stalled?" badge on a running job with
// no recent phase update is not covered. A wrong threshold or rendering condition would
// silently drop the stall indicator on Monitor's job list.
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { createElement, act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'
import { STALLED_AFTER_S } from './jobPhase.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const getJobs = vi.fn()
vi.mock('./api.js', () => ({
  getJobs: (...a) => getJobs(...a),
  setWorkers: vi.fn(),
  clearDeadJobs: vi.fn(),
  getWorkerReplicas: vi.fn(),
  getWorkerCapacity: vi.fn(),
}))
vi.mock('./Transparency.jsx', () => ({ TraceChip: () => null }))

import { resetJobsFeed } from './jobsFeed.js'
beforeEach(() => { resetJobsFeed() })

const { default: QueuePanel } = await import('./QueuePanel.jsx')

const baseQ = { workers: 1, worker_tier_alive: false, runtime_mode: 'auto' }

// dur = (updated_at − created_at) / 1000; must meet STALLED_AFTER_S to show the badge.
// Using epoch-based timestamps keeps the calculation deterministic and independent of Date.now().
const T0 = 0
const stalledJob = {
  id: 'j1', type: 'scan_file', status: 'running', scan_id: 's1',
  payload: JSON.stringify({ file: 'big-deck.pptx' }),
  attempts: 1,
  created_at: new Date(T0).toISOString(),
  updated_at: new Date(T0 + (STALLED_AFTER_S + 120) * 1000).toISOString(), // 2 min past threshold
}

const freshJob = {
  ...stalledJob,
  id: 'j2',
  created_at: new Date(T0).toISOString(),
  updated_at: new Date(T0 + 30_000).toISOString(), // 30 s duration — well under STALLED_AFTER_S
}

afterEach(async () => {
  await unmountAll()
  getJobs.mockReset()
})

const settle = async (n = 4) => {
  for (let k = 0; k < n; k++) await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
}

const mount = async () => {
  const { container, root } = createTestRoot()
  await act(async () => { root.render(createElement(QueuePanel)) })
  return container
}

describe('QueuePanel stalled? chip', () => {
  it('renders the stalled? badge when a running job exceeds the stall threshold', async () => {
    getJobs.mockResolvedValue({ ...baseQ, stats: { running: 1 }, jobs: [stalledJob] })
    const c = await mount()
    await settle()

    expect(c.textContent).toMatch(/stalled\?/)
  })

  it('tooltip on the stalled? badge mentions the duration in minutes', async () => {
    getJobs.mockResolvedValue({ ...baseQ, stats: { running: 1 }, jobs: [stalledJob] })
    const c = await mount()
    await settle()

    const badge = [...c.querySelectorAll('span')].find((s) => s.textContent.trim() === 'stalled?')
    expect(badge).toBeTruthy()
    expect(badge.title).toMatch(/minutes/)
  })

  it('does not render the stalled? badge for a running job within the threshold', async () => {
    getJobs.mockResolvedValue({ ...baseQ, stats: { running: 1 }, jobs: [freshJob] })
    const c = await mount()
    await settle()

    expect(c.textContent).not.toMatch(/stalled\?/)
  })

  it('does not render the stalled? badge for a done job whose duration exceeded the threshold', async () => {
    // A finished job with high duration is not stalled — isStalled() gates on status === 'running'.
    const doneJob = { ...stalledJob, id: 'j3', status: 'done' }
    getJobs.mockResolvedValue({ ...baseQ, stats: { done: 1 }, jobs: [doneJob] })
    const c = await mount()
    await settle()

    expect(c.textContent).not.toMatch(/stalled\?/)
  })
})
