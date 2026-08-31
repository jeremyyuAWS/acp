/**
 * The pickup estimate must ask about the scan that was just submitted, not the one on screen.
 *
 * WHAT PRODUCTION RECORDED (2026-08-30, Pacific): a discovery submission returned 200 at 9:46:27
 * and a worker claimed the job for scan ad94e943e0f2 at 9:46:50 — while the pickup-estimate
 * request named scan **5e78b8d2cb75**, the PREVIOUS scan. The UI was mixing previous-inventory
 * identity with active-job identity.
 *
 * WHY, exactly. App owns two ids and they are different for the whole time a scan is in flight:
 *
 *     scanId       = run?.id      the DISPLAYED run. App only replaces `run` when pollScanJob
 *                                 RESOLVES — i.e. when the scan finishes — so during the entire
 *                                 in-flight window this is the previous scan.
 *     liveScanId                  set from the submission's own response, next to jobId, the
 *                                 moment the job is accepted.
 *
 * `liveScanId` was already used for stop (App.jsx:1780), the live-assessment panel (:1819) and
 * the Monitor link (:1859). Discover's estimate was the one call site that missed it and used
 * `run?.id`.
 *
 * AND THE OBVIOUS FIX WOULD HAVE BEEN WORSE. `scanId` inside Discover also drives
 * loadDiscoveryInventory, getSourceStatus, acknowledgeScan and the export — all of which
 * legitimately mean the displayed run. Passing `liveScanId || run?.id` as `scanId` would have
 * pointed the inventory loader at a scan with no inventory yet and made acknowledgeScan
 * acknowledge the wrong run. Hence two separate props rather than one redefined one, which is
 * what the tests below pin: same render, two ids, each going to the right place.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement, act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const getQueueEstimate = vi.fn()
const getScanInventory = vi.fn()
const getSourceStatus = vi.fn()
const acknowledgeScan = vi.fn()

vi.mock('./api.js', async (importOriginal) => {
  const real = await importOriginal()
  return {
    ...real,
    getQueueEstimate: (...a) => getQueueEstimate(...a),
    getScanInventory: (...a) => getScanInventory(...a),
    getSourceStatus: (...a) => getSourceStatus(...a),
    acknowledgeScan: (...a) => acknowledgeScan(...a),
  }
})

const { default: Discover } = await import('./Discover.jsx')

const DISPLAYED = '5e78b8d2cb75'      // the previous scan, whose results are on screen
const ACTIVE = 'ad94e943e0f2'         // the scan just submitted

beforeEach(() => {
  getQueueEstimate.mockReset().mockResolvedValue({ available: false })
  getScanInventory.mockReset().mockResolvedValue({ items: [] })
  getSourceStatus.mockReset().mockResolvedValue({})
  acknowledgeScan.mockReset().mockResolvedValue({})
})
afterEach(() => { unmountAll() })

let container, root
const render = async (props) => {
  ;({ container, root } = createTestRoot())
  await act(async () => {
    root.render(createElement(Discover, {
      sources: [], files: [], busy: true, onScan: () => {},
      progress: { phase: 'queued', elapsed: 1 },
      ...props,
    }))
  })
  for (let k = 0; k < 5; k++) await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
  return container
}

const estimateIds = () => getQueueEstimate.mock.calls.map((c) => c[0])


describe('scan B submitted while scan A results are displayed', () => {
  it('estimates for the ACTIVE scan, not the displayed one', async () => {
    // The production case, reproduced as a render: both ids present and different.
    await render({ scanId: DISPLAYED, activeScanId: ACTIVE })

    expect(estimateIds()).toContain(ACTIVE)
    expect(estimateIds()).not.toContain(DISPLAYED)
  })

  it('still loads the DISPLAYED scan\'s inventory', async () => {
    // The half the naive fix would have broken: the estimate moving to the active id must not
    // drag the inventory loader with it — the new scan has no inventory yet.
    await render({ scanId: DISPLAYED, activeScanId: ACTIVE })

    const invIds = getScanInventory.mock.calls.map((c) => c[0])
    expect(invIds.every((id) => id === DISPLAYED)).toBe(true)
    expect(invIds).not.toContain(ACTIVE)
  })

  it('asks source status about the displayed scan, not the active one', async () => {
    await render({ scanId: DISPLAYED, activeScanId: ACTIVE })
    const ids = getSourceStatus.mock.calls.map((c) => c[0])
    expect(ids.every((id) => id === DISPLAYED)).toBe(true)
  })
})


describe('when nothing is in flight', () => {
  it('makes no estimate request at all rather than estimating the finished run', async () => {
    // No fallback to scanId. There is no pickup to estimate when nothing was submitted, and an
    // estimate for a completed scan is exactly the wrong answer that started this.
    await render({ scanId: DISPLAYED, activeScanId: null })
    expect(getQueueEstimate).not.toHaveBeenCalled()
  })

  it('does not estimate once the job has left the queue', async () => {
    await render({ scanId: DISPLAYED, activeScanId: ACTIVE,
                   progress: { phase: 'listing', elapsed: 3 } })
    expect(getQueueEstimate).not.toHaveBeenCalled()
  })
})


describe('a late response from the previous scan', () => {
  it('cannot land on the new scan\'s panel', async () => {
    // Scan A's estimate is still in flight when B starts. A's reply must be discarded: the effect
    // re-runs on activeScanId, and the old closure's `live` flag is already false.
    let resolveA
    getQueueEstimate.mockImplementationOnce(() => new Promise((r) => { resolveA = r }))

    ;({ container, root } = createTestRoot())
    const props = {
      sources: [], files: [], busy: true, onScan: () => {},
      progress: { phase: 'queued', elapsed: 1 },
      scanId: DISPLAYED, activeScanId: 'scan-A',
    }
    await act(async () => { root.render(createElement(Discover, props)) })

    // B starts before A's request settles.
    getQueueEstimate.mockResolvedValue({ available: true, state: 'ok', scan: 'B' })
    await act(async () => {
      root.render(createElement(Discover, { ...props, activeScanId: 'scan-B' }))
    })

    // A finally replies, with a state that would be visibly wrong if it were accepted.
    await act(async () => {
      resolveA({ available: true, state: 'insufficient_history', scan: 'A' })
      await new Promise((r) => setTimeout(r, 0))
    })
    for (let k = 0; k < 4; k++) {
      await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
    }

    // B asked for itself, and A's id was never asked about after the switch.
    expect(estimateIds()).toContain('scan-B')
    const afterSwitch = estimateIds().slice(estimateIds().indexOf('scan-B'))
    expect(afterSwitch).not.toContain('scan-A')
  })
})
