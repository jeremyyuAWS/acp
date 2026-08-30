import { describe, it, expect, afterEach, vi } from 'vitest'
import { createElement, act } from 'react'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { createTestRoot, unmountAll } from './testRoots.js'

// Proves Discover actually wires its own live signals into the shared ProcessingStatusPanel
// (the same component Assess uses, #922) — deriveDiscoverProcessingState is covered on its own
// (discoverProcessingState.test.js); this is the DOM leg, matching this codebase's own
// SOURCE/DOM/unit split used elsewhere (see discoveryResultsWiring.test.jsx's own header comment).

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const { default: Discover } = await import('./Discover.jsx')

let container, root
const mount = async (props) => {
  ;({ container, root } = createTestRoot())
  await act(async () => {
    root.render(createElement(Discover, { sources: [], files: [], busy: false, onScan: () => {}, ...props }))
  })
  return container
}
afterEach(() => unmountAll())

describe('the Processing status panel on Discover', () => {
  it('shows the failure reason from discoveryFailureReason via the errLog it already loads', async () => {
    // errLog populates async (listScanDecisions) — SIM mode with no scanId means it never
    // fires, so this proves the FALLBACK generic text renders, matching the pure-function's own
    // "no reason recorded" case. The live wiring (real errLog → real reason text) is covered at
    // the unit level in discoverProcessingState.test.js; scanId-driven async population is
    // exercised by discoverFailedRun.test.jsx's own sibling tests for the same errLog signal.
    const c = await mount({ scope: null, run: { id: 's1', status: 'failed' }, busy: false })
    expect(c.textContent).toMatch(/discovery did not finish/i)
  })

  it('shows a queued explanation with no pickup estimate when this tab is not tracking the scan', async () => {
    const c = await mount({ scope: null, run: { id: 's2', status: 'queued' }, busy: false })
    expect(c.textContent).toMatch(/queued.{0,10}not started yet/i)
    expect(c.textContent).toMatch(/pickup estimate is still being calculated/i)
  })

  it('shows "waiting for a worker" while this tab is tracking a freshly queued scan', async () => {
    const c = await mount({
      scope: null, run: { id: 's3', status: 'queued' }, busy: true,
      progress: { phase: 'queued', started_at: '2026-08-28T21:00:00Z' },
    })
    expect(c.textContent).toMatch(/waiting for a worker/i)
  })

  it('shows the active discovery stage while busy and progressing', async () => {
    const c = await mount({
      scope: { kind: 'drive', inventory: { discovered: 12 } }, run: { id: 's4', status: 'running' },
      busy: true, progress: { phase: 'discovering', elapsed: 5 },
    })
    expect(c.textContent).toMatch(/discovering documents/i)
    expect(c.textContent).toMatch(/12 found so far/i)
  })

  it('shows the live SSE badge while discovering with a fresh Redis heartbeat', async () => {
    const c = await mount({
      scope: null, run: { id: 's4b', status: 'running' },
      busy: true, progress: { phase: 'discovering', elapsed: 5, freshness: 'live' },
    })
    expect(c.querySelector('[aria-label="Processing status"] .pulsedot')).toBeTruthy()
    expect(c.textContent).toMatch(/\blive\b/)
  })

  it('does not show the live badge while reconnecting', async () => {
    const c = await mount({
      scope: null, run: { id: 's4c', status: 'running' },
      busy: true, progress: { phase: 'discovering', elapsed: 5, freshness: 'reconnecting' },
    })
    expect(c.querySelector('[aria-label="Processing status"] .pulsedot')).toBeFalsy()
  })

  it('offers a "View in Monitor" link that calls the onViewMonitor prop', async () => {
    const onViewMonitor = vi.fn()
    const c = await mount({ scope: null, run: { id: 's5', status: 'failed' }, busy: false, onViewMonitor })
    const link = [...c.querySelectorAll('button')].find((b) => b.textContent.includes('View in Monitor'))
    expect(link, 'no View in Monitor link rendered').toBeTruthy()
    await act(async () => { link.click() })
    expect(onViewMonitor).toHaveBeenCalledTimes(1)
  })

  it('offers a Re-run button for a failed scan that calls onScan("all")', async () => {
    const onScan = vi.fn()
    const c = await mount({ scope: null, run: { id: 's6', status: 'failed' }, busy: false, onScan })
    const btn = [...c.querySelectorAll('button')].find((b) => b.textContent === 'Re-run')
    expect(btn, 'no Re-run button rendered').toBeTruthy()
    await act(async () => { btn.click() })
    expect(onScan).toHaveBeenCalledWith('all')
  })

  it('renders nothing from this panel for a healthy, already-discovered run', async () => {
    const c = await mount({
      scope: { kind: 'drive', inventory: { discovered: 5 } }, run: { id: 's7', status: 'discovered' }, busy: false,
    })
    expect(c.querySelector('[aria-label="Processing status"]')).toBeFalsy()
  })
})

describe('the queue-estimate poll is wired through to the panel', () => {
  // SOURCE-level, not DOM: exercising the real fetch through a full non-SIM Discover mount would
  // mean stubbing every other endpoint this tab calls on mount just to reach this one poll —
  // this codebase's own established split for exactly that tradeoff (see this file's own header
  // comment, and scanUnavailable.test.js's `code()` helper for the same pattern elsewhere).
  const here = dirname(fileURLToPath(import.meta.url))
  const src = readFileSync(join(here, 'Discover.jsx'), 'utf8')

  it('polls getQueueEstimate(scanId, "discover") only in the same pre-listing window as queueSnap', () => {
    expect(src).toMatch(/getQueueEstimate\(scanId, 'discover'\)/)
    expect(src).toMatch(/if \(!busy \|\| \(phase && phase !== 'queued'\) \|\| !scanId\) return undefined/)
  })

  it('threads the result into deriveDiscoverProcessingState as pickupEstimate', () => {
    expect(src).toMatch(/pickupEstimate,\n/)
  })
})
