import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { act } from 'react-dom/test-utils'

// The whole point of the per-image rows: a draft must describe the image on ITS OWN row. A vision
// model sees one image; drafting the first of nineteen for all of them would caption the wrong
// picture and the reviewer would approve alt text for an image they never saw. Descriptions now
// generate AUTOMATICALLY when the card is in view (auto-draft), fanning out one call per image's
// own locator — so this invariant is exercised by the auto-draft itself, and again by the per-image
// retry button.

const suggestFix = vi.fn()
vi.mock('./api.js', () => ({
  suggestFix: (...a) => suggestFix(...a),
  getFileRemediationDiffs: () => Promise.resolve([]),
  aiProvenance: () => null,
  getFileThumbnail: () => Promise.resolve(null),   // Thumbnail.jsx self-hides without a blob
  getFilePage: () => Promise.resolve(null),
  getFileGeometry: () => Promise.resolve(null),
  getScanAiCalls: () => Promise.resolve([]),
  validateAlt: () => Promise.resolve({}),
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
// jsdom has no IntersectionObserver, so the card counts as in-view immediately and auto-draft fires
// on mount; the sequential draftAll needs a few macrotask turns to complete.
const settle = async (n = 8) => { for (let k = 0; k < n; k++) await act(async () => { await new Promise((r) => setTimeout(r, 0)) }) }
const drafts = () => [...container.querySelectorAll('.evcard-draft-btn')]
const inputs = () => [...container.querySelectorAll('.evcard-rec-input')]
const click = async (el) => { await act(async () => { el.dispatchEvent(new MouseEvent('click', { bubbles: true })) }) }

beforeEach(() => {
  suggestFix.mockReset()
  // Each locator gets a DISTINCT suggestion, so a description bleeding into the wrong image's box
  // would be visible.
  suggestFix.mockImplementation((scan, file, rule, locator) =>
    Promise.resolve({ suggestion: `desc:${locator}`, is_template: false, model: 'llava:7b' }))
})

describe('EvidenceCard — auto-draft targets each image’s own row', () => {
  it('auto-drafts every deferred image from its OWN locator, isolated per row', async () => {
    await mount(); await settle()
    expect(suggestFix).toHaveBeenCalledWith('s1', 'deck.pptx', '1.1.1', 'ppt/slides/slide1.xml#rId2')
    expect(suggestFix).toHaveBeenCalledWith('s1', 'deck.pptx', '1.1.1', 'ppt/slides/slide3.xml#rId4')
    // each box holds ITS image's description, never another's
    expect(inputs().map((t) => t.value)).toEqual([
      'desc:ppt/slides/slide1.xml#rId2', 'desc:ppt/slides/slide2.xml#rId3', 'desc:ppt/slides/slide3.xml#rId4',
    ])
  })

  it('the per-image retry re-drafts that row’s image, not the first', async () => {
    await mount(); await settle()
    suggestFix.mockClear()
    await click(drafts()[2])
    expect(suggestFix).toHaveBeenCalledWith('s1', 'deck.pptx', '1.1.1', 'ppt/slides/slide3.xml#rId4', null)
  })

  it('a per-image retry shows the server reason when the model could only produce a template', async () => {
    suggestFix.mockResolvedValue({
      suggestion: 'Describe: [what it shows]', is_template: true,
      reason: 'Template only — no vision model is available to look at this image.',
    })
    await mount(); await settle()          // auto-draftAll leaves the boxes empty (all templates)
    await click(drafts()[0])               // reviewer retries one image → the per-image reason surfaces
    expect(container.textContent).toContain('no vision model is available')
    expect(container.textContent).not.toContain('no vision model described this image')
  })

  it('auto-drafts a single-value item with no per-image target (no locator)', async () => {
    // No evidence and no proposals → the single-value editor; its auto-draft has no per-image target.
    await mount({ item: { ...item, evidence: [], finding_count: 1 } }); await settle()
    expect(suggestFix).toHaveBeenCalledWith('s1', 'deck.pptx', '1.1.1', undefined)
  })
})
