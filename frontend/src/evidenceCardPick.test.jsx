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
  getFileThumbnail: () => Promise.resolve(null),   // Thumbnail.jsx self-hides without a blob
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
const thumbs = () => [...container.querySelectorAll('.evcard-evidence-thumb')]
const click = async (el) => { await act(async () => { el.dispatchEvent(new MouseEvent('click', { bubbles: true })) }) }

beforeEach(() => {
  suggestFix.mockReset()
  suggestFix.mockResolvedValue({ suggestion: 'A nurse reviews a chart.', is_template: false, model: 'llava:7b' })
})

describe('EvidenceCard — the drafted image is the picked image', () => {
  it('drafts the FIRST image by default', async () => {
    await mount()
    await click(container.querySelector('.evcard-draft-btn'))
    expect(suggestFix).toHaveBeenCalledWith('s1', 'deck.pptx', '1.1.1', 'ppt/slides/slide1.xml#rId2')
  })

  it('drafts the image the reviewer selected, not the first', async () => {
    await mount()
    await click(thumbs()[2])
    await click(container.querySelector('.evcard-draft-btn'))
    expect(suggestFix).toHaveBeenCalledWith('s1', 'deck.pptx', '1.1.1', 'ppt/slides/slide3.xml#rId4')
  })

  it('moves the picked marker to the clicked thumbnail', async () => {
    await mount()
    await click(thumbs()[1])
    const pressed = thumbs().map((t) => t.getAttribute('aria-pressed'))
    expect(pressed).toEqual(['false', 'true', 'false'])
  })

  it('puts the returned alt text into the editor', async () => {
    await mount()
    await click(container.querySelector('.evcard-draft-btn'))
    expect(container.querySelector('.evcard-rec-input').value).toBe('A nurse reviews a chart.')
  })

  it('shows the server reason when the model could only produce a template', async () => {
    suggestFix.mockResolvedValue({
      suggestion: 'Describe: [what it shows]', is_template: true,
      reason: 'Template only — no vision model is available to look at this image.',
    })
    await mount()
    await click(container.querySelector('.evcard-draft-btn'))
    expect(container.textContent).toContain('no vision model is available')
    expect(container.textContent).not.toContain('no vision model described this image')
  })

  it('sends no locator for an item with no images', async () => {
    await mount({ item: { ...item, evidence: [] } })
    await click(container.querySelector('.evcard-draft-btn'))
    expect(suggestFix).toHaveBeenCalledWith('s1', 'deck.pptx', '1.1.1', undefined)
  })
})
