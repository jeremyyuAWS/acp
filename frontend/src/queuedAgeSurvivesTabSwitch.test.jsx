/* The queued card's age, tested the way the bug actually happened: by leaving and coming back.
 *
 * WHY THE EXISTING TESTS COULD NOT CATCH THIS. Every queued-age assertion in
 * discoverRunProgress.test.jsx goes through `renderToStaticMarkup`. That renders once, to a
 * string, and never runs an effect — so the component's mount clock is frozen at 0 for the whole
 * test and a mount-relative age is indistinguishable from a server-derived one. The tests are
 * right about the derivation and structurally incapable of being wrong about the reset.
 *
 * The reset is the whole defect. #1090 fixed it by reading `progress.started_at` instead of the
 * mount clock, and the reason it mattered was never the first paint — it was switching to Assess
 * and back, which unmounts and remounts this component and restarted the clock at zero. A scan
 * queued for eleven minutes read "created 0s ago" to the person checking whether the queue was
 * moving.
 *
 * So these mount for real, let the clock run, unmount, and mount again — and assert the second
 * mount agrees with the first. A mount-anchored implementation passes every static test above
 * and fails here, which is the point.
 *
 * Deliberately written against `progress.started_at` alone, the queued phase's own field, so it
 * holds regardless of what any caller does or does not pass alongside it.
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement, act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const { default: DiscoverRunProgress } = await import('./DiscoverRunProgress.jsx')

const agoIso = (secs) => new Date(Date.now() - secs * 1000).toISOString()

const mountQueued = async (progress) => {
  const { container, root } = createTestRoot()
  await act(async () => {
    root.render(createElement(DiscoverRunProgress, { progress, busy: true }))
  })
  return container
}

// unmountAll is async. Not awaiting it tears down the NEXT test's root instead of this one's,
// and the symptom is an empty container rather than an error — worth stating, because it cost a
// round of confusing failures while writing these.
afterEach(async () => { await unmountAll(); vi.useRealTimers() })

describe('a queued run, after switching tabs and coming back', () => {
  it('reports the same age on the second mount as on the first', async () => {
    const startedAt = agoIso(11 * 60)
    const first = await mountQueued({ phase: 'queued', started_at: startedAt })
    expect(first.textContent).toMatch(/created 11m ago/)

    await unmountAll()                                   // leaving Discover for Assess

    const second = await mountQueued({ phase: 'queued', started_at: startedAt })
    expect(second.textContent).toMatch(/created 11m ago/)
    expect(second.textContent).not.toMatch(/created 0s ago/)
  })

  it('keeps the age after the component has been mounted and ticking for a while', async () => {
    // The other half: a clock that runs must not drift away from the server's answer either.
    vi.useFakeTimers()
    const { container, root } = createTestRoot()
    const progress = { phase: 'queued', started_at: agoIso(300) }
    await act(async () => {
      root.render(createElement(DiscoverRunProgress, { progress, busy: true }))
    })
    expect(container.textContent).toMatch(/created 5m ago/)

    await act(async () => { vi.advanceTimersByTime(60_000) })
    expect(container.textContent).toMatch(/created 6m ago/)   // 5m + the minute that passed
  })

  it('survives many remounts without creeping toward zero', async () => {
    // A single remount could pass by luck if the first render happened to be near zero anyway.
    const startedAt = agoIso(42 * 60)
    for (let i = 0; i < 4; i++) {
      const c = await mountQueued({ phase: 'queued', started_at: startedAt })
      expect(c.textContent).toMatch(/created 42m ago/)
      await unmountAll()
    }
  })
})

describe('a queued run whose submission time the server did not give us', () => {
  it('says so in words rather than rendering a zero', async () => {
    const c = await mountQueued({ phase: 'queued' })
    expect(c.textContent).toMatch(/submission time unavailable/)
    expect(c.textContent).not.toMatch(/created 0s ago/)
    expect(c.textContent).not.toMatch(/created \d+s ago/)
  })

  it('still says so after a remount, rather than filling the gap from the mount clock', async () => {
    // The failure mode this replaces: a `?? elapsed` fallback reads as a real age, and reads
    // MOST convincingly right after a remount, when the mount clock is small and plausible.
    await mountQueued({ phase: 'queued' })
    await unmountAll()
    const second = await mountQueued({ phase: 'queued' })
    expect(second.textContent).toMatch(/submission time unavailable/)
    expect(second.textContent).not.toMatch(/created/)
  })

  it('treats an unparseable timestamp as unavailable, not as the epoch', async () => {
    // Date.parse('not a date') is NaN; a naive subtraction renders "NaN" or a 56-year age.
    const c = await mountQueued({ phase: 'queued', started_at: 'not a date' })
    expect(c.textContent).toMatch(/submission time unavailable/)
    expect(c.textContent).not.toMatch(/NaN/)
  })

  it('never renders a negative age when the server clock is ahead of this tab', async () => {
    const c = await mountQueued({ phase: 'queued', started_at: agoIso(-90) })
    expect(c.textContent).toMatch(/created 0s ago/)      // clamped, not negative
    expect(c.textContent).not.toMatch(/created -/)
  })
})
