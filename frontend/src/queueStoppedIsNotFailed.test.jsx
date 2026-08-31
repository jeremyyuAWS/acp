/* A job someone STOPPED is not a job that FAILED, and the queue panel must not say it is.
 *
 * WHAT WAS WRONG. `_end_running_scan` — the path both Stop and supersede route through — marks
 * every outstanding job of the scan 'dead'. This panel gated its red banner on `stats.dead`, the
 * raw status count, and captioned it "N jobs failed permanently". So pressing Stop on a
 * 200-document scan produced a red incident banner announcing 200 permanent failures, a
 * red "200 dead-letter" chip beside it, and — because the reason string comes from the jobs'
 * `last_error`, which a stop does not write — the fallback line "See server logs for details."
 * about a button the user had just pressed themselves.
 *
 * The panel had no way to know better: 'dead' means both things and nothing else was exposed.
 * store.dead_letter_breakdown now separates them (it reads `cancel_requested_at` alongside the
 * status) and returns `failed` and `stopped` counts. These tests pin the panel reading them.
 *
 * The fallback is deliberate and tested below: when `dead_letters.failed` is absent — an older
 * API behind a newer bundle, which the app's blue-green cutover can produce for a few seconds —
 * the panel uses the unsplit count, exactly as it did before. Over-attributing a stop for a few
 * seconds is a smaller harm than silently dropping a real failure from an incident view.
 */
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { createElement, act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const getJobs = vi.fn()
const setWorkers = vi.fn()
const clearDeadJobs = vi.fn()
const getWorkerReplicas = vi.fn()
const getWorkerCapacity = vi.fn()
vi.mock('./api.js', () => ({
  getJobs: (...a) => getJobs(...a),
  setWorkers: (...a) => setWorkers(...a),
  clearDeadJobs: (...a) => clearDeadJobs(...a),
  getWorkerReplicas: (...a) => getWorkerReplicas(...a),
  getWorkerCapacity: (...a) => getWorkerCapacity(...a),
}))

import { resetJobsFeed } from './jobsFeed.js'
beforeEach(() => { resetJobsFeed() })

const { default: QueuePanel } = await import('./QueuePanel.jsx')

const mount = async () => {
  const { container, root } = createTestRoot()
  await act(async () => { root.render(createElement(QueuePanel)) })
  return container
}
const settle = async (n = 4) => {
  for (let k = 0; k < n; k++) await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
}

afterEach(async () => {
  unmountAll()
  getJobs.mockReset(); setWorkers.mockReset(); clearDeadJobs.mockReset()
  getWorkerReplicas.mockReset(); getWorkerCapacity.mockReset()
})

/** The payload GET /jobs returns after a run of `stopped` jobs was stopped and `failed` failed. */
const feed = (failed, stopped, errors = []) => ({
  workers: 0, worker_tier_alive: true, runtime_mode: 'auto', jobs: [],
  // `dead` is the RAW status count and still includes both — the server has not stopped
  // reporting it, the panel has stopped believing it means "failed".
  stats: { dead: failed + stopped },
  dead_letters: {
    failed: { n: failed, affected_runs: failed ? 1 : 0 },
    stopped: { n: stopped, affected_runs: stopped ? 1 : 0 },
    by_type: failed ? { scan_file: failed } : {},
    top_errors: errors,
  },
})

describe('stopping a run', () => {
  it('raises no permanent-failure banner at all', async () => {
    getJobs.mockResolvedValue(feed(0, 200))
    const c = await mount()
    await settle()
    expect(c.textContent).not.toMatch(/failed permanently/)
    expect(c.textContent).not.toMatch(/See server logs for details/)
    expect([...c.querySelectorAll('button')].some((b) => b.textContent === 'Dismiss records'))
      .toBe(false)
  })

  it('reports the stopped jobs rather than making them vanish', async () => {
    getJobs.mockResolvedValue(feed(0, 200))
    const c = await mount()
    await settle()
    expect(c.textContent).toMatch(/200 stopped/)
  })

  it('does not colour the stopped count as a dead-letter', async () => {
    getJobs.mockResolvedValue(feed(0, 5))
    const c = await mount()
    await settle()
    expect(c.textContent).not.toMatch(/dead-letter/)
  })
})

describe('a real failure', () => {
  it('still raises the banner, with its reason and its dismiss action', async () => {
    getJobs.mockResolvedValue(feed(3, 0, [{ error: 'corrupt archive' }]))
    const c = await mount()
    await settle()
    expect(c.textContent).toMatch(/3 jobs failed permanently/)
    expect(c.textContent).toMatch(/Reason: corrupt archive/)
    expect([...c.querySelectorAll('button')].some((b) => b.textContent === 'Dismiss records'))
      .toBe(true)
  })
})

describe('both at once — the state a busy estate is normally in', () => {
  it('counts each in its own place instead of merging them into one red number', async () => {
    // The case an eyeball subtraction gets wrong: 2 real failures beside 40 stopped jobs used
    // to render as "42 jobs failed permanently".
    getJobs.mockResolvedValue(feed(2, 40, [{ error: 'drive said no' }]))
    const c = await mount()
    await settle()
    expect(c.textContent).toMatch(/2 jobs failed permanently/)
    expect(c.textContent).not.toMatch(/42 jobs failed permanently/)
    expect(c.textContent).toMatch(/40 stopped/)
    expect(c.textContent).toMatch(/2 dead-letter/)
  })
})

describe('an API that has not been split yet', () => {
  it('keeps the pre-split behaviour rather than dropping the failure count', async () => {
    // No `failed`/`stopped` keys — the shape every deployed API returned before this change.
    getJobs.mockResolvedValue({
      workers: 0, worker_tier_alive: true, runtime_mode: 'auto', jobs: [],
      stats: { dead: 4 }, dead_letters: { top_errors: [{ error: 'corrupt archive' }] },
    })
    const c = await mount()
    await settle()
    expect(c.textContent).toMatch(/4 jobs failed permanently/)
    expect(c.textContent).not.toMatch(/stopped/)
  })
})
