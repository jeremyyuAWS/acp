/**
 * Three rules about what this screen is allowed to imply, all of which it broke.
 *
 *   1. A SERVICE HEARTBEAT IS NOT JOB PROGRESS. `worker_tier_alive` means the worker process
 *      answered within 120s. It says nothing about this job — and a worker crash-looping on one
 *      document (2026-08-30: exit 139, restarts at 3:01, 3:12 and 3:23pm PDT) answers freshly
 *      between restarts while completing nothing. store.py's oldest_queued_job docstring already
 *      makes the argument: "a fresh heartbeat proves the worker CONTAINER is up, not that
 *      anything is actually claiming work."
 *
 *   2. A TERMINAL JOB MUST SAY AUTOMATIC RETRIES HAVE STOPPED. 'dead' said "stopped retrying";
 *      'cancelled' had NO BRANCH AT ALL and fell through to `Running · 4m`, reporting elapsed
 *      time for work nobody was doing.
 *
 *   3. TERMINAL STATE OUTRANKS GREEN SERVICE HEALTH. The strip renders independently of the job
 *      line, so a dead run sat directly beneath a green "● Worker service online" — the same
 *      shape of contradiction as the banner fixed in #1060 and #1066, one surface further on.
 *
 * And the corollary: with no evidence either way, the screen says PROGRESS NOT CONFIRMED. It does
 * not invent a cause. The client cannot distinguish a slow first document from a wedged parser
 * from a queue not yet reached, and guessing is what produced "nothing is processing them" over a
 * job a worker was running.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement, act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const assessScan = vi.fn()
const getScan = vi.fn()
const getQueueJob = vi.fn()
const getJobs = vi.fn()
const getScanLive = vi.fn(() => Promise.resolve({ queue: null }))

vi.mock('./api.js', () => ({
  assessScan: (...a) => assessScan(...a),
  getScan: (...a) => getScan(...a),
  getQueueJob: (...a) => getQueueJob(...a),
  getJobs: (...a) => getJobs(...a),
  setWorkers: vi.fn(),
  getCapability: vi.fn(() => Promise.resolve(null)),
  refreshScanDriveToken: vi.fn(() => Promise.resolve(null)),
  getScanTraces: vi.fn(() => Promise.resolve([])),
  getScanLive: (...a) => getScanLive(...a),
  getWorkerReplicas: vi.fn(() => Promise.resolve({ configured: false })),
  setWorkerReplicas: vi.fn(() => Promise.resolve({ configured: false })),
  getQueueEstimate: vi.fn(() => Promise.resolve({ available: false })),
}))

import { resetJobsFeed } from './jobsFeed.js'
const { default: AssessRunner, isTerminalJob, progressIsConfirmed } =
  await import('./AssessRunner.jsx')

let container, root, errSpy

const NOTHING_SCORED = {
  run: { files: 3 },
  files: [
    { file: 'alpha.docx', score: null, status: 'discovered' },
    { file: 'beta.pdf', score: null, status: 'discovered' },
    { file: 'gamma.pptx', score: null, status: 'discovered' },
  ],
}

/** The tier is answering: fresh heartbeat, distributed topology, healthy by every signal here. */
const TIER_HEALTHY = {
  workers: 0,
  worker_tier_alive: true,
  worker_heartbeat_age_s: 3,
  worker_heartbeat_at: new Date().toISOString(),
  suggested_workers: 4,
  runtime_mode: 'distributed',
  stats: { running: 0, queued: 0, done: 0 },
  dead_letters: { by_type: {}, top_errors: [] },
  jobs: [],
}

const text = () => container.textContent
const healthEl = () => container.querySelector('.assesshealth')

const settle = async (n = 8) => {
  for (let k = 0; k < n; k++) await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
}

