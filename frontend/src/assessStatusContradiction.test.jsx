/**
 * Assess must not tell a user "nothing is processing them" while it also says a worker claimed
 * the job seconds ago. Reproduced first, fixed second.
 *
 * THE DIAGNOSIS THAT WAS WRONG. The obvious reading is a sticky `workersDown` flag: it is set once
 * at kickoff from the POST /assess response (AssessRunner.jsx ~line 422) and never re-derived from
 * the live /jobs feed. But `workersDown` cannot produce this screen, because the two messages sit
 * on opposite sides of it — the kickoff banner renders under `{workersDown && …}` and the
 * claimed-job line under `{jobInfo && !workersDown && …}`. A stuck `true` HIDES the claim line.
 *
 * THE ACTUAL COMBINATION. Both visible messages require `!workersDown`, and the no-local-workers
 * banner adds:
 *
 *     workerSnap.workers === 0 && !(runtime_mode === 'distributed' && alive)
 *
 * Two problems compound there.
 *
 * `workerSnap.workers` is the API container's OWN in-process pool, and in the split topology
 * (#113) that is 0 BY DESIGN — production's readyz reports `pool_size: 12, local_pool: 0`. So the
 * first half of the condition is permanently true in every real deployment, and the banner is held
 * back by nothing but `alive`.
 *
 * And `runtime_mode === 'distributed' && alive` conflates TOPOLOGY with HEALTH — the same defect
 * fixed in Discover.jsx and QueuePanel.jsx (#1059). `runtime_mode` says whether a separate worker
 * tier exists; `alive` says whether it is heartbeating this instant. A single stale heartbeat poll
 * flips `alive` false, the suppression lifts, and a banner about the LOCAL pool appears — telling
 * the user nothing is processing their documents while the line directly above it reports the job
 * claimed by a worker that is, in fact, running it.
 *
 * The banner also offers a "Start N workers" button wired to setWorkers(), which the worker-
 * provisioning PRD says must not be exposed to ordinary users at all.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement, act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const assessScan = vi.fn()
const getScan = vi.fn()
const getQueueJob = vi.fn()
const getJobs = vi.fn()
const getScanLive = vi.fn()
const getQueueEstimate = vi.fn()
const setWorkers = vi.fn()
vi.mock('./api.js', () => ({
  assessScan: (...a) => assessScan(...a),
  getScan: (...a) => getScan(...a),
  getQueueJob: (...a) => getQueueJob(...a),
  getJobs: (...a) => getJobs(...a),
  setWorkers: (...a) => setWorkers(...a),
  getCapability: vi.fn(() => Promise.resolve(null)),
  refreshScanDriveToken: vi.fn(() => Promise.resolve(null)),
  getScanTraces: vi.fn(() => Promise.resolve([])),
  getScanLive: (...a) => getScanLive(...a),
  getWorkerReplicas: vi.fn(() => Promise.resolve({ configured: false })),
  setWorkerReplicas: vi.fn(() => Promise.resolve({ configured: false })),
  getQueueEstimate: (...a) => getQueueEstimate(...a),
}))

import { resetJobsFeed } from './jobsFeed.js'
const { default: AssessRunner } = await import('./AssessRunner.jsx')

let container, root, errSpy
const mount = async (files) => {
  ;({ container, root } = createTestRoot())
  await act(async () => { root.render(createElement(AssessRunner, { files, runId: 's1' })) })
}
const settle = async (n = 8) => {
  for (let k = 0; k < n; k++) await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
}
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

/**
 * Production's real shape: a separate Azure-managed worker tier (so the API's own pool is 0), a
 * job a worker has genuinely CLAIMED, and a heartbeat that has momentarily gone stale.
 */
const SPLIT_TOPOLOGY_HEARTBEAT_STALE = {
  workers: 0,                    // the API container's local pool — 0 by design in split topology
  worker_tier_alive: false,      // one stale poll; the tier itself is running the job
  worker_heartbeat_age_s: 140,
  suggested_workers: 4,
  runtime_mode: 'distributed',
  stats: { running: 1, queued: 0, done: 0 },
  dead_letters: { by_type: {}, top_errors: [] },
  jobs: [],
}

beforeEach(() => {
  resetJobsFeed()
  assessScan.mockReset(); getScan.mockReset(); getQueueJob.mockReset()
  getJobs.mockReset(); getScanLive.mockReset(); getQueueEstimate.mockReset(); setWorkers.mockReset()
  getScanLive.mockResolvedValue({ queue: null })
  getQueueEstimate.mockResolvedValue({ available: false })
  errSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
  try { sessionStorage.clear() } catch { /* ignore */ }
})
afterEach(() => { errSpy.mockRestore(); unmountAll(); resetJobsFeed() })

