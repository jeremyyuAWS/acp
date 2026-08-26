/**
 * Discover's scan-infra readiness warning — GET /readyz is checked on mount (and again after any
 * scan finishes) so a worker outage reads as "this may not work" BEFORE the click, instead of a
 * silent stall discovered only after clicking "Re-scan all sources" (the 2026-08-26 incident:
 * a queued job sat unclaimed with zero signal until the run "finished" showing 0 documents).
 * Non-blocking by design — the button stays enabled regardless of what this shows.
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement, act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'

const checkReadiness = vi.fn()
vi.mock('./api.js', () => ({
  checkReadiness: (...a) => checkReadiness(...a),
  getScanInventory: vi.fn(),
  listScanDecisions: vi.fn(),
  overrideLifecycleRecommendation: vi.fn(),
  acknowledgeScan: vi.fn(),
  unacknowledgeScan: vi.fn(),
}))

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
const flush = async () => { await act(async () => {}) }
afterEach(() => { unmountAll(); checkReadiness.mockReset() })

describe('scan-infra readiness warning', () => {
  it('shows a warning when /readyz reports not-ready', async () => {
    checkReadiness.mockResolvedValue({ ready: false, degraded: ['no_workers'] })
    const c = await mount({})
    await flush()
    expect(c.textContent).toMatch(/scan infrastructure looks degraded/i)
    expect(c.textContent).toMatch(/no_workers/)
  })

  it('shows nothing when /readyz reports ready', async () => {
    checkReadiness.mockResolvedValue({ ready: true, degraded: [] })
    const c = await mount({})
    await flush()
    expect(c.textContent).not.toMatch(/scan infrastructure looks degraded/i)
  })

  it('shows nothing while the probe is inconclusive (network error resolves null)', async () => {
    checkReadiness.mockResolvedValue(null)
    const c = await mount({})
    await flush()
    expect(c.textContent).not.toMatch(/scan infrastructure looks degraded/i)
  })

  it('never shows while a scan is actively running', async () => {
    checkReadiness.mockResolvedValue({ ready: false, degraded: ['no_workers'] })
    const c = await mount({ busy: true })
    await flush()
    expect(c.textContent).not.toMatch(/scan infrastructure looks degraded/i)
  })

  it('does not disable "Re-scan all sources" while degraded — it is a warning, not a gate', async () => {
    checkReadiness.mockResolvedValue({ ready: false, degraded: ['no_workers'] })
    const c = await mount({})
    await flush()
    const btn = [...c.querySelectorAll('button')].find((b) => /Re-scan all sources/.test(b.textContent))
    expect(btn).toBeTruthy()
    expect(btn.disabled).toBe(false)
  })
})
