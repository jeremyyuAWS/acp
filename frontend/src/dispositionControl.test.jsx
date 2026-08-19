import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'
import DispositionControl from './DispositionControl.jsx'

// W4 — the dead-end resolution control. Verifies at the DOM level that: it offers both lanes, a
// reason is mandatory, a successful save calls onSave with (kind, reason), and a recorded
// disposition renders instead of the actions.
afterEach(unmountAll)

const flush = async () => { for (let k = 0; k < 4; k++) await act(async () => { await new Promise((r) => setTimeout(r, 0)) }) }
const mount = async (props) => {
  const { container, root } = createTestRoot()
  await act(async () => { root.render(createElement(DispositionControl, props)) })
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

describe('DispositionControl (W4)', () => {
  it('offers both resolution lanes when nothing is recorded yet', async () => {
    const c = await mount({ sc: '1.2.1', onSave: vi.fn() })
    expect(btnByText(c, 'Attest conformance')).toBeTruthy()
    expect(btnByText(c, 'Mark out of scope')).toBeTruthy()
  })

  it('requires a reason before it will save', async () => {
    const onSave = vi.fn(() => Promise.resolve({ ok: true }))
    const c = await mount({ sc: '1.2.1', onSave })
    await click(btnByText(c, 'Attest conformance'))
    await click(btnByText(c, 'Save'))            // empty reason
    expect(onSave).not.toHaveBeenCalled()
    expect(c.querySelector('[role="alert"]').textContent).toMatch(/reason is required/i)
  })

  it('calls onSave with (kind, reason) on a valid attestation', async () => {
    const onSave = vi.fn(() => Promise.resolve({ ok: true }))
    const c = await mount({ sc: '1.2.1', onSave })
    await click(btnByText(c, 'Attest conformance'))
    await setValue(c.querySelector('input'), 'Verified with NVDA')
    await click(btnByText(c, 'Save'))
    await flush()
    expect(onSave).toHaveBeenCalledWith('attested', 'Verified with NVDA')
  })

  it('routes the out-of-scope lane with its own kind', async () => {
    const onSave = vi.fn(() => Promise.resolve(true))
    const c = await mount({ sc: '1.2.2', onSave })
    await click(btnByText(c, 'Mark out of scope'))
    await setValue(c.querySelector('input'), 'contract excludes video')
    await click(btnByText(c, 'Save'))
    await flush()
    expect(onSave).toHaveBeenCalledWith('out_of_scope', 'contract excludes video')
  })

  it('surfaces a save failure and does not clear the form', async () => {
    const onSave = vi.fn(() => Promise.resolve(false))
    const c = await mount({ sc: '1.2.1', onSave })
    await click(btnByText(c, 'Attest conformance'))
    await setValue(c.querySelector('input'), 'x')
    await click(btnByText(c, 'Save'))
    await flush()
    expect(c.querySelector('[role="alert"]').textContent).toMatch(/could not record/i)
    expect(c.querySelector('input')).toBeTruthy()   // form still open
  })

  it('renders the recorded disposition (with its reason) instead of the actions', async () => {
    const c = await mount({ sc: '1.2.1', disposition: { kind: 'attested', reason: 'Verified with NVDA', actor: 'a@b.co' }, onSave: vi.fn() })
    expect(btnByText(c, 'Attest conformance')).toBeFalsy()
    expect(c.textContent).toMatch(/Manually attested/)
    expect(c.textContent).toMatch(/Verified with NVDA/)
  })

  it('ignores a recorded disposition with no reason (treats it as unresolved)', async () => {
    const c = await mount({ sc: '1.2.1', disposition: { kind: 'attested', reason: '' }, onSave: vi.fn() })
    expect(btnByText(c, 'Attest conformance')).toBeTruthy()
  })
})
