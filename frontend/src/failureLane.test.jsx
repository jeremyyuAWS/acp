/**
 * W7 · Operational-failure lane — the "job *failed*" branch made visible on Monitor.
 *
 * The durable jobs table already retried-then-dead-lettered failing work, but nothing surfaced
 * it. This guards the lane's contract directly: how a job is categorised (retrying vs terminal
 * dead-letter vs not-a-failure), the plain-language reason hints, the retry affordance re-running
 * the ORIGINATING action (rescoreFile for a scan, remediateScan for a remediation), and the
 * dead-letter clear.
 *
 * DOM-level, not browser-level: this repo's preview server runs vite rooted at the SHARED checkout
 * whatever worktree you are in (CLAUDE.md), so a browser check would exercise code without this.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

const getJobs = vi.fn()
const clearDeadJobs = vi.fn(async () => ({ purged: 2 }))
const remediateScan = vi.fn(async () => ({ enqueued: 1, job_ids: ['x'] }))
const rescoreFile = vi.fn(async () => ({ job_id: 'r1' }))

vi.mock('./api.js', () => ({
  getJobs: (...a) => getJobs(...a),
  clearDeadJobs: (...a) => clearDeadJobs(...a),
  remediateScan: (...a) => remediateScan(...a),
  rescoreFile: (...a) => rescoreFile(...a),
}))

// jobsFeed.js shares ONE GET /jobs subscription across every component that wants it, and keeps
// its cached payload across unmount on purpose: a remount seconds later should draw immediately,
// and the payload carries its real fetchedAt plus a `stale` flag so it cannot pass as fresh.
// Within a test file that means one test's cache would otherwise answer the next test's mock.
// Reset it explicitly here — the module's production behaviour is deliberate and is covered in
// jobsFeed.test.js; it is this file that needs a cold start, not the cache that needs weakening.
import { resetJobsFeed } from './jobsFeed.js'
beforeEach(() => { resetJobsFeed() })


const mod = await import('./FailureLane.jsx')
const FailureLane = mod.default
const { classifyFailure, splitFailures } = mod

afterEach(unmountAll)
beforeEach(() => {
  getJobs.mockReset(); clearDeadJobs.mockClear(); remediateScan.mockClear(); rescoreFile.mockClear()
  clearDeadJobs.mockResolvedValue({ purged: 2 })
  remediateScan.mockResolvedValue({ enqueued: 1 })
  rescoreFile.mockResolvedValue({ job_id: 'r1' })
})

const flush = async () => { await act(async () => { await Promise.resolve(); await Promise.resolve() }) }
async function mount() {
  const { root, container } = createTestRoot()
  await act(async () => { root.render(createElement(FailureLane)) })
  await flush()
  return container
}
const click = async (el) => { await act(async () => { el.click() }); await flush() }
const btn = (c, re) => [...c.querySelectorAll('button')].find((b) => re.test(b.textContent))

// ── pure categorisation ──────────────────────────────────────────────────────
describe('classifyFailure — which jobs are operational failures', () => {
  it('a dead-lettered job is terminal', () => {
    expect(classifyFailure({ status: 'dead', attempts: 5, max_attempts: 5 })).toBe('dead')
  })
  it('a bare failed job with retries left is still retrying; exhausted → dead', () => {
    expect(classifyFailure({ status: 'failed', attempts: 2, max_attempts: 5 })).toBe('retrying')
    expect(classifyFailure({ status: 'failed', attempts: 5, max_attempts: 5 })).toBe('dead')
  })
  it('a queued/running job that already errored and re-attempted is mid-retry', () => {
    expect(classifyFailure({ status: 'queued', attempts: 2, last_error: 'boom' })).toBe('retrying')
    expect(classifyFailure({ status: 'running', attempts: 3, last_error: 'boom' })).toBe('retrying')
  })
  it('healthy jobs are not failures', () => {
    expect(classifyFailure({ status: 'done', attempts: 1 })).toBe(null)
    expect(classifyFailure({ status: 'running', attempts: 1 })).toBe(null)          // first attempt
    expect(classifyFailure({ status: 'queued', attempts: 1, last_error: null })).toBe(null)
  })
})

describe('splitFailures — buckets the feed', () => {
  it('separates dead from retrying and drops the healthy ones', () => {
    const { dead, retrying } = splitFailures([
      { id: 'a', status: 'dead', attempts: 5, max_attempts: 5 },
      { id: 'b', status: 'running', attempts: 2, last_error: 'x' },
      { id: 'c', status: 'done', attempts: 1 },
    ])
    expect(dead.map((j) => j.id)).toEqual(['a'])
    expect(retrying.map((j) => j.id)).toEqual(['b'])
  })
})

// ── rendering + interaction ──────────────────────────────────────────────────
describe('FailureLane rendering', () => {
  it('shows the healthy state when nothing has failed', async () => {
    getJobs.mockResolvedValue({ jobs: [
      { id: 'j1', type: 'scan_file', status: 'done', attempts: 1 },
    ] })
    const c = await mount()
    expect(c.textContent).toMatch(/No operational failures/)
    expect(btn(c, /Retry/)).toBeUndefined()
  })

  it('lists a dead-lettered corrupt-file scan with its reason and a retry button', async () => {
    getJobs.mockResolvedValue({ jobs: [
      { id: 'd1', type: 'scan_file', status: 'dead', attempts: 5, max_attempts: 5,
        scan_id: 's1', payload: '{"file":"budget.pdf"}',
        last_error: 'PdfReadError: file appears corrupt / malformed' },
    ] })
    const c = await mount()
    expect(c.textContent).toMatch(/budget\.pdf/)
    expect(c.textContent).toMatch(/dead-letter/i)
    // plain-language hint for a corrupt file
    expect(c.textContent).toMatch(/could not be opened/i)
    // count badge
    expect(c.textContent).toMatch(/1 needs? attention/)
    expect(btn(c, /Retry/)).toBeTruthy()
  })

  it('retry on a dead scan_file re-runs rescoreFile for that file', async () => {
    getJobs.mockResolvedValue({ jobs: [
      { id: 'd1', type: 'scan_file', status: 'dead', attempts: 5, max_attempts: 5,
        scan_id: 's1', payload: '{"file":"budget.pdf"}', last_error: 'timeout' },
    ] })
    const c = await mount()
    await click(btn(c, /Retry/))
    expect(rescoreFile).toHaveBeenCalledWith('s1', 'budget.pdf')
    expect(remediateScan).not.toHaveBeenCalled()
    expect(c.textContent).toMatch(/re-queued/i)
  })

  it('retry on a dead remediate_file re-runs remediateScan scoped to that file', async () => {
    getJobs.mockResolvedValue({ jobs: [
      { id: 'd2', type: 'remediate_file', status: 'dead', attempts: 5, max_attempts: 5,
        scan_id: 's9', payload: '{"file":"report.html"}', last_error: 'Drive token expired' },
    ] })
    const c = await mount()
    // OAuth/expired hint
    expect(c.textContent).toMatch(/sign-in expired/i)
    await click(btn(c, /Retry/))
    expect(remediateScan).toHaveBeenCalledWith('s9', ['report.html'])
  })

  it('a retrying (transient) job shows the attempt count and NO retry button', async () => {
    getJobs.mockResolvedValue({ jobs: [
      { id: 't1', type: 'scan_file', status: 'running', attempts: 2, max_attempts: 5,
        scan_id: 's1', payload: '{"file":"slow.docx"}', last_error: 'connection reset' },
    ] })
    const c = await mount()
    expect(c.textContent).toMatch(/attempt 2 of 5/)
    // retry is only offered on terminal dead-letters, not while auto-retry is in flight
    expect(btn(c, /Retry/)).toBeUndefined()
  })

  it('a scan-level dead job (no single-file re-trigger) is shown but offers no retry button', async () => {
    getJobs.mockResolvedValue({ jobs: [
      { id: 'd3', type: 'scan_discover', status: 'dead', attempts: 5, max_attempts: 5,
        scan_id: 's1', payload: '{"source":"drive"}', last_error: 'source unreachable' },
    ] })
    const c = await mount()
    expect(c.textContent).toMatch(/Finding documents/)
    expect(btn(c, /Retry/)).toBeUndefined()
  })

  it('Clear dead-letters calls the purge endpoint', async () => {
    getJobs.mockResolvedValue({ jobs: [
      { id: 'd1', type: 'scan_file', status: 'dead', attempts: 5, max_attempts: 5,
        scan_id: 's1', payload: '{"file":"x.pdf"}', last_error: 'corrupt' },
    ] })
    const c = await mount()
    await click(btn(c, /Clear dead-letters/))
    expect(clearDeadJobs).toHaveBeenCalled()
  })
})
