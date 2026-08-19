import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

afterEach(unmountAll)
const { default: WorkspaceFooter } = await import('./WorkspaceFooter.jsx')

let container, root
beforeEach(() => { ;({ container, root } = createTestRoot()) })
const render = async (props) => { await act(async () => { root.render(createElement(WorkspaceFooter, props)) }) }
const click = async (el) => { await act(async () => { el.dispatchEvent(new MouseEvent('click', { bubbles: true })) }) }
const btn = (label) => [...container.querySelectorAll('button')].find((b) => b.getAttribute('aria-label') === label)

describe('WorkspaceFooter — workflow guide + navigation', () => {
  it('spells out the Show → Review → Verify workflow', async () => {
    await render({ position: 2, total: 7 })
    expect(container.textContent).toContain('Show the problem')
    expect(container.textContent).toContain('Review the proposed change')
    expect(container.textContent).toContain('Verify the result')
  })

  it('shows the position as N of M', async () => {
    await render({ position: 3, total: 7 })
    expect(container.textContent).toContain('3 of 7')
  })

  it('disables Previous at the first item and Next at the last', async () => {
    await render({ position: 1, total: 7 })
    expect(btn('Previous finding').disabled).toBe(true)
    expect(btn('Next finding').disabled).toBe(false)
    await render({ position: 7, total: 7 })
    expect(btn('Next finding').disabled).toBe(true)
    expect(btn('Previous finding').disabled).toBe(false)
  })

  it('calls onPrev / onNext when the enabled buttons are clicked', async () => {
    let prev = 0, next = 0
    await render({ position: 4, total: 7, onPrev: () => { prev++ }, onNext: () => { next++ } })
    await click(btn('Previous finding'))
    await click(btn('Next finding'))
    expect([prev, next]).toEqual([1, 1])
  })
})
