import { describe, it, expect, afterEach } from 'vitest'
import { createElement, act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const { default: UtilizationBar } = await import('./UtilizationBar.jsx')

let container, root
const mount = async (props) => {
  ;({ container, root } = createTestRoot())
  await act(async () => { root.render(createElement(UtilizationBar, props)) })
  return container
}
afterEach(unmountAll)

describe('UtilizationBar', () => {
  it('renders nothing when percent is null', async () => {
    const c = await mount({ label: 'CPU', percent: null })
    expect(c.textContent).toBe('')
  })

  it('shows the label and percent as text', async () => {
    const c = await mount({ label: 'CPU', percent: 18 })
    expect(c.textContent).toMatch(/CPU 18%/)
  })

  it('sizes the fill bar to the percent', async () => {
    const c = await mount({ label: 'Memory', percent: 40 })
    const fill = c.querySelector('span[style*="width: 40%"]')
    expect(fill).toBeTruthy()
  })

  it('clamps a fill above 100 to 100%', async () => {
    const c = await mount({ label: 'CPU', percent: 130 })
    expect(c.textContent).toMatch(/CPU 130%/)   // the TEXT shows the real number
    const fill = c.querySelector('span[style*="width: 100%"]')  // the BAR never overflows
    expect(fill).toBeTruthy()
  })

  it('colors the fill green below the warning threshold', async () => {
    const c = await mount({ label: 'CPU', percent: 30 })
    const fill = c.querySelector('span[style*="background: rgb(26, 127, 55)"]')
    expect(fill).toBeTruthy()
  })

  it('colors the fill amber between the warning and high thresholds', async () => {
    const c = await mount({ label: 'CPU', percent: 65 })
    const fill = c.querySelector('span[style*="background: rgb(133, 79, 11)"]')
    expect(fill).toBeTruthy()
  })

  it('colors the fill red at or above the high-utilization threshold, matching the diagnosis layer', async () => {
    const c = await mount({ label: 'CPU', percent: 80 })
    const fill = c.querySelector('span[style*="background: rgb(138, 42, 32)"]')
    expect(fill).toBeTruthy()
  })

  it('has an accessible label naming the metric and value', async () => {
    const c = await mount({ label: 'Memory', percent: 55 })
    expect(c.querySelector('[aria-label="Memory utilization 55%"]')).toBeTruthy()
  })
})
