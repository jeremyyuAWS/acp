import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement, act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'

// Proves Discover actually wires live getJobs()-derived worker counts into WorkerAvailability —
// mirrors processingStatusPanelIntegration.test.jsx's own SOURCE/DOM/unit split for AssessRunner.
// The point of this strip (unlike ProcessingStatusPanel, which only appears once a scan is
// active/terminal) is that it is visible the WHOLE time this tab is mounted — a user should be
// able to tell whether anything would pick up a job BEFORE they click "Re-scan".

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const getJobs = vi.fn()
const setWorkers = vi.fn()
vi.mock('./api.js', () => ({
  checkReadiness: vi.fn(() => Promise.resolve(null)),
  getScanInventory: vi.fn(() => Promise.resolve(null)),
  listScanDecisions: vi.fn(() => Promise.resolve([])),
  overrideLifecycleRecommendation: vi.fn(),
  acknowledgeScan: vi.fn(),
  unacknowledgeScan: vi.fn(),
  getJobs: (...a) => getJobs(...a),
  setWorkers: (...a) => setWorkers(...a),
}))

const { default: Discover } = await import('./Discover.jsx')

let container, root
const mount = async (props) => {
  ;({ container, root } = createTestRoot())
  await act(async () => {
    root.render(createElement(Discover, { sources: [], files: [], busy: false, onScan: () => {}, ...props }))
  })
  return container
}
const settle = async (n = 4) => { for (let k = 0; k < n; k++) await act(async () => { await new Promise((r) => setTimeout(r, 0)) }) }
afterEach(() => { unmountAll(); getJobs.mockReset(); setWorkers.mockReset() })

describe('Worker availability on Discover', () => {
  it('shows the live worker count and online status from getJobs(), even with no scan running', async () => {
    getJobs.mockResolvedValue({ workers: 3, worker_tier_alive: true, suggested_workers: 4, runtime_mode: 'auto' })
    const c = await mount({})
    await settle()
    expect(c.textContent).toMatch(/online/i)
    expect(c.textContent).toMatch(/3 workers available to pick up jobs/i)
  })

  it('shows offline with zero workers when the worker tier has no heartbeat', async () => {
    getJobs.mockResolvedValue({ workers: 0, worker_tier_alive: false, suggested_workers: 4, runtime_mode: 'auto' })
    const c = await mount({})
    await settle()
    expect(c.textContent).toMatch(/offline/i)
    expect(c.textContent).toMatch(/processing capacity is off/i)
  })

  it('starting workers from zero calls setWorkers with the suggested count and reflects the result', async () => {
    getJobs.mockResolvedValue({ workers: 0, worker_tier_alive: false, suggested_workers: 4, runtime_mode: 'auto' })
    setWorkers.mockResolvedValue({ workers: 4 })
    const c = await mount({})
    await settle()
    const plus = c.querySelector('button[aria-label="Add a worker"]')
    await act(async () => { plus.click() })
    await settle()
    expect(setWorkers).toHaveBeenCalledWith(4)
    expect(c.textContent).toMatch(/4 workers available to pick up jobs/i)
  })

  it('renders nothing from this strip while getJobs has not resolved yet', async () => {
    getJobs.mockReturnValue(new Promise(() => {}))
    const c = await mount({})
    await settle()
    expect(c.textContent).not.toMatch(/available to pick up jobs/i)
  })
})
