import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement, act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'

// Real-time queue visibility for the deferred Assess model (2026-08-22). Before this,
// "Opening & assessing 0 of 148…" looked identical whether a worker was seconds from picking
// the job up or the worker tier was down entirely — POST /assess already returned
// workers/worker_tier_alive/job_id and nothing read them. These tests drive AssessRunner through
// the actual states GET /jobs/{id} can report and check the panel says something different for
// each of them, plus the "no workers at all" case surfaced at kickoff.

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const assessScan = vi.fn()
const getScan = vi.fn()
const getCapability = vi.fn()
const refreshScanDriveToken = vi.fn()
const getScanTraces = vi.fn()
const getQueueJob = vi.fn()
vi.mock('./api.js', () => ({
  assessScan: (...a) => assessScan(...a),
  getScan: (...a) => getScan(...a),
  getCapability: (...a) => getCapability(...a),
  refreshScanDriveToken: (...a) => refreshScanDriveToken(...a),
  getScanTraces: (...a) => getScanTraces(...a),
  getQueueJob: (...a) => getQueueJob(...a),
  getScanLive: vi.fn(() => Promise.resolve({ queue: null })),
  getJobs: vi.fn(() => Promise.resolve({ workers: 0, stats: { running: 0, queued: 0 }, worker_tier_alive: false })),
  setWorkers: vi.fn(() => Promise.resolve({ workers: 0 })),
  getWorkerReplicas: vi.fn(() => Promise.resolve({ configured: false })),
  setWorkerReplicas: vi.fn(() => Promise.resolve({ configured: false })),
}))

const { default: AssessRunner } = await import('./AssessRunner.jsx')

let container, root, errSpy
const mount = async (files) => {
  ;({ container, root } = createTestRoot())
  await act(async () => { root.render(createElement(AssessRunner, { files, runId: 's1' })) })
}
const settle = async (n = 6) => { for (let k = 0; k < n; k++) await act(async () => { await new Promise((r) => setTimeout(r, 0)) }) }
const clickText = async (t) => {
  const el = [...container.querySelectorAll('button')].find((b) => b.textContent.includes(t))
  await act(async () => { el.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
}
const text = () => container.textContent
const realErrors = () => errSpy.mock.calls.filter(([m]) => !String(m).includes('act(...)'))

beforeEach(() => {
  assessScan.mockReset(); getScan.mockReset(); refreshScanDriveToken.mockReset()
  getScanTraces.mockReset().mockResolvedValue([])
  getQueueJob.mockReset()
  getCapability.mockReset().mockResolvedValue(null)
  refreshScanDriveToken.mockResolvedValue(null)
  errSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
  try { sessionStorage.clear() } catch { /* ignore */ }
})
afterEach(() => { errSpy.mockRestore() })
afterEach(unmountAll)

const NOTHING_SCORED = {
  run: { files: 3 },
  files: [
    { file: 'a.docx', score: null, status: 'discovered' },
    { file: 'b.pdf', score: null, status: 'discovered' },
    { file: 'c.pptx', score: null, status: 'discovered' },
  ],
}

describe('no workers available, surfaced at kickoff', () => {
  it('shows a clear warning instead of a silent 0% when POST /assess reports no worker tier', async () => {
    assessScan.mockResolvedValue({ deferred: true, job_id: 'j1', workers: 0, worker_tier_alive: false })
    getScan.mockResolvedValue(NOTHING_SCORED)
    getQueueJob.mockResolvedValue({ id: 'j1', status: 'queued' })
    await mount([{ file: 'a.docx', status: 'discovered' }])
    await clickText('Assess')
    await settle()

    expect(text()).toMatch(/no worker capacity/i)
    expect(realErrors()).toEqual([])
  })

  it('does not warn when a worker tier is confirmed alive', async () => {
    assessScan.mockResolvedValue({ deferred: true, job_id: 'j1', workers: 0, worker_tier_alive: true })
    getScan.mockResolvedValue(NOTHING_SCORED)
    getQueueJob.mockResolvedValue({ id: 'j1', status: 'queued' })
    await mount([{ file: 'a.docx', status: 'discovered' }])
    await clickText('Assess')
    await settle()

    expect(text()).not.toMatch(/no worker capacity/i)
  })
})

describe('real queue status while nothing has scored yet', () => {
  it('says "queued — waiting for a worker" when the job has not been claimed', async () => {
    assessScan.mockResolvedValue({ deferred: true, job_id: 'j1', workers: 1, worker_tier_alive: true })
    getScan.mockResolvedValue(NOTHING_SCORED)
    getQueueJob.mockResolvedValue({ id: 'j1', status: 'queued' })
    await mount([{ file: 'a.docx', status: 'discovered' }])
    await clickText('Assess')
    await settle()

    expect(text()).toMatch(/waiting for a worker/i)
    expect(realErrors()).toEqual([])
  })

  it('says a worker is on it, and shows the phase, once claimed', async () => {
    assessScan.mockResolvedValue({ deferred: true, job_id: 'j1', workers: 1, worker_tier_alive: true })
    getScan.mockResolvedValue(NOTHING_SCORED)
    getQueueJob.mockResolvedValue({
      id: 'j1', status: 'running', phase: 'opening a.docx',
      locked_at: new Date(Date.now() - 5000).toISOString(),
    })
    await mount([{ file: 'a.docx', status: 'discovered' }])
    await clickText('Assess')
    await settle()

    expect(text()).toMatch(/a worker is on this now/i)
    expect(text()).toContain('opening a.docx')
    expect(realErrors()).toEqual([])
  })

  it('surfaces a dead job\'s error instead of leaving the bar at a silent 0%', async () => {
    assessScan.mockResolvedValue({ deferred: true, job_id: 'j1', workers: 1, worker_tier_alive: true })
    getScan.mockResolvedValue(NOTHING_SCORED)
    getQueueJob.mockResolvedValue({ id: 'j1', status: 'dead', error: 'boom: connection reset' })
    await mount([{ file: 'a.docx', status: 'discovered' }])
    await clickText('Assess')
    await settle()

    expect(text()).toMatch(/failed repeatedly/i)
    expect(text()).toContain('boom: connection reset')
    expect(realErrors()).toEqual([])
  })

  it('stops polling the job once real per-file progress exists', async () => {
    assessScan.mockResolvedValue({ deferred: true, job_id: 'j1', workers: 1, worker_tier_alive: true })
    getScan.mockResolvedValue({
      run: { files: 2 },
      files: [{ file: 'done.pdf', score: 90 }, { file: 'b.docx', score: null }],
    })
    getQueueJob.mockResolvedValue({ id: 'j1', status: 'running' })
    await mount([{ file: 'b.docx', status: 'discovered' }])
    await clickText('Assess')
    await settle()

    // Real progress (a scored file) answers the question the job-status line exists for —
    // it must not keep asserting "a worker is on this" once the file list already proves it.
    expect(text()).not.toMatch(/a worker is on this now/i)
    expect(realErrors()).toEqual([])
  })
})
