/**
 * Assess must not turn a stale heartbeat into a claim that nothing is processing, and must not
 * offer an ordinary user a way to provision workers.
 *
 * WHY THIS EXISTS WHEN #1060 ALREADY FIXED "THIS". #1060 fixed ONE of three places in this file
 * that conflated TOPOLOGY (is there a separate worker tier?) with HEALTH (is it heartbeating this
 * instant?), and its tests asserted against the one string it was changing:
 *
 *     /nothing is processing them/i      the no-local-workers BANNER
 *     /Start \d+ workers/i               that banner's button, which carried a count
 *
 * Both passed. Neither could fail for the other two sites, because those render different words.
 * `ProcessingStatusPanel` — rendered ABOVE the fixed banner, from `noCapacity`, which still read
 * `!(runtime_mode === 'distributed' && alive)` — says "no worker is currently online to process
 * them" and offers a button reading "Start workers", no count. So the screenshot reproduced
 * unchanged after the fix that was supposed to address it, and the suite stayed green.
 *
 * That is the failure CLAUDE.md names: an assertion pinned to the exact text of the thing being
 * changed is a check about the author's intent, not about the screen. These tests assert on the
 * CLAIM ("is anything telling the user no worker is available?") and on the CONTROL ("is any
 * worker-provisioning affordance reachable?"), across every wording either can take.
 *
 * THE THREE SITES, all on 11406200 before this change:
 *   - `noCapacity`      (ProcessingStatusPanel)  !(distributed && alive)
 *   - `externallyManaged` (worker strip)          distributed && alive  → ± concurrency buttons
 *   - the banner        (#1060)                   distributed only      ← already correct
 *
 * AND THE THIRD STATE. `worker_tier_alive` is a boolean, so it cannot distinguish "the tier beat
 * 140s ago and is late" from "no worker has EVER beaten" — store.py's worker_tier_status() returns
 * age_s: null for the latter precisely because they "read differently in an alert". AssessRunner
 * discarded both the age and the timestamp and rendered a hard binary, so a deployment whose
 * worker tier has never started read as a confident "offline", and any absence of data read as a
 * definite claim. Health here now has three states, and the unknown one says so.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement, act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const assessScan = vi.fn()
const getScan = vi.fn()
const getQueueJob = vi.fn()
const setWorkers = vi.fn()

// Mutable so a test can change what the NEXT poll observes — heartbeat loss and recovery are
// transitions, and asserting them from two separate mounts would not prove the live feed moves.
let jobsPayload = null
const getJobs = vi.fn(() => Promise.resolve(jobsPayload))

vi.mock('./api.js', () => ({
  assessScan: (...a) => assessScan(...a),
  getScan: (...a) => getScan(...a),
  getQueueJob: (...a) => getQueueJob(...a),
  getJobs: (...a) => getJobs(...a),
  setWorkers: (...a) => setWorkers(...a),
  getCapability: vi.fn(() => Promise.resolve(null)),
  refreshScanDriveToken: vi.fn(() => Promise.resolve(null)),
  getScanTraces: vi.fn(() => Promise.resolve([])),
  getScanLive: vi.fn(() => Promise.resolve({ queue: null })),
  getWorkerReplicas: vi.fn(() => Promise.resolve({ configured: false })),
  setWorkerReplicas: vi.fn(() => Promise.resolve({ configured: false })),
  getQueueEstimate: vi.fn(() => Promise.resolve({ available: false })),
}))

import { resetJobsFeed } from './jobsFeed.js'
const { default: AssessRunner } = await import('./AssessRunner.jsx')

let container, root, errSpy

const NOTHING_SCORED = {
  run: { files: 3 },
  files: [
    { file: 'alpha.docx', score: null, status: 'discovered' },
    { file: 'beta.pdf', score: null, status: 'discovered' },
    { file: 'gamma.pptx', score: null, status: 'discovered' },
  ],
}

/** Production's real shape (#113): a separate Azure-managed worker tier, so the API's own pool
 *  is 0 by design. readyz reports `pool_size: 12, local_pool: 0`. */
const SPLIT_TOPOLOGY = {
  workers: 0,
  worker_tier_alive: true,
  worker_heartbeat_age_s: 4,
  worker_heartbeat_at: new Date().toISOString(),
  suggested_workers: 4,
  runtime_mode: 'distributed',
  stats: { running: 1, queued: 0, done: 0 },
  dead_letters: { by_type: {}, top_errors: [] },
  jobs: [],
}
/** One poll lands late. The tier is still running the job — `stats.running` says so. */
const HEARTBEAT_STALE = { ...SPLIT_TOPOLOGY, worker_tier_alive: false, worker_heartbeat_age_s: 140 }
/** No worker has EVER beaten: store.py returns age_s null here, a different fact from "late". */
const HEARTBEAT_NEVER = { ...SPLIT_TOPOLOGY, worker_tier_alive: false,
                          worker_heartbeat_age_s: null, worker_heartbeat_at: null }
/** A genuine in-process deployment with nothing to run the queue. The warning is CORRECT here. */
const LOCAL_ONLY_NO_WORKERS = { ...SPLIT_TOPOLOGY, worker_tier_alive: false,
                                worker_heartbeat_age_s: null, worker_heartbeat_at: null,
                                runtime_mode: 'in-process',
                                stats: { running: 0, queued: 1, done: 0 } }

const text = () => container.textContent

/** Every wording any surface in this file uses to claim capacity is unavailable. Asserting the
 *  claim rather than one banner's sentence is the whole point — see the header. */
const claimsNothingIsProcessing = () =>
  /nothing is processing them/i.test(text())
  || /no worker is currently online/i.test(text())
  || /No local workers active/i.test(text())

