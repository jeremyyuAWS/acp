/**
 * The job poll loop stops when the App unmounts.
 *
 * WHAT WAS ACTUALLY WRONG, and what was not. `_pollScanJobPolling` is a `do…while (!job.done)`
 * over `getJob` with a 350ms sleep and no other stop condition — not even `scanCancelledRef`,
 * which only the queued-scan loop consults. So an App that unmounted while a job was still
 * running kept issuing a request every 350ms until the server finished that job, for a component
 * nobody could see.
 *
 * NOT a setState-after-unmount bug. React 18 removed that warning because such an update is a
 * documented no-op (there are zero occurrences of the warning string in react-dom 18.3.1), and
 * `window` always exists in a browser. The `ReferenceError: window is not defined` this was first
 * noticed through only happens when jsdom is torn down with the loop still running — a symptom of
 * the leak, in the one environment where the leak can also throw.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

globalThis.__BUILD_TIME__ = '2026-08-01T00:00:00.000Z'
globalThis.__BUILD_VERSION__ = '2026.8.1'

// A job that is never done — exactly the shape that kept the old loop running forever.
const getJob = vi.fn(async () => ({ done: false, phase: 'discovering', scan_id: 's1' }))

vi.mock('./api.js', async (importActual) => ({
  ...(await importActual()),
  getConfig: vi.fn(async () => ({ auth: 'demo' })),
  getRubric: vi.fn(async () => ({ target: 'WCAG 2.1 AA', hash: 'abcdef0123' })),
  getSources: vi.fn(async () => []),
  listScans: vi.fn(async () => []),
  getActiveScan: vi.fn(async () => null),
  getSettings: vi.fn(async () => ({ scan_scope: '' })),
  updateSettings: vi.fn(async () => ({ scan_scope: '' })),
  getScan: vi.fn(async () => ({ run: { id: 's1', status: 'done' }, files: [] })),
  getDecisions: vi.fn(async () => ({})),
  startScanQueued: vi.fn(() => new Promise(() => {})),
  getJob,
}))

const { default: App } = await import('./App.jsx')

// `unmountAll` is async. Not awaiting it (as the neighbouring test files do) lets the next test
// mount before the previous root has finished tearing down, and this file's second test then saw
// zero polls where it should have seen many — it passed alone and failed in the file.
afterEach(async () => { await unmountAll(); sessionStorage.clear() })
beforeEach(() => { sessionStorage.clear(); getJob.mockClear() })

const flush = async () => { for (let i = 0; i < 4; i++) await act(async () => { await Promise.resolve() }) }
const byText = (c, sel, re) => [...c.querySelectorAll(sel)].find((e) => re.test(e.textContent))
const settle = async (ms) => { await act(async () => { await new Promise((r) => setTimeout(r, ms)) }); await flush() }

async function mountWithARunningJob() {
  sessionStorage.setItem('active_job_id', 'j1')
  const { root, container } = createTestRoot()
  await act(async () => { root.render(createElement(App)) })
  await flush()
  const signIn = byText(container, 'button', /Sign in with SSO/)
  if (signIn) await act(async () => { signIn.click() })
  await flush()
  await settle(500)
  return root
}

describe('the job poll loop and unmount', () => {
  it('keeps polling while the App is mounted', async () => {
    // Anti-vacuity for the test below: if the loop never ran, "it stopped" would pass for the
    // wrong reason. This proves there is a live poll to stop.
    await mountWithARunningJob()
    expect(getJob).toHaveBeenCalledWith('j1')
    const before = getJob.mock.calls.length
    await settle(800)
    expect(getJob.mock.calls.length,
      'the poll loop is not running, so the unmount test below proves nothing').toBeGreaterThan(before)
  })

  it('stops issuing requests once the App unmounts', async () => {
    const root = await mountWithARunningJob()
    expect(getJob.mock.calls.length).toBeGreaterThan(0)

    await act(async () => { root.unmount() })
    const afterUnmount = getJob.mock.calls.length

    // Several poll intervals. The old loop would have fired at least twice more in this span.
    await settle(1200)
    expect(getJob.mock.calls.length,
      'the App kept polling getJob after unmounting').toBe(afterUnmount)
  })

  it('keeps the reconnect keys when it abandons the poll on unmount', async () => {
    // The regression this fix nearly introduced. `pollScanJob`'s finally() clears
    // active_job_id, which is what a fresh load reconnects THROUGH. Stopping the loop made that
    // finally reachable on unmount for the first time, so a reload during a running job would
    // have silently forgotten it — defeating the feature the key exists for. Abandoning the poll
    // is not the job finishing.
    const root = await mountWithARunningJob()
    expect(sessionStorage.getItem('active_job_id')).toBe('j1')

    await act(async () => { root.unmount() })
    await settle(800)
    expect(sessionStorage.getItem('active_job_id'),
      'unmounting threw away the id a reload needs to reconnect').toBe('j1')
  })

  it('does not fetch the finished scan after unmounting', async () => {
    // The loop's exit path calls getScan(job.scan_id). Stopping the ticks but still spending that
    // request would be a smaller version of the same leak.
    const api = await import('./api.js')
    const root = await mountWithARunningJob()
    api.getScan.mockClear()
    getJob.mockImplementation(async () => ({ done: true, phase: 'done', scan_id: 's1' }))

    await act(async () => { root.unmount() })
    await settle(800)
    expect(api.getScan).not.toHaveBeenCalled()
  })
})
