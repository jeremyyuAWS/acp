import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const { default: DiscoveryQueuedPlaceholder } = await import('./DiscoveryQueuedPlaceholder.jsx')

let container, root
const mount = async (props) => {
  ;({ container, root } = createTestRoot())
  await act(async () => { root.render(createElement(DiscoveryQueuedPlaceholder, props)) })
  return container
}
afterEach(() => unmountAll())

describe('DiscoveryQueuedPlaceholder', () => {
  it('says results will appear when processing begins', async () => {
    const c = await mount({ previousCount: null, previousAt: null })
    expect(c.textContent).toMatch(/Discovery results will appear here when processing begins/i)
  })

  it('shows the previous inventory count and date when a real previous run exists', async () => {
    const c = await mount({
      previousCount: 170,
      previousAt: { recorded: true, absolute: 'Aug 27, 2026, 3:40 PM EDT' },
    })
    expect(c.textContent).toMatch(/Previous inventory: 170 files/)
    expect(c.textContent).toMatch(/from Aug 27, 2026, 3:40 PM EDT/)
  })

  it('singularizes the file count for exactly one previous file', async () => {
    const c = await mount({ previousCount: 1, previousAt: { recorded: true, absolute: 'x' } })
    expect(c.textContent).toMatch(/1 file\b/)
    expect(c.textContent).not.toMatch(/1 files/)
  })

  it('omits the "from <date>" clause when no date was recorded, without inventing one', async () => {
    const c = await mount({ previousCount: 12, previousAt: { recorded: false } })
    expect(c.textContent).toMatch(/Previous inventory: 12 files/)
    expect(c.textContent).not.toMatch(/from /)
  })

  it('shows no previous-inventory line for a previousCount of exactly 0', async () => {
    const c = await mount({ previousCount: 0, previousAt: null })
    expect(c.textContent).not.toMatch(/Previous inventory/)
  })

  it('shows no previous-inventory line for a null previousCount (genuinely first scan)', async () => {
    const c = await mount({ previousCount: null, previousAt: null })
    expect(c.textContent).not.toMatch(/Previous inventory/)
  })

  it('offers a "View previous run" action that calls onShowPrevious', async () => {
    const onShowPrevious = vi.fn()
    const c = await mount({
      previousCount: 5, previousAt: { recorded: true, absolute: 'x' }, onShowPrevious,
    })
    const btn = [...c.querySelectorAll('button')].find((b) => b.textContent.includes('View previous run'))
    expect(btn, 'no View previous run button rendered').toBeTruthy()
    await act(async () => { btn.click() })
    expect(onShowPrevious).toHaveBeenCalledTimes(1)
  })

  it('does not offer the action when no callback is given', async () => {
    const c = await mount({ previousCount: 5, previousAt: { recorded: true, absolute: 'x' } })
    expect(c.textContent).not.toMatch(/View previous run/)
  })
})
