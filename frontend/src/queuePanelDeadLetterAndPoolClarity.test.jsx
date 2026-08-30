import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement, act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'

// Two related clarity fixes to Monitor -> Async job queue (stakeholder UX review, 2026-08-30):
//
// 1. The in-process pool's "0" reads as "no capacity" sitting directly under "✓ worker service
//    online" — live screenshot showed exactly this. The pool is legitimately, permanently 0
//    whenever a dedicated worker tier does the real work, so that specific case (workers===0 &&
//    worker_tier_alive) now collapses the +/- control behind a "Advanced: emergency in-process
//    workers" disclosure instead of rendering a bold "0" as a headline stat. Every other case
//    (workers > 0, or no tier heartbeat — the genuine "nothing will process jobs" state) is
//    unchanged: the control stays exactly where and how it was.
//
// 2. The dead-letter banner's only action used to be "Clear dead-letters", read as the fix. It
//    only deletes the records — the underlying cause (a bad Drive connection, in the
//    suspicious-zero case) is untouched by clicking it. Relabeled "Dismiss records" with a
//    tooltip saying exactly that, and the suspicious-zero reason (api/handlers.py's
//    _scan_discover guard, a RuntimeError with a stable message) now gets an explicit
//    interpretation + recommended action rather than just the raw reason string.

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

// jobsFeed.js shares ONE GET /jobs subscription across every component that wants it, and keeps
// its cached payload across unmount on purpose: a remount seconds later should draw immediately,
// and the payload carries its real fetchedAt plus a `stale` flag so it cannot pass as fresh.
// Within a test file that means one test's cache would otherwise answer the next test's mock.
// Reset it explicitly here — the module's production behaviour is deliberate and is covered in
// jobsFeed.test.js; it is this file that needs a cold start, not the cache that needs weakening.
import { resetJobsFeed } from './jobsFeed.js'
beforeEach(() => { resetJobsFeed() })


const { default: QueuePanel } = await import('./QueuePanel.jsx')

let container, root
const mount = async () => {
  ;({ container, root } = createTestRoot())
  await act(async () => { root.render(createElement(QueuePanel)) })
  return container
}
const settle = async (n = 4) => { for (let k = 0; k < n; k++) await act(async () => { await new Promise((r) => setTimeout(r, 0)) }) }

afterEach(async () => {
  unmountAll()
  getJobs.mockReset(); setWorkers.mockReset(); clearDeadJobs.mockReset()
  getWorkerReplicas.mockReset(); getWorkerCapacity.mockReset()
  const { _resetForTests } = await import('./workerCapacityStore.js')
  _resetForTests()
})

describe('the in-process pool disclosure', () => {
  it('collapses the pool control behind "Advanced" when the pool is decoratively 0 (a dedicated tier is alive)', async () => {
    getJobs.mockResolvedValue({ workers: 0, worker_tier_alive: true, runtime_mode: 'auto', stats: {}, jobs: [] })
    const c = await mount()
    await settle()
    const details = c.querySelector('details')
    expect(details).toBeTruthy()
    expect(details.querySelector('summary').textContent).toMatch(/Advanced: emergency in-process workers/)
    // The control itself is still present in the DOM (reachable, not deleted) — just collapsed.
    expect(details.querySelector('button[aria-label="Add a worker"]')).toBeTruthy()
    // It must not also render a second, non-collapsed copy of the control.
    expect(c.querySelectorAll('button[aria-label="Add a worker"]').length).toBe(1)
  })

  it('does NOT collapse the pool control when it is the genuine capacity signal (workers > 0)', async () => {
    getJobs.mockResolvedValue({ workers: 4, worker_tier_alive: true, runtime_mode: 'auto', stats: {}, jobs: [] })
    const c = await mount()
    await settle()
    expect(c.querySelector('details')).toBeFalsy()
    expect(c.querySelector('button[aria-label="Add a worker"]')).toBeTruthy()
  })

  it('does NOT collapse the pool control when no worker tier has ever reported in (the real "nothing will process jobs" state)', async () => {
    getJobs.mockResolvedValue({ workers: 0, worker_tier_alive: false, runtime_mode: 'auto', stats: {}, jobs: [] })
    const c = await mount()
    await settle()
    expect(c.querySelector('details')).toBeFalsy()
    expect(c.textContent).toMatch(/No workers available/)
  })
})

describe('the dead-letter banner', () => {
  it('labels the clear action "Dismiss records" and says it does not fix the cause', async () => {
    getJobs.mockResolvedValue({
      workers: 0, worker_tier_alive: true, runtime_mode: 'auto',
      stats: { dead: 5 }, dead_letters: { top_errors: [{ error: 'source unreachable' }] }, jobs: [],
    })
    const c = await mount()
    await settle()
    const btn = [...c.querySelectorAll('button')].find((b) => b.textContent === 'Dismiss records')
    expect(btn).toBeTruthy()
    expect(btn.title).toMatch(/does not fix whatever caused the failures/)
    expect(c.textContent).not.toMatch(/Clear dead-letters/)
  })

  it('explains the suspicious-zero guard in plain language and recommends re-running Discover', async () => {
    getJobs.mockResolvedValue({
      workers: 0, worker_tier_alive: true, runtime_mode: 'auto',
      stats: { dead: 5 },
      dead_letters: { top_errors: [{
        error: 'listing returned 0 files but previous scan db198af27aa3 found 6916; refusing to publish suspicious zero',
      }] },
      jobs: [],
    })
    const c = await mount()
    await settle()
    expect(c.textContent).toMatch(/preserved the previously verified inventory/)
    expect(c.textContent).toMatch(/re-run Discover to retry/)
  })

  it('omits the suspicious-zero interpretation for an unrelated dead-letter reason', async () => {
    getJobs.mockResolvedValue({
      workers: 0, worker_tier_alive: true, runtime_mode: 'auto',
      stats: { dead: 2 }, dead_letters: { top_errors: [{ error: 'corrupt archive' }] }, jobs: [],
    })
    const c = await mount()
    await settle()
    expect(c.textContent).not.toMatch(/preserved the previously verified inventory/)
  })

  it('still clicks through to clearDeadJobs under its new label', async () => {
    getJobs.mockResolvedValue({
      workers: 0, worker_tier_alive: true, runtime_mode: 'auto',
      stats: { dead: 1 }, dead_letters: { top_errors: [{ error: 'corrupt archive' }] }, jobs: [],
    })
    clearDeadJobs.mockResolvedValue({ purged: 1 })
    const c = await mount()
    await settle()
    const btn = [...c.querySelectorAll('button')].find((b) => b.textContent === 'Dismiss records')
    await act(async () => { btn.click() })
    await settle()
    expect(clearDeadJobs).toHaveBeenCalled()
  })
})
