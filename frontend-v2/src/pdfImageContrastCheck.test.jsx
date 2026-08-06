import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

// ADR 0025 Tier B — the measured-contrast affordance on the PDF text-over-image finding. Pins
// on-demand fetch, a measured fail as actionable, a measured pass as "confirm" (never a certified
// pass), and an honest degrade when the image behind the text is too busy to measure.

// Unmount every root this file mounts — see testRoots.js.
afterEach(unmountAll)

const getFilePdfContrast = vi.fn()
vi.mock('./api.js', () => ({ getFilePdfContrast: (...a) => getFilePdfContrast(...a) }))

const { default: PdfImageContrastCheck } = await import('./PdfImageContrastCheck.jsx')

let container, root
const mount = async () => {
  ;({ container, root } = createTestRoot())
  await act(async () => { root.render(createElement(PdfImageContrastCheck, { scanId: 's1', file: 'doc.pdf' })) })
}
const settle = async (n = 4) => { for (let k = 0; k < n; k++) await act(async () => { await new Promise((r) => setTimeout(r, 0)) }) }
const click = async (el) => { await act(async () => { el.dispatchEvent(new MouseEvent('click', { bubbles: true })) }) }
const text = () => container.textContent
const btn = () => container.querySelector('button')

beforeEach(() => { getFilePdfContrast.mockReset() })

describe('PdfImageContrastCheck (Tier B measured PDF contrast)', () => {
  it('measures on demand and reports a fail as actionable', async () => {
    getFilePdfContrast.mockResolvedValue({ measured: true, worst_ratio: 2.4, any_fail_aa: true, checked: 2, total: 2 })
    await mount()
    await click(btn()); await settle()
    expect(getFilePdfContrast).toHaveBeenCalledWith('s1', 'doc.pdf')
    expect(text()).toContain('2.4:1')
    expect(text().toLowerCase()).toContain('fails aa')
  })

  it('a measured pass says confirm, never a certified pass', async () => {
    getFilePdfContrast.mockResolvedValue({ measured: true, worst_ratio: 8.1, any_fail_aa: false, checked: 1, total: 1 })
    await mount(); await click(btn()); await settle()
    expect(text()).toContain('8.1:1')
    expect(text().toLowerCase()).toContain('confirm')
    expect(text().toLowerCase()).toContain('meets aa')
  })

  it('reports the checked/total cap when it applies', async () => {
    getFilePdfContrast.mockResolvedValue({ measured: true, worst_ratio: 3.2, any_fail_aa: true, checked: 12, total: 20 })
    await mount(); await click(btn()); await settle()
    expect(text()).toContain('12 of 20 runs checked')
  })

  it('degrades to an honest note on a busy background', async () => {
    getFilePdfContrast.mockResolvedValue({ measured: false, reason: 'ambiguous_background' })
    await mount(); await click(btn()); await settle()
    expect(text().toLowerCase()).toContain('verify by eye')
    expect(text()).not.toContain(':1')
  })
})
