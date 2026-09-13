import { describe, it, expect, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'
import CropReviewContext from './CropReviewContext.jsx'
import { imagesOfTextException } from './reviewCard.js'
const crop = { crop: {t:19861,l:0,r:0,b:0}, selectable_description_supported: true, requires_visual_confirmation: true, transcription_source: 'visible-crop-ocr-v1', visible_image_sha256: 'a'.repeat(64), source_image_sha256: 'b'.repeat(64) }
const PNG = 'data:image/png;base64,iVBORw0KGgo='
afterEach(unmountAll)
async function mount(props) { const {container, root} = createTestRoot(); await act(async()=>root.render(createElement(CropReviewContext,props))); return container }
describe('visible crop review', () => {
  it('shows saved crop thumbnail with its actual fidelity and preservation outcomes', async () => {
    const c = await mount({ evidence: crop, thumb: PNG, locator: 'image 2', draft: 'Visible controller instructions', sourceUrl: 'https://tenant.sharepoint.com/manual.docx' })
    expect(c.querySelector('img').src).toBe(PNG)
    expect(c.querySelector('pre').textContent).toBe('Visible controller instructions')
    expect(c.querySelector('a').href).toBe('https://tenant.sharepoint.com/manual.docx')
    expect(c.textContent).toContain('up to 96px')
    expect(c.textContent).toContain('added beside it as selectable text and as alt text')
    expect(c.textContent).toContain('does not verify that the image-of-text finding is cleared')
  })
  it('never loads a remote image or substitutes full-document pixels', async () => {
    const c = await mount({ evidence: crop, thumb: 'https://example.com/private.png' })
    expect(c.querySelector('img')).toBeNull()
    expect(c.textContent).toContain('preview unavailable')
  })
  it('renders transcript as plain text and refuses an unsafe source link', async () => {
    const c = await mount({ evidence: crop, thumb: PNG, draft: '<img src="remote">', sourceUrl: 'javascript:alert(1)' })
    expect(c.querySelector('pre').textContent).toBe('<img src="remote">')
    expect(c.querySelectorAll('img')).toHaveLength(1)
    expect(c.querySelector('a')).toBeNull()
  })
  it('does not retroactively disclose the new writing choice for older proposals', async () => {
    const c = await mount({ evidence: { ...crop, selectable_description_supported: undefined }, thumb: PNG })
    expect(c.textContent).toBe('')
    expect(imagesOfTextException('1.4.5', null, { ...crop, selectable_description_supported: undefined }).action.resolution).not.toBe('described_not_replaced')
  })
  it('routes an unidentified cropped diagram by disclosed metadata without a logo assumption', () => {
    const choice = imagesOfTextException('1.4.5', null, crop)
    expect(choice.action.resolution).toBe('described_not_replaced')
    expect(choice.action.needsText).toBe(true)
    expect(choice.action.title).toContain('not verified clear')
    expect(choice.prompt).toBeUndefined()
    expect(imagesOfTextException('1.1.1', null, crop)).toBeNull()
  })
})
