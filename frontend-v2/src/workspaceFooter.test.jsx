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

  const stepItems = () => [...container.querySelectorAll('[role=listitem]')]

  it('without activeStep the guide is decorative — no step is marked current', async () => {
    await render({ position: 1, total: 3 })
    expect(container.querySelector('[aria-current=step]')).toBeNull()
  })

  it('lights the active step and checks off the ones behind it', async () => {
    // activeStep 2 → Show + Review are done (✓), Verify is the live step.
    await render({ position: 1, total: 3, activeStep: 2 })
    const current = container.querySelector('[aria-current=step]')
    expect(current.textContent).toContain('Verify the result')
    const items = stepItems()
    expect(items[0].textContent).toContain('✓')   // Show the problem — done
    expect(items[1].textContent).toContain('✓')   // Review — done
    expect(items[2].getAttribute('aria-current')).toBe('step')
  })

  it('when the finding is fully done (3) no step is active and all are checked', async () => {
    await render({ position: 1, total: 3, activeStep: 3 })
    expect(container.querySelector('[aria-current=step]')).toBeNull()
    expect(stepItems().every((it) => it.textContent.includes('✓'))).toBe(true)
  })
})