/** Start a run whose job the backend reports in `status`, with the tier healthy throughout. */
async function runWithJobStatus(status, extra = {}) {
  assessScan.mockResolvedValue({ deferred: true, job_id: 'j1', workers: 0, worker_tier_alive: true })
  getScan.mockResolvedValue(NOTHING_SCORED)
  getQueueJob.mockResolvedValue({ id: 'j1', status, ...extra })
  getJobs.mockResolvedValue(TIER_HEALTHY)
  ;({ container, root } = createTestRoot())
  await act(async () => {
    root.render(createElement(AssessRunner, { files: [{ file: 'alpha.docx', status: 'discovered' }],
                                             runId: 's1' }))
  })
  const btn = [...container.querySelectorAll('button')].find((b) => /Assess/i.test(b.textContent))
  await act(async () => { btn.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
  await settle()
}

beforeEach(() => {
  resetJobsFeed()
  assessScan.mockReset(); getScan.mockReset(); getQueueJob.mockReset(); getJobs.mockReset()
  getScanLive.mockReset(); getScanLive.mockResolvedValue({ queue: null })
  errSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
  try { sessionStorage.clear() } catch { /* ignore */ }
})
afterEach(() => { errSpy.mockRestore(); unmountAll(); resetJobsFeed() })

describe('a terminal job outranks a healthy service', () => {
  it('says automatic retries have stopped when the job is dead', async () => {
    await runWithJobStatus('dead')
    expect(text()).toMatch(/automatic retries have stopped/i)
  })

  it('says automatic retries have stopped when the job was cancelled', async () => {
    // Had no branch at all: 'cancelled' fell through to the running case and reported elapsed
    // time, so a stopped run read as one still under way.
    await runWithJobStatus('cancelled')
    expect(text()).toMatch(/automatic retries have stopped/i)
  })

  it('does not report a cancelled run as still running', async () => {
    await runWithJobStatus('cancelled')
    expect(text()).not.toMatch(/A worker is on this now/i)
    expect(text()).toMatch(/this run was stopped/i)
  })

  it('does not show a green service light beside a terminal job', async () => {
    await runWithJobStatus('dead')
    const el = healthEl()
    expect(el).toBeTruthy()
    // #1a7f37 is the ok tone. jsdom serialises it as rgb().
    expect(el.style.color).not.toBe('rgb(26, 127, 55)')
    expect(el.textContent).toMatch(/but this run has stopped/i)
  })

  it('still shows the green light for a healthy service on a live run', async () => {
    // The invariant. Suppressing the light whenever it might be awkward would be its own
    // dishonesty; it is outranked only by a TERMINAL job. Passes before AND after.
    await runWithJobStatus('running', { phase: 'assessing' })
    expect(healthEl().style.color).toBe('rgb(26, 127, 55)')
    expect(text()).not.toMatch(/but this run has stopped/i)
  })
})

describe('a heartbeat is not progress', () => {
  it('says progress is not confirmed when nothing has completed and nothing is in flight', async () => {
    // The tier is answering with a 3s heartbeat and the job is claimed. Neither is evidence that
    // THIS run is moving, which is exactly how the crash-loop looked from here.
    await runWithJobStatus('running', { phase: 'assessing' })
    expect(text()).toMatch(/progress not confirmed/i)
  })

  it('invents no cause for the missing progress', async () => {
    await runWithJobStatus('running', { phase: 'assessing' })
    expect(text()).not.toMatch(/crash|corrupt|stuck|wedged|failing|restart/i)
  })

  it('drops the caveat once the backend reports work in flight for THIS scan', async () => {
    // Driven through GET /scans/{id}/live rather than by seeding a scored file, because
    // `progress` comes from the component's own poll and a fixture cannot set it from outside —
    // the first version of this test tried and measured a render where progress was still 0.
    // `workers.busy` is scan-scoped, which is exactly the kind of evidence a heartbeat is not.
    getScanLive.mockResolvedValue({ queue: { in_flight: 2, queued: 1, workers: { busy: 2, max: 12 } } })
    await runWithJobStatus('running', { phase: 'assessing' })
    expect(text()).toMatch(/2 processing/)
    expect(text()).not.toMatch(/progress not confirmed/i)
  })

  it('never contradicts a terminal job by also questioning its progress', async () => {
    await runWithJobStatus('dead')
    expect(text()).not.toMatch(/progress not confirmed/i)
  })
})

describe('the derivations themselves', () => {
  it('treats dead and cancelled as terminal, and nothing else', () => {
    expect(isTerminalJob('dead')).toBe(true)
    expect(isTerminalJob('cancelled')).toBe(true)
    for (const s of ['queued', 'running', 'done', undefined, null, '']) {
      expect(isTerminalJob(s)).toBe(false)
    }
  })

  it('counts a completed document or an in-flight one as progress, and a heartbeat as neither', () => {
    expect(progressIsConfirmed({ completed: 1, inFlight: 0 })).toBe(true)
    expect(progressIsConfirmed({ completed: 0, inFlight: 2 })).toBe(true)
    expect(progressIsConfirmed({ completed: 0, inFlight: 0 })).toBe(false)
    expect(progressIsConfirmed()).toBe(false)
  })
})
