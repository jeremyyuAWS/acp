import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

// ADR 0024 Tier B.1 — the measured-contrast affordance on the 1.4.3-hybrid finding. Pins that it
// (1) fetches on demand, (2) shows a measured FAIL as actionable review evidence, (3) shows a
// measured pass as "meets AA — confirm" (never a certified pass), and (4) degrades to an honest
// note when the pixels are ambiguous or rendering is unavailable.

// Unmount every root this file mounts — see testRoots.js.
afterEach(unmountAll)

const getFileContrast = vi.fn()
vi.mock('./api.js', () => ({ getFileContrast: (...a) => getFileContrast(...a) }))

const { default: HybridContrastCheck } = await import('./HybridContrastCheck.jsx')

let container, root
const mount = async () => {
  ;({ container, root } = createTestRoot())
  await act(async () => { root.render(createElement(HybridContrastCheck, { scanId: 's1', file: 'deck.pptx' })) })
}
const settle = async (n = 4) => { for (let k = 0; k < n; k++) await act(async () => { await new Promise((r) => setTimeout(r, 0)) }) }
const click = async (el) => { await act(async () => { el.dispatchEvent(new MouseEvent('click', { bubbles: true })) }) }
const text = () => container.textContent
const btn = () => container.querySelector('button')

beforeEach(() => { getFileContrast.mockReset() })

describe('HybridContrastCheck (Tier B.1 measured contrast)', () => {
  it('measures on demand and reports a failing ratio as actionable', async () => {
    getFileContrast.mockResolvedValue({ measured: true, worst_ratio: 2.1, worst_shape: 'Title 1', any_fail_aa: true, checked: 2, total: 2 })
    await mount()
    expect(btn()).toBeTruthy()
    await click(btn()); await settle()
    expect(getFileContrast).toHaveBeenCalledWith('s1', 'deck.pptx')
    expect(text()).toContain('2.1:1')
    expect(text()).toContain('fails AA')
  })

  it('a measured pass says meets AA — confirm, never a certified pass', async () => {
    getFileContrast.mockResolvedValue({ measured: true, worst_ratio: 8.3, worst_shape: 'Body', any_fail_aa: false, checked: 1, total: 1 })
    await mount(); await click(btn()); await settle()
    expect(text()).toContain('8.3:1')
    expect(text()).toContain('meets AA')
    expect(text().toLowerCase()).not.toContain('certified')
    expect(text().toLowerCase()).not.toContain('pass')
  })

  it('degrades to an honest note when the background is too busy to measure', async () => {
    getFileContrast.mockResolvedValue({ measured: false, reason: 'ambiguous_background', checked: 3, total: 3 })
    await mount(); await click(btn()); await settle()
    expect(text().toLowerCase()).toContain('busy')
    expect(text()).not.toContain(':1')
  })

  it('says so plainly when rendering is unavailable', async () => {
    getFileContrast.mockResolvedValue({ measured: false, reason: 'render_unavailable' })
    await mount(); await click(btn()); await settle()
    expect(text().toLowerCase()).toContain('verify by eye')
  })
})
