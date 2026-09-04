// QueuePanel "Remediating <filename>" live badge.
//
// THE GAP. The top-of-panel pulse shown when a remediate_file job is running is the only
// operator-facing feedback that remediation is actively happening. The remJob/remFile
// derivation and the aria-live badge rendering are untested — a broken filter condition
// would silently drop the indicator.
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { createElement, act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'

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
const now = new Date().toISOString()

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

describe('QueuePanel remediation live badge', () => {
  it('shows the filename when a remediate_file job is running', async () => {
    getJobs.mockResolvedValue({
      ...baseQ,
      stats: { running: 1 },
      jobs: [{
        id: 'r1', type: 'remediate_file', status: 'running', scan_id: 's1',
        payload: JSON.stringify({ file: 'annual-report.pptx' }),
        created_at: now, updated_at: now, attempts: 1,
      }],
    })
    const c = await mount()
    await settle()

    expect(c.textContent).toMatch(/Remediating/)
    expect(c.textContent).toMatch(/annual-report\.pptx/)
  })

  it('badge element carries aria-live="polite"', async () => {
    getJobs.mockResolvedValue({
      ...baseQ,
      stats: { running: 1 },
      jobs: [{
        id: 'r1', type: 'remediate_file', status: 'running', scan_id: 's1',
        payload: JSON.stringify({ file: 'report.pptx' }),
        created_at: now, updated_at: now, attempts: 1,
      }],
    })
    const c = await mount()
    await settle()

    // The remediation badge should be an aria-live region in the panel header.
    const live = [...c.querySelectorAll('[aria-live="polite"]')]
      .find((el) => el.textContent.includes('Remediating'))
    expect(live).toBeTruthy()
  })

  it('omits the badge when no remediate_file job is running', async () => {
    getJobs.mockResolvedValue({
      ...baseQ,
      stats: { running: 1 },
      jobs: [{
        id: 'j1', type: 'scan_file', status: 'running', scan_id: 's1',
        payload: JSON.stringify({ file: 'deck.pptx' }),
        created_at: now, updated_at: now, attempts: 1,
      }],
    })
    const c = await mount()
    await settle()

    expect(c.textContent).not.toMatch(/Remediating/)
  })

  it('omits the badge when the remediate_file job is done (not running)', async () => {
    getJobs.mockResolvedValue({
      ...baseQ,
      stats: { done: 1 },
      jobs: [{
        id: 'r1', type: 'remediate_file', status: 'done', scan_id: 's1',
        payload: JSON.stringify({ file: 'report.pptx' }),
        created_at: now, updated_at: now, attempts: 1,
      }],
    })
    const c = await mount()
    await settle()

    expect(c.textContent).not.toMatch(/Remediating/)
  })
})
