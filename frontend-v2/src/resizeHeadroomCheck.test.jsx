import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

// ADR 0024 Tier B.2 — the measured-fit affordance on the 1.4.4 Resize Text finding. Pins on-demand
// fetch, a measured overflow as actionable, measured headroom as "verify" (never a certified pass),
// and honest degrade.

// Unmount every root this file mounts — see testRoots.js.
afterEach(unmountAll)

const getFileResize = vi.fn()
vi.mock('./api.js', () => ({ getFileResize: (...a) => getFileResize(...a) }))

const { default: ResizeHeadroomCheck } = await import('./ResizeHeadroomCheck.jsx')

let container, root
const mount = async () => {
  ;({ container, root } = createTestRoot())
  await act(async () => { root.render(createElement(ResizeHeadroomCheck, { scanId: 's1', file: 'deck.pptx' })) })
}
const settle = async (n = 4) => { for (let k = 0; k < n; k++) await act(async () => { await new Promise((r) => setTimeout(r, 0)) }) }
const click = async (el) => { await act(async () => { el.dispatchEvent(new MouseEvent('click', { bubbles: true })) }) }
const text = () => container.textContent
const btn = () => container.querySelector('button')

beforeEach(() => { getFileResize.mockReset() })

describe('ResizeHeadroomCheck (Tier B.2 measured fit)', () => {
  it('measures on demand and reports an overflow as actionable', async () => {
    getFileResize.mockResolvedValue({ measured: true, worst_fill: 0.7, worst_shape: 'Body 1', any_overflow_at_200: true, checked: 1, total: 1 })
    await mount()
    await click(btn()); await settle()
    expect(getFileResize).toHaveBeenCalledWith('s1', 'deck.pptx')
    expect(text()).toContain('70%')
    expect(text().toLowerCase()).toContain('clip')
  })

  it('headroom says verify, never a certified pass', async () => {
    getFileResize.mockResolvedValue({ measured: true, worst_fill: 0.3, worst_shape: 'Body 2', any_overflow_at_200: false, checked: 1, total: 1 })
    await mount(); await click(btn()); await settle()
    expect(text()).toContain('30%')
    expect(text().toLowerCase()).toContain('verify')
    expect(text().toLowerCase()).not.toContain('pass')
  })

  it('degrades to an honest note when the text cannot be isolated', async () => {
    getFileResize.mockResolvedValue({ measured: false, reason: 'no_text_measured' })
    await mount(); await click(btn()); await settle()
    expect(text().toLowerCase()).toContain('verify by eye')
    expect(text()).not.toContain('%')
  })
})
