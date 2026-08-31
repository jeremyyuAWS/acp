import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement, act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'

// Proves Discover actually swaps the results table for DiscoveryQueuedPlaceholder while a new
// scan is queued or tracked pre-listing — not just that the component renders correctly in
// isolation (discoveryQueuedPlaceholder.test.jsx covers that). The point: scope/files/run are
// still the PREVIOUS scan's data during this window (App.jsx only replaces them once the new
// run settles), so the results table must not render as if they were current.

globalThis.IS_REACT_ACT_ENVIRONMENT = true

vi.mock('./api.js', () => ({
  checkReadiness: vi.fn(() => Promise.resolve(null)),
  getScanInventory: vi.fn(() => Promise.resolve(null)),
  listScanDecisions: vi.fn(() => Promise.resolve([])),
  overrideLifecycleRecommendation: vi.fn(),
  acknowledgeScan: vi.fn(),
  unacknowledgeScan: vi.fn(),
  getQueueJob: vi.fn(() => Promise.resolve({})),
  getJobs: vi.fn(() => Promise.resolve({ jobs: [] })),
  setWorkers: vi.fn(() => Promise.resolve({ workers: 0 })),
}))

const { default: Discover } = await import('./Discover.jsx')

let container, root
const mount = async (props) => {
  ;({ container, root } = createTestRoot())
  await act(async () => {
    root.render(createElement(Discover, { sources: [], files: [], busy: false, onScan: () => {}, ...props }))
  })
  return container
}
const rerender = async (props) => {
  await act(async () => {
    root.render(createElement(Discover, { sources: [], files: [], busy: false, onScan: () => {}, ...props }))
  })
}
const settle = async (n = 4) => { for (let k = 0; k < n; k++) await act(async () => { await new Promise((r) => setTimeout(r, 0)) }) }
afterEach(() => unmountAll())

const PREV_RUN = { id: 'prev-1', status: 'discovered', discovered_at: '2026-08-27T15:40:00Z',
                  scope: { kind: 'drive', inventory: { discovered: 170 } } }

describe('the queued placeholder replacing stale results', () => {
  it('replaces the results table while this tab tracks a newly-queued scan (busy, pre-listing)', async () => {
    const c = await mount({
      scope: PREV_RUN.scope, run: PREV_RUN, busy: true, files: [],
      progress: { phase: 'queued' },
    })
    await settle()
    expect(c.textContent).toMatch(/Discovery results will appear here when this scan finishes/i)
    expect(c.textContent).toMatch(/Previous inventory: 170 files/)
    expect(c.querySelector('#discover-inventory-table')).toBeFalsy()
  })

  it('replaces the results table for a known-queued run this tab is not tracking live', async () => {
    const c = await mount({
      scope: PREV_RUN.scope, run: { ...PREV_RUN, status: 'queued' }, busy: false, files: [],
    })
    await settle()
    expect(c.textContent).toMatch(/Discovery results will appear here when this scan finishes/i)
  })

  it.each(['discovering', 'lifecycle', 'connecting'])('keeps old results hidden during %s', async (phase) => {
    const c = await mount({
      scope: PREV_RUN.scope, run: PREV_RUN, busy: true,
      files: [{ file: 'previous-estate.docx', status: 'unassessed' }],
      progress: { phase, elapsed: 5, files_found: 3 },
    })
    await settle()
    expect(c.textContent).toMatch(/Discovery results will appear here when this scan finishes/i)
    expect(c.querySelector('#discover-inventory-table')).toBeFalsy()
    expect(c.querySelector('#disc-documents')).toBeFalsy()
    expect(c.textContent).not.toContain('previous-estate.docx')
  })

  it('shows the real results table for a settled, non-queued run', async () => {
    const c = await mount({
      scope: PREV_RUN.scope, run: PREV_RUN, busy: false, files: [],
    })
    await settle()
    expect(c.textContent).not.toMatch(/Discovery results will appear here when this scan finishes/i)
    expect(c.querySelector('#discover-inventory-table')).toBeTruthy()
  })

  it('"View previous run" reveals the actual results table, still labeled by its own runAt', async () => {
    const c = await mount({
      scope: PREV_RUN.scope, run: PREV_RUN, busy: true, files: [],
      progress: { phase: 'queued' },
      runAt: { recorded: true, absolute: 'Aug 27, 2026, 3:40 PM EDT' },
    })
    await settle()
    const btn = [...c.querySelectorAll('button')].find((b) => b.textContent.includes('View previous run'))
    expect(btn, 'no View previous run button rendered').toBeTruthy()
    await act(async () => { btn.click() })
    expect(c.querySelector('#discover-inventory-table')).toBeTruthy()
    expect(c.textContent).toContain('Previous scan results — not results from the active discovery.')
    expect(c.textContent).not.toMatch(/Discovery results will appear here when this scan finishes/i)
  })

  it('resets the "view previous" reveal when a new scan starts (busy flips true again)', async () => {
    const c = await mount({
      scope: PREV_RUN.scope, run: PREV_RUN, busy: true, files: [],
      progress: { phase: 'queued' },
    })
    await settle()
    const btn = [...c.querySelectorAll('button')].find((b) => b.textContent.includes('View previous run'))
    await act(async () => { btn.click() })
    expect(c.querySelector('#discover-inventory-table')).toBeTruthy()

    // Scan settles, then a second scan starts — the reveal must not carry over to it.
    await rerender({ scope: PREV_RUN.scope, run: PREV_RUN, busy: false, files: [] })
    await settle()
    await rerender({
      scope: PREV_RUN.scope, run: PREV_RUN, busy: true, files: [],
      progress: { phase: 'queued' },
    })
    await settle()
    expect(c.textContent).toMatch(/Discovery results will appear here when this scan finishes/i)
  })

  it('resets the reveal when the active run changes without an idle render', async () => {
    const props = { scope: PREV_RUN.scope, run: PREV_RUN, busy: true, progress: { phase: 'discovering' } }
    const c = await mount({ ...props, activeScanId: 'active-a' })
    await settle()
    await act(async () => { [...c.querySelectorAll('button')].find(b => b.textContent.includes('View previous run')).click() })
    expect(c.querySelector('#discover-inventory-table')).toBeTruthy()
    await rerender({ ...props, activeScanId: 'active-b' })
    expect(c.querySelector('#discover-inventory-table')).toBeFalsy()
  })
})
