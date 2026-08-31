/**
 * QueuePanel must not claim anything it has not read. The DOM half of queueFreshness.test.js.
 *
 * THE DEFECT. `q` initialised to null, and everything derived from it with a fallback:
 *
 *     const stats   = q?.stats || {}                    // {} before any response
 *     const shown   = order.filter((s) => stats[s])     // []
 *     const workers = q?.workers ?? 0                   // 0
 *     …
 *     {shown.length === 0 && !err && <span>queue empty — nothing in flight</span>}
 *     <span style={{ fontSize: 22, fontWeight: 700 }}>{workers}</span>
 *
 * So a freshly-mounted panel, before a single response, rendered **"queue empty — nothing in
 * flight"** and a bold **0** with +/- controls beside it. Two confident factual claims that no
 * successful read had established.
 *
 * The unit tests pin the state machine. These pin what actually reaches the screen, because the
 * defect was never in the derivation — it was in rendering a claim from a fallback value, and a
 * pure-function test cannot see that.
 */
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { createElement, act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const getJobs = vi.fn()
vi.mock('./api.js', () => ({
  getJobs: (...a) => getJobs(...a),
  setWorkers: vi.fn(),
  clearDeadJobs: vi.fn(),
  getWorkerReplicas: vi.fn(async () => ({})),
  setWorkerReplicas: vi.fn(),
  getWorkerCapacity: vi.fn(async () => ({})),
}))

import { resetJobsFeed } from './jobsFeed.js'
beforeEach(() => { resetJobsFeed(); getJobs.mockReset() })
afterEach(() => { unmountAll() })

const { default: QueuePanel } = await import('./QueuePanel.jsx')

let container, root
const mount = async () => {
  ;({ container, root } = createTestRoot())
  await act(async () => { root.render(createElement(QueuePanel)) })
  return container
}
const settle = async (n = 6) => {
  for (let k = 0; k < n; k++) await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
}

const EMPTY_OK = { stats: {}, jobs: [], workers: 0, runtime_mode: 'distributed',
                   worker_tier_alive: true }

/** A promise that never settles — the delayed-response case, held open for the assertion. */
const never = () => new Promise(() => {})


describe('before any response has arrived', () => {
  it('does not claim the queue is empty', async () => {
    getJobs.mockImplementation(never)
    const c = await mount()
    await settle()
    expect(c.textContent).not.toMatch(/queue empty/i)
  })

  it('says it is still looking instead', async () => {
    getJobs.mockImplementation(never)
    const c = await mount()
    await settle()
    expect(c.textContent).toMatch(/checking the queue/i)
  })

  it('does not render a total-jobs count', async () => {
    getJobs.mockImplementation(never)
    const c = await mount()
    await settle()
    expect(c.textContent).not.toMatch(/total jobs/i)
  })

  it('does not offer worker controls for a pool it has not read', async () => {
    // The +/- buttons beside a fabricated 0. Offering a control for a number nothing measured
    // invites someone to "fix" a worker count that was never real.
    getJobs.mockImplementation(never)
    const c = await mount()
    await settle()
    expect(c.querySelector('[aria-label="Add a worker"]')).toBeNull()
    expect(c.querySelector('[aria-label="Remove a worker"]')).toBeNull()
  })
})


describe('after a successful response', () => {
  it('may then say the queue is empty', async () => {
    // The control. Without this the tests above would pass for a panel that never says anything.
    getJobs.mockResolvedValue(EMPTY_OK)
    const c = await mount()
    await settle()
    expect(c.textContent).toMatch(/queue empty/i)
    expect(c.textContent).not.toMatch(/checking the queue/i)
  })

  it('shows the counts it actually read', async () => {
    getJobs.mockResolvedValue({ ...EMPTY_OK, stats: { queued: 2, running: 1 } })
    const c = await mount()
    await settle()
    expect(c.textContent).toMatch(/total jobs/i)
  })
})


describe('when the queue cannot be read at all', () => {
  it.each([['500'], ['503']])('a %s with nothing cached says unavailable, never empty', async (code) => {
    getJobs.mockRejectedValue(new Error(`HTTP ${code}`))
    const c = await mount()
    await settle()
    expect(c.textContent).not.toMatch(/queue empty/i)
    expect(c.textContent).toMatch(/unavailable|could not/i)
  })

  it.each([['500'], ['503']])('a %s with nothing cached shows no worker controls', async (code) => {
    getJobs.mockRejectedValue(new Error(`HTTP ${code}`))
    const c = await mount()
    await settle()
    expect(c.querySelector('[aria-label="Add a worker"]')).toBeNull()
  })
})


describe('when a later poll fails but earlier data exists', () => {
  it('keeps the last-known counts rather than blanking or zeroing them', async () => {
    getJobs.mockResolvedValueOnce({ ...EMPTY_OK, stats: { queued: 7 } })
    const c = await mount()
    await settle()
    expect(c.textContent).toMatch(/total jobs/i)

    getJobs.mockRejectedValue(new Error('HTTP 503'))
    await settle(10)

    // The counts survive. Reverting to zeros here would replace real information with a
    // confident-looking fabrication at exactly the moment the operator needs the truth.
    expect(c.textContent).toMatch(/total jobs/i)
    expect(c.textContent).not.toMatch(/queue empty/i)
  })
})


describe('topology', () => {
  it('withholds worker controls when runtime_mode is absent, even on a good response', async () => {
    // Unknown is not zero. Without runtime_mode the panel cannot tell whether this pool is the
    // thing running the work at all (the split topology of #113), so it must not offer to scale it.
    const { runtime_mode, ...noMode } = EMPTY_OK       // eslint-disable-line no-unused-vars
    getJobs.mockResolvedValue(noMode)
    const c = await mount()
    await settle()
    expect(c.textContent).toMatch(/queue empty/i)      // the read itself succeeded
    expect(c.querySelector('[aria-label="Add a worker"]')).toBeNull()
  })

  it('offers them once the topology is stated', async () => {
    // The control for the test above: proves the controls can appear, so their absence there is
    // about topology rather than about the panel never rendering them.
    getJobs.mockResolvedValue({ ...EMPTY_OK, runtime_mode: 'in_process', worker_tier_alive: false })
    const c = await mount()
    await settle()
    expect(c.querySelector('[aria-label="Add a worker"]')).not.toBeNull()
  })
})
