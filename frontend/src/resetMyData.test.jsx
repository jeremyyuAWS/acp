// Reset is caller-scoped and requires a confirmation, with no typed phrase.
import { describe, it, expect, afterEach, vi } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

const resetMyData = vi.fn(() => Promise.resolve({ owner: 'jeremy@acp.io', cleared_tables: ['scan_runs', 'file_records'] }))

vi.mock('./api.js', () => ({ resetMyData }))

afterEach(() => { unmountAll(); resetMyData.mockClear(); vi.restoreAllMocks() })

const { ResetMyData } = await import('./Settings.jsx')

const render = async () => {
  const { container, root } = createTestRoot()
  await act(async () => { root.render(createElement(ResetMyData)) })
  return container
}
const btn = (c) => [...c.querySelectorAll('button')].find((b) => b.textContent.includes('Reset my data'))
const click = async (el) => { await act(async () => { el.dispatchEvent(new MouseEvent('click', { bubbles: true })) }) }

describe('ResetMyData', () => {
  it('does not reset when confirmation is cancelled', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    const c = await render()
    expect(c.querySelector('input')).toBeNull()
    await click(btn(c))
    expect(resetMyData).not.toHaveBeenCalled()
  })

  it('calls resetMyData with no target argument — it is always "mine"', async () => {
    const c = await render()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    await click(btn(c))
    await act(async () => { await Promise.resolve() })
    expect(resetMyData).toHaveBeenCalledTimes(1)
    expect(resetMyData).toHaveBeenCalledWith()
  })

  it('shows the cleared owner and table count after confirmation', async () => {
    const c = await render()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    await click(btn(c))
    await act(async () => { await Promise.resolve() })
    expect(c.textContent).toContain('cleared 2 table(s) for jeremy@acp.io')
    expect(c.querySelector('input')).toBeNull()
    expect(btn(c).disabled).toBe(false)
  })

  it('surfaces a failure without pretending the reset happened', async () => {
    resetMyData.mockImplementationOnce(() => Promise.reject(new Error('network down')))
    const c = await render()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
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
