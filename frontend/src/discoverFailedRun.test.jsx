import { describe, it, expect, afterEach } from 'vitest'
import { createElement, act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'

// A listing failure (expired Drive token, a transient API error, the worker dying mid-list)
// leaves scan_runs at status='failed' — set by handlers._scan_discover (api/handlers.py) right
// before it re-raises, so the row is not left stuck at 'running' with scope=NULL forever. Without
// a distinct rendering here, that row reads exactly like a clean, empty scan: "0 documents
// discovered", "Discovery completion time not recorded", "inventory could not be read" — every one
// of them the honest text for "nothing happened yet", none of them saying discovery actually broke.

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

describe('a failed discovery run', () => {
  it('shows an explicit failure banner when run.status is "failed"', async () => {
    const c = await mount({ scope: null, run: { id: 's1', status: 'failed' } })
    expect(c.textContent).toMatch(/discovery did not finish/i)
    expect(c.querySelector('[role="alert"]')).toBeTruthy()
  })

  it('does not show the banner for a healthy run', async () => {
    const c = await mount({ scope: { kind: 'drive', inventory: { discovered: 5 } },
                            run: { id: 's2', status: 'discovered' } })
    expect(c.textContent).not.toMatch(/discovery did not finish/i)
  })

  it('does not show the banner when there is no run yet', async () => {
    const c = await mount({ scope: null, run: null })
    expect(c.textContent).not.toMatch(/discovery did not finish/i)
  })
})

// Found live 2026-08-28: a scan that got orphaned (worker died without ever reaching a terminal
// status) showed "0 documents discovered" with no explanation — status stayed 'running' forever,
// which the 'failed' banner above never covers, and 'cancelled'/'interrupted' (a stop the codebase
// already tracks distinctly elsewhere, e.g. DiscoverRunProgress's own "Discovery stopped" card)
// had no banner here at all when viewed without live progress data. All three are the same shape
// as the failed-run gap this file already pins: a status that means "don't trust these counts",
// silently indistinguishable from a genuinely clean, complete, empty scan.
describe('a run whose counts should not be trusted (stuck, stopped, or interrupted)', () => {
  it('flags a scan stuck at "running" with nothing here tracking it live', async () => {
    const c = await mount({ scope: null, run: { id: 's3', status: 'running' }, busy: false })
    expect(c.textContent).toMatch(/still shows as running/i)
    expect(c.querySelector('[role="alert"]')).toBeTruthy()
  })

  it('does not flag "running" while this tab IS actively tracking it (busy)', async () => {
    const c = await mount({ scope: null, run: { id: 's3', status: 'running' }, busy: true })
    expect(c.textContent).not.toMatch(/still shows as running/i)
  })

  it('explains a user-cancelled run distinctly from a failure', async () => {
    const c = await mount({ scope: null, run: { id: 's4', status: 'cancelled' } })
    expect(c.textContent).toMatch(/stopped before it finished/i)
    expect(c.textContent).not.toMatch(/discovery did not finish/i)
  })

  it('explains a server-interrupted run distinctly from both a failure and a cancel', async () => {
    const c = await mount({ scope: null, run: { id: 's5', status: 'interrupted' } })
    expect(c.textContent).toMatch(/interrupted before it finished/i)
    expect(c.textContent).not.toMatch(/discovery did not finish/i)
    expect(c.textContent).not.toMatch(/stopped before it finished/i)
  })

  it('shows none of these banners for a healthy discovered run', async () => {
    const c = await mount({ scope: { kind: 'drive', inventory: { discovered: 5 } },
                            run: { id: 's6', status: 'discovered' }, busy: false })
    expect(c.querySelector('[role="alert"]')).toBeFalsy()
  })
})

// Found live 2026-08-28: a page showing a stale, already-terminal `run` (from BEFORE the
// currently-tracked scan started — `run` is `scan?.run` in App.jsx, only replaced once a poll
// SETTLES) rendered a live "Discovering documents" progress card directly above a "Discovery was
// stopped before it finished" banner — true of two different scans, read as one. 'running' already
// guarded on `!busy` for the same reason; 'failed' and 'cancelled'/'interrupted' did not.
describe('a stale terminal run does not shadow a scan that is actively in flight', () => {
  it('suppresses the "failed" banner while a new scan is busy', async () => {
    const c = await mount({ scope: null, run: { id: 's1', status: 'failed' }, busy: true })
    expect(c.textContent).not.toMatch(/discovery did not finish/i)
  })

  it('suppresses the "cancelled" banner while a new scan is busy', async () => {
    const c = await mount({ scope: null, run: { id: 's4', status: 'cancelled' }, busy: true })
    expect(c.textContent).not.toMatch(/stopped before it finished/i)
  })

  it('suppresses the "interrupted" banner while a new scan is busy', async () => {
    const c = await mount({ scope: null, run: { id: 's5', status: 'interrupted' }, busy: true })
    expect(c.textContent).not.toMatch(/interrupted before it finished/i)
  })
})
