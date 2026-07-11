import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { act } from 'react-dom/test-utils'

// The whole point of the strip: "Draft with AI" must describe the image the reviewer is
// LOOKING AT. A vision model sees one image. Silently drafting the first of nineteen would
// caption the wrong picture, and the reviewer would approve alt text for an image they
// never saw — worse than no draft at all.

const suggestFix = vi.fn()
vi.mock('./api.js', () => ({
  suggestFix: (...a) => suggestFix(...a),
  getFileRemediationDiffs: () => Promise.resolve([]),
  aiProvenance: () => null,
  getFileThumbnail: () => Promise.resolve(null),   // Thumbnail.jsx self-hides without a blob
  getFilePage: () => Promise.resolve(null),
  getFileGeometry: () => Promise.resolve(null),
}))

const { default: EvidenceCard } = await import('./EvidenceCard.jsx')

const PNG = 'data:image/png;base64,iVBORw0KGgo='
const item = {
  id: 1, scan_id: 's1', file: 'deck.pptx', rule_id: '1.1.1', rule_name: 'Non-text Content',
  status: 'pending', finding_count: 3,
  evidence: [
    { locator: 'ppt/slides/slide1.xml#rId2', thumb: PNG },
    { locator: 'ppt/slides/slide2.xml#rId3', thumb: PNG },
    { locator: 'ppt/slides/slide3.xml#rId4', thumb: PNG },
  ],
}

let container, root
const mount = async (props = {}) => {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  await act(async () => { root.render(createElement(EvidenceCard, { item, onAct: () => {}, ...props })) })
}
// The picker is gone: each deferred image has its own editor row and its own draft button, so
// the draft targets THAT image by construction — there is no "picked" image to get wrong.
const drafts = () => [...container.querySelectorAll('.evcard-draft-btn')]
const inputs = () => [...container.querySelectorAll('.evcard-rec-input')]
const click = async (el) => { await act(async () => { el.dispatchEvent(new MouseEvent('click', { bubbles: true })) }) }

beforeEach(() => {
  suggestFix.mockReset()
  suggestFix.mockResolvedValue({ suggestion: 'A nurse reviews a chart.', is_template: false, model: 'llava:7b' })
})

describe('EvidenceCard — the drafted image is its own row', () => {
  it('a row draft describes that row’s image', async () => {
    await mount()
    await click(drafts()[0])
    expect(suggestFix).toHaveBeenCalledWith('s1', 'deck.pptx', '1.1.1', 'ppt/slides/slide1.xml#rId2')
  })

  it('a later row draft describes that image, not the first', async () => {
    await mount()
    await click(drafts()[2])
    expect(suggestFix).toHaveBeenCalledWith('s1', 'deck.pptx', '1.1.1', 'ppt/slides/slide3.xml#rId4')
  })

  it('puts the draft into that row only, never another image’s box', async () => {
    await mount()
    await click(drafts()[2])
    expect(inputs().map((t) => t.value)).toEqual(['', '', 'A nurse reviews a chart.'])
  })

  it('shows the server reason when the model could only produce a template', async () => {
    suggestFix.mockResolvedValue({
      suggestion: 'Describe: [what it shows]', is_template: true,
      reason: 'Template only — no vision model is available to look at this image.',
    })
    await mount()
    await click(drafts()[0])
    expect(container.textContent).toContain('no vision model is available')
    expect(container.textContent).not.toContain('no vision model described this image')
  })

  it('sends no locator for a single-value item with no images', async () => {
    // No evidence and no proposals → the single-value editor, whose draft has no per-image target.
    await mount({ item: { ...item, evidence: [], finding_count: 1 } })
    await click(container.querySelector('.evcard-draft-btn'))
    expect(suggestFix).toHaveBeenCalledWith('s1', 'deck.pptx', '1.1.1', undefined)
  })
})
