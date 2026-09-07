import { describe, expect, it } from 'vitest'
import { runProgress } from './AdminLiveTraffic.jsx'

// 2026-09-07: an Assess tile read "200%" with its bar drawn clean out of the card — two documents
// completed against an expected total of one. Gauges are bounded at 100; the excess is named.
describe('A run tile never reads past 100%', () => {
  it('caps the percentage and reports the excess separately', () => {
    expect(runProgress({ completed: 2, total: 1 })).toEqual({ pct: 100, over: true, excess: 1 })
  })

  it('is an ordinary ratio inside the bound', () => {
    expect(runProgress({ completed: 8, total: 20 })).toEqual({ pct: 40, over: false, excess: 0 })
    expect(runProgress({ completed: 1, total: 1 })).toEqual({ pct: 100, over: false, excess: 0 })
  })

  it('reads a missing total as nothing to report, not as infinity', () => {
    expect(runProgress({ completed: 3, total: 0 })).toEqual({ pct: 0, over: false, excess: 0 })
    expect(runProgress({})).toEqual({ pct: 0, over: false, excess: 0 })
  })
})

// --- The tile itself, not just the arithmetic --------------------------------------------------
// A correct helper that the tile stopped calling would leave this file green and the card
// overflowing again. So the node is rendered and its bar's width read back from the DOM.
import { afterEach, vi } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

// Handle needs a live ReactFlow node context; nothing under test does. Everything else is real.
vi.mock('@xyflow/react', async (importOriginal) => ({
  ...(await importOriginal()),
  Handle: () => createElement('span', { 'data-handle': '' }),
}))

const { RunNode } = await import('./AdminLiveTraffic.jsx')

afterEach(async () => { await unmountAll() })

async function tile(run) {
  const { root, container } = createTestRoot()
  await act(async () => { root.render(createElement(RunNode, { data: { run } })) })
  return container
}

describe('The run tile draws a bounded bar and names the discrepancy', () => {
  const over = { stage: 'assess', status: 'active', owner: 'a@b', completed: 2, total: 1, running: 0 }

  it('never draws the bar past the card', async () => {
    const container = await tile(over)
    expect(container.querySelector('[data-testid="run-progress-bar"]').style.width).toBe('100%')
  })

  it('labels the tile 100%, not 200%', async () => {
    const text = (await tile(over)).textContent
    expect(text).toContain('100%')
    expect(text).not.toContain('200%')
  })

  it('says the expected total is stale rather than hiding the extra document', async () => {
    const note = (await tile(over)).querySelector('[role="note"]')
    expect(note?.textContent).toContain('1 more completed than the 1 expected')
    expect(note?.textContent).toContain('expected total is stale')
  })

  it('shows no discrepancy note on an ordinary run', async () => {
    const container = await tile({ ...over, completed: 8, total: 20 })
    expect(container.querySelector('[role="note"]')).toBeNull()
    expect(container.querySelector('[data-testid="run-progress-bar"]').style.width).toBe('40%')
  })
})
