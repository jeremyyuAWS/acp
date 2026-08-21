/**
 * The self-service "Reset my test data" control in Settings → My Data.
 *
 * Sibling of the admin-only ResetData (global reset_analytics): this one has no scope choice and
 * no admin gate — any signed-in user clears only their OWN scans. Pins: typed-confirm gates the
 * button exactly like ResetData, the call carries no target (it's always "mine"), and the result
 * message names the cleared owner without exposing anyone else's data.
 */
import { describe, it, expect, afterEach, vi } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

const resetMyData = vi.fn(() => Promise.resolve({ owner: 'jeremy@acp.io', cleared_tables: ['scan_runs', 'file_records'] }))

vi.mock('./api.js', () => ({ resetMyData }))

afterEach(() => { unmountAll(); resetMyData.mockClear() })

const { ResetMyData } = await import('./Settings.jsx')

const render = async () => {
  const { container, root } = createTestRoot()
  await act(async () => { root.render(createElement(ResetMyData)) })
  return container
}
const btn = (c) => [...c.querySelectorAll('button')].find((b) => b.textContent.includes('Reset my data'))
const typeConfirm = async (c, val) => {
  const input = c.querySelector('input')
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set
  await act(async () => { setter.call(input, val); input.dispatchEvent(new Event('input', { bubbles: true })) })
}
const click = async (el) => { await act(async () => { el.dispatchEvent(new MouseEvent('click', { bubbles: true })) }) }

describe('ResetMyData', () => {
  it('disables the button until RESET is typed exactly', async () => {
    const c = await render()
    expect(btn(c).disabled).toBe(true)
    await typeConfirm(c, 'reset')
    expect(btn(c).disabled).toBe(true)     // case-sensitive
    await typeConfirm(c, 'RESET')
    expect(btn(c).disabled).toBe(false)
  })

  it('calls resetMyData with no target argument — it is always "mine"', async () => {
    const c = await render()
    await typeConfirm(c, 'RESET')
    await click(btn(c))
    await act(async () => { await Promise.resolve() })
    expect(resetMyData).toHaveBeenCalledTimes(1)
    expect(resetMyData).toHaveBeenCalledWith()
  })

  it('shows the cleared owner and table count, and clears the confirm field', async () => {
    const c = await render()
    await typeConfirm(c, 'RESET')
    await click(btn(c))
    await act(async () => { await Promise.resolve() })
    expect(c.textContent).toContain('cleared 2 table(s) for jeremy@acp.io')
    expect(c.querySelector('input').value).toBe('')
    expect(btn(c).disabled).toBe(true)      // re-armed: needs RESET typed again
  })

  it('surfaces a failure without pretending the reset happened', async () => {
    resetMyData.mockImplementationOnce(() => Promise.reject(new Error('network down')))
    const c = await render()
    await typeConfirm(c, 'RESET')
    await click(btn(c))
    await act(async () => { await Promise.resolve() })
    expect(c.textContent).toContain('network down')
    expect(c.textContent).not.toContain('Reset done')
  })

  it('never mentions other users or a scope choice — this control has neither', async () => {
    const c = await render()
    expect(c.querySelectorAll('input[type="radio"]').length).toBe(0)
    expect(c.textContent.toLowerCase()).not.toContain('grafana')
    expect(c.textContent.toLowerCase()).not.toContain('langfuse')
  })
})
