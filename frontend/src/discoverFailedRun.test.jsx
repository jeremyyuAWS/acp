import { describe, it, expect, afterEach } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { createElement, act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'

// A listing failure (expired Drive token, a transient API error, the worker dying mid-list)
// leaves scan_runs at status='failed' — set by handlers._scan_discover (api/handlers.py) right
// before it re-raises, so the row is not left stuck at 'running' with scope=NULL forever. Without
// a distinct rendering here, that row reads exactly like a clean, empty scan: "0 documents
// discovered", "Discovery completion time not recorded", "inventory could not be read" — every one
// of them the honest text for "nothing happened yet", none of them saying discovery actually broke.

globalThis.IS_REACT_ACT_ENVIRONMENT = true

// source — the failed banner reads the SPECIFIC recorded reason, not a static string.
//
// discoveryFailureReason.js is fully covered as a pure function in its own test file; a DOM test
// here would need to mock the async listScanDecisions() fetch that populates errLog, which is
// exactly the pattern this codebase already avoids for the sibling feature next to it
// (buildUnreadableWhy/errLog — see unreadableWhy.test.jsx for the pure-function coverage and
// discoveryResultsWiring.test.jsx for the source check, never a mocked-fetch DOM test). A source
// regex is what catches the failure mode that actually matters here: the import or the prop name
// silently drifting so the banner falls back to the generic text for every failure, forever.
const here = dirname(fileURLToPath(import.meta.url))
const discoverSrc = readFileSync(join(here, 'Discover.jsx'), 'utf8')
describe('source — the failed banner reads the recorded reason', () => {
  it('imports discoveryFailureReason and derives it from errLog', () => {
    expect(discoverSrc).toMatch(/import \{ discoveryFailureReason \} from '\.\/discoveryFailureReason\.js'/)
    expect(discoverSrc).toMatch(/discoveryFailureReason\(errLog\)/)
  })

  it('renders failureReason in the failed banner, with the old generic text only as a fallback', () => {
    expect(discoverSrc).toMatch(/failureReason\s*\n?\s*\? <>Discovery did not finish: \{failureReason\}\.<\/>/)
    expect(discoverSrc).toMatch(/the last attempt to list this source failed/)
  })
})

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

// Found live 2026-08-28, scan 90203ef148e3: a queued scan displayed with busy=false (this tab
// never reconnected to it — e.g. the default-scan pick landed on it, not an active start/reconnect)
// showed "0 documents discovered · 0 could not be read" with no explanation at all. The notice
// that fixed this originally lived here as its own banner; it was consolidated into
// ProcessingStatusPanel (2026-08-28, after a stakeholder review flagged two near-identical blue
// banners stacked on this exact screen) — this now asserts on that single surviving notice.
describe('a queued run this tab is not tracking live', () => {
  it('explains that the scan has not started yet, distinctly from a failure', async () => {
    const c = await mount({ scope: null, run: { id: 's7', status: 'queued' }, busy: false })
    expect(c.textContent).toMatch(/not started yet/i)
    expect(c.textContent).not.toMatch(/discovery did not finish/i)
    expect(c.querySelector('[role="alert"]')).toBeFalsy()
    expect(c.querySelector('[role="status"]')).toBeTruthy()
  })

  it('does not show it while this tab IS tracking the scan live (busy)', async () => {
    const c = await mount({ scope: null, run: { id: 's7', status: 'queued' }, busy: true })
    expect(c.textContent).not.toMatch(/not started yet/i)
  })
})
