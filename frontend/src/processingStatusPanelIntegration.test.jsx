import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement, act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'

// Proves AssessRunner actually wires live getJobs()-derived signals into ProcessingStatusPanel —
// deriveProcessingState and ProcessingStatusPanel are both covered on their own (processingState.test.js,
// processingStatusPanel.test.jsx); this is the third leg, matching this codebase's own
// SOURCE-vs-DOM-vs-unit split elsewhere (see discoveryResultsWiring.test.jsx's own header comment
// for why neither half alone would catch a dropped wire-up).

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const assessScan = vi.fn()
const getScan = vi.fn()
const getJobs = vi.fn()
vi.mock('./api.js', () => ({
  assessScan: (...a) => assessScan(...a),
  getScan: (...a) => getScan(...a),
  getCapability: vi.fn(() => Promise.resolve(null)),
  refreshScanDriveToken: vi.fn(() => Promise.resolve(null)),
  getScanTraces: vi.fn(() => Promise.resolve([])),
  getQueueJob: vi.fn(() => Promise.resolve({ id: 'j1', status: 'queued' })),
  getScanLive: vi.fn(() => Promise.resolve({ queue: null })),
  getJobs: (...a) => getJobs(...a),
  setWorkers: vi.fn(() => Promise.resolve({ workers: 0 })),
  getWorkerReplicas: vi.fn(() => Promise.resolve({ configured: false })),
  setWorkerReplicas: vi.fn(() => Promise.resolve({ configured: false })),
}))

const { default: AssessRunner } = await import('./AssessRunner.jsx')

let container, root
const mount = async (files, props = {}) => {
  ;({ container, root } = createTestRoot())
  await act(async () => { root.render(createElement(AssessRunner, { files, runId: 's1', ...props })) })
}
const settle = async (n = 8) => { for (let k = 0; k < n; k++) await act(async () => { await new Promise((r) => setTimeout(r, 10)) }) }
const clickText = async (t) => {
  const el = [...container.querySelectorAll('button')].find((b) => b.textContent.includes(t))
  await act(async () => { el.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
}
const text = () => container.textContent

const NOTHING_SCORED = {
  run: { files: 3 },
  files: [
    { file: 'a.docx', score: null, status: 'discovered' },
    { file: 'b.pdf', score: null, status: 'discovered' },
    { file: 'c.pptx', score: null, status: 'discovered' },
  ],
}

beforeEach(() => {
  assessScan.mockReset(); getScan.mockReset(); getJobs.mockReset()
})
afterEach(unmountAll)

describe('ProcessingStatusPanel wired into AssessRunner from live getJobs() signals', () => {
  it('shows "Waiting for a worker" when getJobs reports zero local workers and no live tier', async () => {
    assessScan.mockResolvedValue({ deferred: true, job_id: 'j1', workers: 1, worker_tier_alive: true })
    getScan.mockResolvedValue(NOTHING_SCORED)
    getJobs.mockResolvedValue({ workers: 0, stats: { running: 0, queued: 3 }, worker_tier_alive: false, runtime_mode: 'auto' })
    await mount([{ file: 'a.docx', status: 'discovered' }])
    await clickText('Assess')
    await settle()

    expect(text()).toMatch(/waiting for a worker/i)
    expect(text()).toMatch(/pickup time not available/i)
  })

  it('offers a "View in Monitor" link that calls the onViewMonitor prop', async () => {
    const onViewMonitor = vi.fn()
    assessScan.mockResolvedValue({ deferred: true, job_id: 'j1', workers: 1, worker_tier_alive: true })
    getScan.mockResolvedValue(NOTHING_SCORED)
    getJobs.mockResolvedValue({ workers: 1, stats: { running: 1, queued: 2 }, worker_tier_alive: true, runtime_mode: 'auto' })
    await mount([{ file: 'a.docx', status: 'discovered' }], { onViewMonitor })
    await clickText('Assess')
    await settle()

    const link = [...container.querySelectorAll('button')].find((b) => b.textContent.includes('View in Monitor'))
    expect(link, 'no View in Monitor link rendered').toBeTruthy()
    await act(async () => { link.click() })
    expect(onViewMonitor).toHaveBeenCalledTimes(1)
  })
})
