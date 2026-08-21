import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

// R15 · Undo an applied deterministic fix. Pins: nothing renders without the three identifying
// props, the button calls undoAppliedFix(scanId, file, ruleId), a successful undo swaps to the
// "Undone" state and calls onUndone, "nothing to undo" (undone: false) is an error state rather than
// a false success, and re-selecting a different finding re-arms the component instead of carrying
// over the previous row's "Undone" state.

let calls, resolveWith, rejectWith
vi.mock('./api.js', () => ({
  undoAppliedFix: (scanId, file, ruleId) => {
    calls.push({ scanId, file, ruleId })
    if (rejectWith) return Promise.reject(rejectWith)
    return Promise.resolve(resolveWith)
  },
}))

const { default: UndoFix } = await import('./UndoFix.jsx')

let container, root
const mount = async (props) => {
  ;({ container, root } = createTestRoot())
  await act(async () => {
    root.render(createElement(UndoFix, { scanId: 's1', file: 'handbook.docx', ruleId: '1.1.1', ...props }))
  })
  return container
}
const click = async (el) => { await act(async () => { el.dispatchEvent(new MouseEvent('click', { bubbles: true })) }) }
const flush = async () => { await act(async () => { await Promise.resolve(); await Promise.resolve() }) }
const button = (c) => [...c.querySelectorAll('button')].find((b) => /Undo this fix/.test(b.textContent))

beforeEach(() => { calls = []; resolveWith = { undone: true }; rejectWith = null })
afterEach(unmountAll)

describe('UndoFix', () => {
  it('renders nothing without scanId, file or ruleId', async () => {
    expect((await mount({ scanId: null })).textContent).toBe('')
    expect((await mount({ file: null })).textContent).toBe('')
    expect((await mount({ ruleId: null })).textContent).toBe('')
  })

  it('states plainly that nothing on the document is touched', async () => {
    const c = await mount()
    expect(c.textContent).toContain('never modified')
    expect(c.textContent).toContain('does not touch any file')
  })

  it('calls undoAppliedFix with the three identifying values', async () => {
    const c = await mount()
    await click(button(c))
    expect(calls).toEqual([{ scanId: 's1', file: 'handbook.docx', ruleId: '1.1.1' }])
  })

  it('swaps to the Undone state and calls onUndone on success', async () => {
    const onUndone = vi.fn()
    const c = await mount({ onUndone })
    await click(button(c))
    await flush()
    expect(c.textContent).toContain('Undone')
    expect(c.textContent).toContain('fix it the same way')
    expect(onUndone).toHaveBeenCalledTimes(1)
    expect(button(c)).toBeUndefined()   // the button is gone once done
  })

  it('reports "nothing to undo" as an error, not a false success', async () => {
    resolveWith = { undone: false }
    const onUndone = vi.fn()
    const c = await mount({ onUndone })
    await click(button(c))
    await flush()
    expect(c.textContent).toContain('Nothing to undo')
    expect(onUndone).not.toHaveBeenCalled()
    expect(button(c)).toBeTruthy()   // stays actionable, not stuck in a false "Undone"
  })

  it('shows the request error and leaves the control usable to retry', async () => {
    rejectWith = new Error('network down')
    const c = await mount()
    await click(button(c))
    await flush()
    expect(c.textContent).toContain('network down')
    expect(button(c)).toBeTruthy()
  })

  it('re-arms when the selected finding changes, not carrying over the last "Undone"', async () => {
    const c = await mount()
    await click(button(c))
    await flush()
    expect(c.textContent).toContain('Undone')

    await act(async () => {
      root.render(createElement(UndoFix, { scanId: 's1', file: 'onboarding.docx', ruleId: '1.3.1' }))
    })
    expect(c.textContent).not.toContain('Undone')
    expect(button(c)).toBeTruthy()
  })

  it('disables the button and relabels it while the request is in flight', async () => {
    // The mocked undoAppliedFix already returns a real (not pre-settled) Promise, so the state is
    // checked synchronously right after the click, before it resolves. The label itself changes to
    // "Undoing…", so this queries the button directly rather than through the "Undo this fix" filter.
    const c = await mount()
    act(() => { button(c).dispatchEvent(new MouseEvent('click', { bubbles: true })) })
    const b = c.querySelector('button')
    expect(b.disabled).toBe(true)
    expect(b.textContent).toBe('Undoing…')
    await flush()
  })
})
