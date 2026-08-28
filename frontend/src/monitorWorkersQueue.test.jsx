/**
 * Monitor → Workers & Queue: the live operational deep dive ("Monitor tells me why"), distinct
 * from Settings' Worker Configuration tab (capacity CONFIG only — see settingsAccessScope.test.jsx)
 * and from an in-scan "what is happening right now" panel (a later slice, not built yet).
 *
 * QueuePanel is already fully self-contained (own polling, own state) — this only proves Monitor
 * mounts it, not QueuePanel's own internal behavior (no dedicated test file for that exists).
 */
import { describe, it, expect, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

const { default: Monitor } = await import('./Monitor.jsx')

afterEach(unmountAll)

const settle = async () => {
  for (let k = 0; k < 3; k++) await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
}
const render = async (props = {}) => {
  const { container, root } = createTestRoot()
  await act(async () => {
    root.render(createElement(Monitor, { run: null, scanList: [], sources: [], files: [], ...props }))
  })
  await settle()
  return container
}

describe('the Workers & Queue section', () => {
  it('mounts QueuePanel — the same durable-queue view Remediate uses', async () => {
    const c = await render()
    expect(c.textContent).toMatch(/Workers & Queue/)
    expect(c.textContent).toMatch(/Async job queue/)
  })

  it('points to Settings for capacity changes rather than duplicating the control here', async () => {
    const c = await render()
    expect(c.textContent).toMatch(/Settings.*Worker Configuration/)
  })
})
