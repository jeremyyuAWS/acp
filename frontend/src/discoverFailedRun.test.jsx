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
