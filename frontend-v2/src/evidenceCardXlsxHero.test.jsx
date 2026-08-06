// Problem 1 — an xlsx image finding must LEAD with the isolated embedded image, not a whole-sheet
// render (a grid of cells that buries the flagged picture). The hero becomes the image itself, and
// the small duplicate thumb beside the text is suppressed. pptx keeps the page-render hero.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

vi.mock('./api.js', () => ({
  suggestFix: vi.fn(),
  getFileRemediationDiffs: () => Promise.resolve([]),
  aiProvenance: () => null,
  getFileThumbnail: () => Promise.resolve(null),
  getFilePage: () => Promise.resolve(null),
  getFileGeometry: () => Promise.resolve(null),
  getScanAiCalls: () => Promise.resolve([]),
  validateAlt: () => Promise.resolve({}),
}))

// Unmount every root this file mounts — see testRoots.js.
afterEach(unmountAll)

const { default: EvidenceCard } = await import('./EvidenceCard.jsx')

const PNG = 'data:image/png;base64,iVBORw0KGgo='
const imageItem = (file, kind) => ({
  id: 7, scan_id: 's1', file, rule_id: '1.1.1', rule_name: 'Non-text Content',
  status: 'pending', finding_count: 1,
  proposals: [{ locator: 'xl/drawings/drawing1.xml#Image 1', proposed_value: 'Mark as decorative',
                thumb: PNG, ...(kind ? { kind } : {}) }],
})

let container, root
const mount = async (item) => {
  ;({ container, root } = createTestRoot())
  await act(async () => {
    root.render(createElement(EvidenceCard, { item, onAct: vi.fn().mockResolvedValue(undefined) }))
  })
}
beforeEach(() => { document.body.innerHTML = '' })

describe('EvidenceCard — xlsx leads with the isolated image', () => {
  it('renders the isolated-image hero for an xlsx image finding', async () => {
    await mount(imageItem('sheet.xlsx'))
    const hero = container.querySelector('.evcard-hero-img')
    expect(hero).toBeTruthy()
    expect(hero.querySelector('img').getAttribute('src')).toBe(PNG)
    expect(hero.textContent).toMatch(/isolated from the sheet/i)
  })

  it('suppresses the small duplicate thumb beside the text (image is already the hero)', async () => {
    await mount(imageItem('sheet.xlsx'))
    expect(container.querySelector('.evcard-thumb')).toBeFalsy()
  })

  it('does NOT hijack the hero for a pptx image finding (scoped to xlsx)', async () => {
    await mount(imageItem('deck.pptx'))
    expect(container.querySelector('.evcard-hero-img')).toBeFalsy()
    // the pptx image still shows as the small object thumb beside the text
    expect(container.querySelector('.evcard-thumb')).toBeTruthy()
  })

  it('does NOT hijack the hero for an xlsx reading-order (whole-page) thumb', async () => {
    await mount(imageItem('sheet.xlsx', 'reading-order'))
    expect(container.querySelector('.evcard-hero-img')).toBeFalsy()
  })
})
