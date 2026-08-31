/* A crashed worker must not look like a working one.
 *
 * MEASURED IN PRODUCTION, 2026-08-31, scan 128d4bf609b4: worker w8 logged
 * `double free or corruption (!prev)`, Azure recorded exit 139, and worker w6 re-claimed the
 * same job as attempt 2 eight minutes later. Throughout, this component rendered the ordinary
 * in-progress checklist — because a process killed by the OS emits no event, and `claim_job`
 * sets phase=NULL on the next claim, so attempt 2 was indistinguishable from attempt 1.
 *
 * store.reclaim_stuck_jobs now marks the requeued row phase='reclaimed' and emits
 * `scan.interrupted` carrying the attempt. This is the card that reads it.
 *
 * WHY NOT REUSE THE 'retrying' CARD, which already exists and already says "attempt N": it opens
 * with "A previous attempt failed — waiting to retry". Nothing failed. The process died. That
 * sentence sends an operator to handler logs for a fault that is not in the handler, and the two
 * states want different investigations:
 *
 *     retrying    the handler raised; last_error says how; the process is healthy
 *     reclaimed   the process stopped without reporting; there is no error to show
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement, act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const { default: DiscoverRunProgress } = await import('./DiscoverRunProgress.jsx')

const mount = async (props) => {
  const { container, root } = createTestRoot()
  await act(async () => { root.render(createElement(DiscoverRunProgress, props)) })
  return container
}

// unmountAll is async; not awaiting it tears down the NEXT test's root and the symptom is an
// empty container rather than an error.
afterEach(async () => { await unmountAll(); vi.useRealTimers() })

const RECLAIMED = { phase: 'reclaimed', attempt: 2, max_attempts: 5 }

describe('a run whose worker died', () => {
  it('says the worker was interrupted, with the attempt it is now on', async () => {
    const c = await mount({ progress: RECLAIMED, busy: true })
    expect(c.textContent).toMatch(/Worker interrupted; retrying/)
    expect(c.textContent).toMatch(/attempt 2 of 5/)
  })

  it('does not render the ordinary in-progress checklist', async () => {
    // THE regression, stated as what the user actually saw for eight minutes: step rows ticking
    // along as though a worker were still walking the estate.
    const c = await mount({ progress: RECLAIMED, busy: true })
    expect(c.querySelector('[aria-label="Discovery steps"]')).toBeNull()
    expect(c.querySelector('[aria-label="Discovery interrupted"]')).toBeTruthy()
  })

  it('does not claim a previous attempt FAILED', async () => {
    // The retrying card's wording, which would be wrong here: nothing failed, and there is no
    // last_error to show because the process never got to write one.
    const c = await mount({ progress: RECLAIMED, busy: true })
    expect(c.textContent).not.toMatch(/attempt failed/i)
    expect(c.textContent).toMatch(/stopped without reporting/)
  })

  it('offers no countdown or ETA for the next attempt', async () => {
    // The job is waiting for whichever worker claims it next. Nothing here can predict that, and
    // a fabricated ETA would be wrong as often as right — the same reasoning that keeps the
    // queued card free of a queue position.
    const c = await mount({ progress: RECLAIMED, busy: true })
    expect(c.textContent).not.toMatch(/\bin \d+s\b|retrying in|next attempt in/i)
  })
})

describe('when the server did not supply an attempt number', () => {
  it('still names the interruption, and simply omits the count', async () => {
    // The number arrives on the scan.interrupted event or the job poll. If neither is in hand,
    // "attempt 2" would be a guess about how many times this estate has been walked.
    const c = await mount({ progress: { phase: 'reclaimed' }, busy: true })
    expect(c.textContent).toMatch(/Worker interrupted; retrying/)
    expect(c.textContent).not.toMatch(/attempt \d/)
    expect(c.textContent).not.toMatch(/attempt (null|undefined|NaN)/)
  })

  it('omits "of N" when only the attempt is known', async () => {
    const c = await mount({ progress: { phase: 'reclaimed', attempt: 3 }, busy: true })
    expect(c.textContent).toMatch(/attempt 3/)
    expect(c.textContent).not.toMatch(/attempt 3 of/)
  })
})

describe('the states either side of it', () => {
  it('leaves the retrying card alone', async () => {
    // The control. A handler that raised is a different fact and keeps its own wording, its own
    // last_error, and its own card.
    const c = await mount({
      progress: { phase: 'retrying', attempt: 2, max_attempts: 5, last_error: 'drive 500' },
      busy: true })
    expect(c.textContent).toMatch(/A previous attempt failed/)
    expect(c.textContent).toMatch(/drive 500/)
    expect(c.textContent).not.toMatch(/Worker interrupted/)
  })

  it('does not hijack an ordinary running scan', async () => {
    const c = await mount({
      progress: { phase: 'analysing', files_found: 10, files_done: 4 }, busy: true })
    expect(c.textContent).not.toMatch(/Worker interrupted/)
    expect(c.querySelector('[aria-label="Discovery steps"]')).toBeTruthy()
  })

  it('does not render once the run is no longer busy', async () => {
    // A reclaimed phase lingering on a terminated run must not resurrect an "interrupted;
    // retrying" promise about a scan that has stopped for good.
    const c = await mount({ progress: RECLAIMED, busy: false })
    expect(c.textContent).not.toMatch(/Worker interrupted; retrying/)
  })
})

describe('stopping from here', () => {
  it('offers Cancel, because no attempt is currently running', async () => {
    const onStop = vi.fn()
    const c = await mount({ progress: RECLAIMED, busy: true, onStop })
    const btn = [...c.querySelectorAll('button')].find((b) => b.textContent === 'Cancel')
    expect(btn).toBeTruthy()
    await act(async () => { btn.click() })
    expect(onStop).toHaveBeenCalled()
  })

  it('shows no Cancel when the caller supplies no handler', async () => {
    const c = await mount({ progress: RECLAIMED, busy: true })
    expect([...c.querySelectorAll('button')].some((b) => b.textContent === 'Cancel')).toBe(false)
  })
})