/** Every worker-provisioning affordance, by ROLE and LABEL rather than by text, so a reworded
 *  button cannot slip past. WorkerReplicaControl is deliberately not counted: it is admin-gated
 *  (`me?.is_admin`) and renders nothing unless Azure replica control is configured, which is the
 *  authorized-operator path the PRD keeps. */
const provisioningControls = () => [...container.querySelectorAll('button')].filter((b) => {
  const label = `${b.getAttribute('aria-label') || ''} ${b.textContent || ''}`
  return /start\s+(\d+\s+)?workers?/i.test(label)
      || /(add|remove) an in-process worker/i.test(label)
})

beforeEach(() => {
  resetJobsFeed()
  assessScan.mockReset(); getScan.mockReset(); getQueueJob.mockReset()
  getJobs.mockClear(); setWorkers.mockReset()
  jobsPayload = SPLIT_TOPOLOGY
  errSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
  try { sessionStorage.clear() } catch { /* ignore */ }
})
afterEach(() => { errSpy.mockRestore(); unmountAll(); resetJobsFeed(); vi.useRealTimers() })

const flush = async (n = 8) => {
  for (let k = 0; k < n; k++) await act(async () => { await Promise.resolve() })
}

/**
 * Kickoff reports the tier alive, so `workersDown` stays false and every message below stays
 * eligible — a stuck `workersDown` would HIDE the claimed-job line and mask what is being tested.
 */
async function startRun(initial) {
  jobsPayload = initial
  assessScan.mockResolvedValue({ deferred: true, job_id: 'j1', workers: 0, worker_tier_alive: true })
  getScan.mockResolvedValue(NOTHING_SCORED)
  getQueueJob.mockResolvedValue({ id: 'j1', status: 'running', phase: 'assessing',
                                  locked_at: new Date(Date.now() - 9000).toISOString() })
  ;({ container, root } = createTestRoot())
  vi.useFakeTimers({ shouldAdvanceTime: true })
  await act(async () => {
    root.render(createElement(AssessRunner, { files: [{ file: 'alpha.docx', status: 'discovered' }],
                                             runId: 's1' }))
  })
  const btn = [...container.querySelectorAll('button')].find((b) => /Assess/i.test(b.textContent))
  await act(async () => { btn.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
  await flush()
}

/** The worker strip polls /jobs every 10s. Advance past one interval and let it settle. */
async function nextPoll(payload) {
  jobsPayload = payload
  await act(async () => { vi.advanceTimersByTime(11_000) })
  await flush()
}

describe('Assess: topology, health, and who may provision workers', () => {
  // ── the screenshot, in full ────────────────────────────────────────────────────────────────
  describe('the reported screen: distributed tier, zero local workers, stale heartbeat, job claimed', () => {
    it('makes no claim that nothing is processing the documents', async () => {
      await startRun(HEARTBEAT_STALE)
      expect(claimsNothingIsProcessing()).toBe(false)
    })

    it('offers no worker-provisioning control to an ordinary user', async () => {
      await startRun(HEARTBEAT_STALE)
      expect(provisioningControls().map((b) => b.textContent.trim())).toEqual([])
    })

    it('still reports the job a worker has claimed', async () => {
      await startRun(HEARTBEAT_STALE)
      expect(text()).toMatch(/A worker is on this now/i)
    })

    it('shows the health as unresponsive rather than silently reading as healthy', async () => {
      await startRun(HEARTBEAT_STALE)
      expect(text()).toMatch(/not responding/i)
      expect(text()).not.toMatch(/Worker service\s*online/i)
    })
  })

  // ── the transition, both directions ────────────────────────────────────────────────────────
  describe('heartbeat loss and recovery', () => {
    it('goes from online to not responding and back, without ever claiming no capacity', async () => {
      await startRun(SPLIT_TOPOLOGY)
      expect(text()).toMatch(/Worker service\s*online/i)
      expect(claimsNothingIsProcessing()).toBe(false)

      await nextPoll(HEARTBEAT_STALE)                       // loss
      expect(text()).toMatch(/not responding/i)
      expect(claimsNothingIsProcessing()).toBe(false)
      expect(provisioningControls()).toEqual([])

      await nextPoll(SPLIT_TOPOLOGY)                        // recovery
      expect(text()).toMatch(/Worker service\s*online/i)
      expect(text()).not.toMatch(/not responding/i)
      expect(claimsNothingIsProcessing()).toBe(false)
    })
  })

  // ── the third state ───────────────────────────────────────────────────────────────────────
  describe('a heartbeat that never arrived', () => {
    it('reads as unknown, not as a confident offline and not as healthy', async () => {
      await startRun(HEARTBEAT_NEVER)
      expect(text()).toMatch(/unknown/i)
      expect(text()).not.toMatch(/Worker service\s*online/i)
      expect(claimsNothingIsProcessing()).toBe(false)
    })
  })

  // ── the invariant: this must pass BEFORE and AFTER ────────────────────────────────────────
  describe('a genuine in-process deployment with no workers', () => {
    it('still warns that nothing is processing, because nothing is', async () => {
      getQueueJob.mockResolvedValue({ id: 'j1', status: 'queued' })
      await startRun(LOCAL_ONLY_NO_WORKERS)
      expect(text()).toMatch(/No local workers active/i)
    })

    it('points at Settings rather than offering the user a control', async () => {
      getQueueJob.mockResolvedValue({ id: 'j1', status: 'queued' })
      await startRun(LOCAL_ONLY_NO_WORKERS)
      expect(text()).toMatch(/Settings/i)
      expect(provisioningControls()).toEqual([])
    })
  })
})
