import { describe, it, expect, afterEach } from 'vitest'
import { createElement, act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'

// handlers._scan_discover records scope.enumeration {complete, truncated, files_found, …} at
// listing time so a partial listing can be told from a whole one without re-deriving it. Nothing
// rendered it: a run that stopped at the per-run file cap showed its partial counts on the estate
// bar in the same voice as a complete run — "N documents discovered", stated as the estate. This
// pins that a partial listing says so, and — the half that actually keeps the banner worth
// reading — that a complete or unrecorded one stays quiet.

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

const PARTIAL = /part of the estate, not all of it|inventory may be incomplete/i

const runWith = (enumeration, extra = {}) => ({
  id: 's1', status: 'discovered', scope: { kind: 'drive', enumeration }, ...extra,
})

describe('a partial discovery snapshot', () => {
  it('says the inventory is not the whole estate when the listing was truncated', async () => {
    const c = await mount({
      scope: { kind: 'drive', inventory: { discovered: 50000 } },
      run: runWith({ complete: false, truncated: true, files_found: 50000 }),
    })
    expect(c.textContent).toMatch(PARTIAL)
    expect(c.textContent).toMatch(/50,000/)
  })

  it('flags an incomplete listing that was not truncated', async () => {
    const c = await mount({
      scope: { kind: 'drive', inventory: { discovered: 4 } },
      run: runWith({ complete: false, truncated: false, files_found: 4 }),
    })
    expect(c.textContent).toMatch(PARTIAL)
  })

  it('stays quiet for a verifiably complete listing', async () => {
    const c = await mount({
      scope: { kind: 'drive', inventory: { discovered: 4 } },
      run: runWith({ complete: true, truncated: false, files_found: 4 }),
    })
    expect(c.textContent).not.toMatch(PARTIAL)
  })

  it('stays quiet for a run recorded before the enumeration flag existed', async () => {
    // Every scan older than the resilience work has no scope.enumeration. Warning on those would
    // band the whole scan history, and a banner that fires on good runs stops being read.
    const c = await mount({
      scope: { kind: 'drive', inventory: { discovered: 4 } },
      run: { id: 's2', status: 'discovered', scope: { kind: 'drive' } },
    })
    expect(c.textContent).not.toMatch(PARTIAL)
  })

  it('does not stack a second banner on a failed run', async () => {
    // The failed banner says something stronger ("discovery did not finish"). Two alerts about
    // one run read as two separate problems.
    const c = await mount({
      scope: null,
      run: runWith({ complete: false, truncated: true, files_found: 2 }, { status: 'failed' }),
    })
    expect(c.textContent).toMatch(/discovery did not finish/i)
    expect(c.textContent).not.toMatch(PARTIAL)
  })

  it('stays quiet while the scan is still running', async () => {
    // The estate bar already calls its counts provisional during a scan.
    const c = await mount({
      busy: true,
      scope: { kind: 'drive', inventory: { discovered: 4 } },
      run: runWith({ complete: false, truncated: true, files_found: 4 }),
    })
    expect(c.textContent).not.toMatch(PARTIAL)
  })
})