/** Kickoff reports the tier ALIVE, so workersDown stays false — both messages stay eligible. */
async function runWithClaimedJobAndStaleHeartbeat() {
  assessScan.mockResolvedValue({ deferred: true, job_id: 'j1', workers: 0, worker_tier_alive: true })
  getScan.mockResolvedValue(NOTHING_SCORED)
  getQueueJob.mockResolvedValue({ id: 'j1', status: 'running', phase: 'assessing',
                                 locked_at: new Date(Date.now() - 9000).toISOString() })
  getJobs.mockResolvedValue(SPLIT_TOPOLOGY_HEARTBEAT_STALE)
  await mount([{ file: 'a.docx', status: 'discovered' }])
  await clickText('Assess')
  await settle()
}

describe('the Assess status contradiction', () => {
  it('does not claim nothing is processing while a worker is running the job', async () => {
    await runWithClaimedJobAndStaleHeartbeat()

    // `saysAWorkerHasIt` used to be computed here as `… === false || true`, which is the constant
    // `true` and was never asserted. Removed rather than fixed: assessTopologyHealth.test.jsx
    // asserts the claimed-job line for this same scenario, and against every wording of the
    // no-capacity claim rather than this one banner's sentence.
    expect(/nothing is processing them/i.test(text())).toBe(false)
  })

  it('does not offer a "Start N workers" control to an ordinary user', async () => {
    await runWithClaimedJobAndStaleHeartbeat()
    const startBtn = [...container.querySelectorAll('button')]
      .find((b) => /Start \d+ workers/i.test(b.textContent))
    expect(startBtn).toBeUndefined()
  })

  it('still warns when there genuinely is no worker tier — an in-process deployment', async () => {
    // The invariant. A deployment with no external tier and no local workers really does have
    // nothing to process the queue, and must still say so. This must pass before AND after.
    assessScan.mockResolvedValue({ deferred: true, job_id: 'j1', workers: 0, worker_tier_alive: true })
    getScan.mockResolvedValue(NOTHING_SCORED)
    getQueueJob.mockResolvedValue({ id: 'j1', status: 'queued' })
    getJobs.mockResolvedValue({ ...SPLIT_TOPOLOGY_HEARTBEAT_STALE,
                                runtime_mode: 'in-process', stats: { running: 0, queued: 1, done: 0 } })
    await mount([{ file: 'a.docx', status: 'discovered' }])
    await clickText('Assess')
    await settle()

    expect(text()).toMatch(/No local workers active/i)
  })

  it('shows one active state when scan evidence says files are processing', async () => {
    // Exact production overlap: the global snapshot still says zero local workers and the
    // stage estimate is one poll behind, while this scan's own live queue proves two files are
    // already executing. Execution evidence must win and redundant queue warnings disappear.
    assessScan.mockResolvedValue({ deferred: true, job_id: 'j1', workers: 0, worker_tier_alive: true })
    getScan.mockResolvedValue({ ...NOTHING_SCORED, run: { files: 63 } })
    getQueueJob.mockResolvedValue({ id: 'j1', status: 'running', phase: 'assessing' })
    getJobs.mockResolvedValue({ ...SPLIT_TOPOLOGY_HEARTBEAT_STALE,
                                runtime_mode: 'auto', worker_tier_alive: true,
                                worker_heartbeat_age_s: 4 })
    getScanLive.mockResolvedValue({
      queue: { in_flight: 2, queued: 61, workers: { busy: 2, max: 2 } },
    })
    getQueueEstimate.mockResolvedValue({ available: true, state: 'no_worker_available' })

    await mount([{ file: 'a.docx', status: 'discovered' }])
    await clickText('Assess')
    await settle()

    expect(container.querySelector('[aria-label="Processing status"]')?.textContent)
      .toMatch(/Assessing (documents|a\.docx)/i)
    expect(text()).toMatch(/2 processing/i)
    expect(text()).toMatch(/Worker service\s*active for this run/i)
    expect(text()).not.toMatch(/Waiting for a worker/i)
    expect(text()).not.toMatch(/No local workers active/i)
    expect(text()).not.toMatch(/No compatible worker/i)
    expect(text()).not.toMatch(/A worker is on this now/i)
  })
})
