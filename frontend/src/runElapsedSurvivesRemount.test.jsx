/* A run's elapsed time is a fact about the RUN, so it must not restart when you look away.
 *
 * THE DEFECT. DiscoverRunProgress anchored its clock to mount:
 *
 *     const [startedAt] = useState(() => Date.now())
 *     …
 *     {fmtElapsedSecs(elapsed)} elapsed
 *
 * The name is most of the story: a mount timestamp called `startedAt` gets rendered as the run's
 * start, and nobody notices, because on the FIRST mount the two numbers agree. They diverge the
 * moment the component remounts — switching to Assess and back, collapsing a panel, any route
 * change — which is precisely when somebody is checking whether a long run has stalled. A scan
 * twelve minutes in reported "0s elapsed" to the person asking if it was stuck.
 *
 * #1090 fixed the QUEUED line this way (server `created_at`, or the words "unavailable"). These
 * are the other two clocks on the same card, plus the one derived number that made it worse than
 * cosmetic.
 *
 * THE DERIVED NUMBER. WorkerCard divides filesDone by this to get a rate, and divides the
 * remainder by that rate to get an ETA. A stale numerator over a freshly-zeroed denominator does
 * not produce a slightly-wrong figure, it produces a confident impossible one: 500 files against
 * a three-second-old clock is 166 files/sec, and the ETA collapses to seconds on a run with
 * twenty minutes left. Suppressing both when the denominator is unknown is the only safe
 * default, since there is no honest value to fall back to.
 *
 * WHAT IS DELIBERATELY STILL MOUNT-RELATIVE: the stall and slow-lifecycle hints. "This view has
 * been watching for 90 seconds and nothing has happened" is a question about the watching.
 * Server-anchoring it would fire it instantly on any reload of an older scan. Pinned below so a
 * later sweep does not "finish the job" by converting it too.
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement, act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const { default: DiscoverRunProgress } = await import('./DiscoverRunProgress.jsx')

const iso = (secsAgo) => new Date(Date.now() - secsAgo * 1000).toISOString()

/** Mount the card fresh, exactly as a tab switch back to Discover does. */
const mountCard = async (props) => {
  const { container, root } = createTestRoot()
  await act(async () => { root.render(createElement(DiscoverRunProgress, props)) })
  return container
}

afterEach(async () => { await unmountAll(); vi.useRealTimers() })

const RUNNING = { phase: 'analysing', files_found: 500, files_done: 500, current: 'a/b.docx' }

describe('a running scan, viewed after switching away and back', () => {
  it('reports the age of the RUN, not the age of the mount', async () => {
    // Twelve minutes in. A fresh mount knows nothing about that except through the server.
    const c = await mountCard({ progress: RUNNING, busy: true, runStartedAt: iso(12 * 60) })
    expect(c.textContent).toMatch(/12m elapsed/)
    expect(c.textContent).not.toMatch(/0s elapsed/)
  })

  it('gives the same answer on a second, independent mount', async () => {
    // The actual regression shape: identical props, mounted twice, must agree. A mount-anchored
    // clock passes the test above (it renders on first mount too) and fails this one.
    const started = iso(7 * 60)
    const first = await mountCard({ progress: RUNNING, busy: true, runStartedAt: started })
    const firstText = first.textContent
    await unmountAll()
    const second = await mountCard({ progress: RUNNING, busy: true, runStartedAt: started })
    expect(second.textContent).toMatch(/7m elapsed/)
    expect(firstText).toMatch(/7m elapsed/)
  })

  it('says so instead of showing a zero when the server has no start instant', async () => {
    const c = await mountCard({ progress: RUNNING, busy: true, runStartedAt: null })
    expect(c.textContent).toMatch(/elapsed time unavailable/)
    expect(c.textContent).not.toMatch(/0s elapsed/)
  })

  it('falls back to the queued stub timestamp when that is the only one there', async () => {
    // queuedProgress.js threads scan_runs.started_at into progress.started_at for the queued
    // phase. That is a real server instant and must not be ignored just because it arrives by
    // the other route.
    const c = await mountCard({
      progress: { ...RUNNING, started_at: iso(200) }, busy: true, runStartedAt: null })
    expect(c.textContent).toMatch(/3m 20s elapsed/)
  })

  it('uses the active scan timestamp instead of the previously selected scan timestamp', async () => {
    // Production regression: starting a new SharePoint scan left the old completed run selected
    // in App state for the duration of the poll. The card mixed the new run's progress with that
    // old run's started_at and immediately displayed "68m elapsed".
    const c = await mountCard({
      progress: { ...RUNNING, started_at: iso(4) },
      busy: true,
      runStartedAt: iso(68 * 60),
    })
    expect(c.textContent).toMatch(/4s elapsed/)
    expect(c.textContent).not.toMatch(/68m elapsed/)
  })
})

describe('the rate and ETA derived from it', () => {
  it('are suppressed rather than fabricated when the run has no start instant', async () => {
    const c = await mountCard({ progress: RUNNING, busy: true, runStartedAt: null })
    // 500 files over an unknown interval is not a speed. Neither figure may appear.
    expect(c.textContent).not.toMatch(/files\/sec/)
    expect(c.textContent).not.toMatch(/remaining/)
  })

  it('cannot report an impossible speed after a remount', async () => {
    // 500 done, 600 total, ten minutes in — 0.83/sec. The mount-anchored clock made this
    // 500/3 = 166/sec on the first tick after a tab switch.
    const c = await mountCard({
      progress: { ...RUNNING, files_done: 500, files_found: 600 },
      busy: true, runStartedAt: iso(600) })
    expect(c.textContent).not.toMatch(/1\d\d(\.\d)? files\/sec/)
  })
})

describe('the watching clock, which is a different question', () => {
  it('still drives the long-running hint from mount, not from the run', async () => {
    vi.useFakeTimers()
    const { container, root } = createTestRoot()
    // Discovering, nothing found, and a run that STARTED two hours ago. If the hint read the
    // run's age it would fire immediately here; it must not, because this view has been
    // watching for zero seconds and has no basis yet to call anything slow.
    const props = { progress: { phase: 'discovering', files_found: 0 }, busy: true,
                    runStartedAt: iso(7200) }
    await act(async () => { root.render(createElement(DiscoverRunProgress, props)) })
    expect(container.textContent).not.toMatch(/appears stalled/i)
    // …while the run's own age, which IS server-anchored, reads two hours straight away.
    expect(container.textContent).toMatch(/120m elapsed/)

    // 95 seconds of actually watching with no progress tick, and now it may.
    await act(async () => { vi.advanceTimersByTime(95_000) })
    expect(container.textContent).toMatch(/appears stalled — no progress for 95s/i)
  })
})
