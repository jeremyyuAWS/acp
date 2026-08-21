import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'
import LifecycleOverrideControl from './LifecycleOverrideControl.jsx'

// Lifecycle rules #8 — the per-file override control. Mirrors dispositionControl.test.jsx's
// coverage shape: a reason is mandatory, a successful save calls onSave(file, reason), a failed
// save surfaces an error and leaves the form open, and a recorded override renders instead of
// the action.
afterEach(unmountAll)

const flush = async () => { for (let k = 0; k < 4; k++) await act(async () => { await new Promise((r) => setTimeout(r, 0)) }) }
const mount = async (props) => {
  const { container, root } = createTestRoot()
  await act(async () => { root.render(createElement(LifecycleOverrideControl, props)) })
  return container
}
const click = async (el) => { await act(async () => { el.dispatchEvent(new MouseEvent('click', { bubbles: true })) }) }
const setValue = async (input, value) => {
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set
    setter.call(input, value)
    input.dispatchEvent(new Event('input', { bubbles: true }))
  })
}
const btnByText = (c, text) => [...c.querySelectorAll('button')].find((b) => b.textContent.trim() === text)

describe('LifecycleOverrideControl (lifecycle rules #8)', () => {
  it('offers the override action when nothing is recorded yet', async () => {
    const c = await mount({ file: 'a.pdf', onSave: vi.fn() })
    expect(btnByText(c, 'Keep this file')).toBeTruthy()
  })

  it('requires a reason before it will save', async () => {
    const onSave = vi.fn(() => Promise.resolve(true))
    const c = await mount({ file: 'a.pdf', onSave })
    await click(btnByText(c, 'Keep this file'))
    await click(btnByText(c, 'Save'))            // empty reason
    expect(onSave).not.toHaveBeenCalled()
    expect(c.querySelector('[role="alert"]').textContent).toMatch(/reason is required/i)
  })

  it('calls onSave with (file, reason) on a valid override', async () => {
    const onSave = vi.fn(() => Promise.resolve(true))
    const c = await mount({ file: 'Finance/old.pdf', onSave })
    await click(btnByText(c, 'Keep this file'))
    await setValue(c.querySelector('input'), 'under active legal hold')
    await click(btnByText(c, 'Save'))
    await flush()
    expect(onSave).toHaveBeenCalledWith('Finance/old.pdf', 'under active legal hold')
  })

  it('surfaces a save failure and does not clear the form', async () => {
    const onSave = vi.fn(() => Promise.resolve(false))
    const c = await mount({ file: 'a.pdf', onSave })
    await click(btnByText(c, 'Keep this file'))
    await setValue(c.querySelector('input'), 'x')
    await click(btnByText(c, 'Save'))
    await flush()
    expect(c.querySelector('[role="alert"]').textContent).toMatch(/could not record/i)
    expect(c.querySelector('input')).toBeTruthy()   // form still open
  })

  it('renders the recorded override (with its reason) instead of the action', async () => {
    const c = await mount({
      file: 'a.pdf',
      override: { reason: 'under active legal hold', actor: 'reviewer@x.com', at: '2026-08-21T10:00:00Z' },
      onSave: vi.fn(),
    })
    expect(btnByText(c, 'Keep this file')).toBeFalsy()
    expect(c.textContent).toMatch(/Kept/)
    expect(c.textContent).toMatch(/under active legal hold/)
  })

  it('Escape cancels the open form without saving', async () => {
    const onSave = vi.fn()
    const c = await mount({ file: 'a.pdf', onSave })
    await click(btnByText(c, 'Keep this file'))
    const input = c.querySelector('input')
    await act(async () => { input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })) })
    expect(onSave).not.toHaveBeenCalled()
    expect(btnByText(c, 'Keep this file')).toBeTruthy()
  })
})
