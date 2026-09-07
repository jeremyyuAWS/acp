import { describe, it, expect } from 'vitest'
import { DESCRIBED_NOT_REPLACED, leadWithIsolatedImage, imagesOfTextException } from './reviewCard.js'

// Problem 1 — for xlsx the page render is the WHOLE sheet, so the card must lead with the isolated
// embedded image (its own bytes), not the sheet screenshot. leadWithIsolatedImage gates on format +
// thumb kind; the component still checks the image bytes are present.
describe('leadWithIsolatedImage — xlsx leads with the embedded image, not the sheet', () => {
  it('is true for an xlsx image finding (no page-kind thumb)', () => {
    expect(leadWithIsolatedImage({ fmt: 'XLSX', thumbKind: null })).toBe(true)
    expect(leadWithIsolatedImage({ fmt: 'XLSX', thumbKind: 'decorative' })).toBe(true)
  })
  it('is false for an xlsx reading-order (whole-page) thumb — that IS a page render', () => {
    expect(leadWithIsolatedImage({ fmt: 'XLSX', thumbKind: 'reading-order' })).toBe(false)
  })
  it('leaves pptx/docx/pdf on the page-render hero (scoped to xlsx)', () => {
    expect(leadWithIsolatedImage({ fmt: 'PPTX', thumbKind: 'decorative' })).toBe(false)
    expect(leadWithIsolatedImage({ fmt: 'DOCX', thumbKind: null })).toBe(false)
    expect(leadWithIsolatedImage({ fmt: 'PDF', thumbKind: null })).toBe(false)
  })
  it('never throws on a missing card', () => {
    expect(leadWithIsolatedImage(null)).toBe(false)
    expect(leadWithIsolatedImage(undefined)).toBe(false)
  })
})

// Problem 2 — the images-of-text exemption ("essential logo/brand") only makes sense for a logo or an
// unidentified image. A recognised DATA image (chart/diagram/…) must NOT get the logo question.
describe('imagesOfTextException — routed by detected image kind', () => {
  const chart = { icon: '📊', label: 'Chart' }
  const diagram = { icon: '🔀', label: 'Diagram' }
  const logo = { icon: '🔖', label: 'Logo' }

  it('is null for criteria that are not images-of-text', () => {
    expect(imagesOfTextException('1.1.1', chart)).toBeNull()
    expect(imagesOfTextException('2.4.4', null)).toBeNull()
  })

  // These two asserted `exc.action` was UNDEFINED until ADR 0055. That was right about the logo
  // exemption and wrong as a whole: it left a data image with guidance and nothing to click, so a
  // reviewer who could not replace the picture — a chart, where replacement destroys the data —
  // had no way to resolve the finding at all. The assertion is now the sharper one it should
  // always have been: still no ESSENTIAL-LOGO action, and a describe action instead.
  it('a chart on 1.4.9 gets remediation guidance and a describe action, never the logo exemption', () => {
    const exc = imagesOfTextException('1.4.9', chart)
    expect(exc.note).toMatch(/logotype exemption/i)
    expect(exc.note).toMatch(/data table/i)   // a chart specifically points to a data table
    expect(exc.action.resolution).toBe(DESCRIBED_NOT_REPLACED)
    expect(exc.action.resolution).not.toBe('essential_exception')
    expect(exc.prompt).toBeUndefined()        // no "is this a logo?" question on a data image
  })

  it('a diagram on 1.4.5 also gets guidance plus the describe action', () => {
    const exc = imagesOfTextException('1.4.5', diagram)
    expect(exc.note).toMatch(/logotype exemption/i)
    expect(exc.note).not.toMatch(/data table/i)   // non-chart guidance omits the data-table line
    expect(exc.action.resolution).toBe(DESCRIBED_NOT_REPLACED)
  })

  it('every content image kind gets a way out, not just charts', () => {
    // The dead end was the whole branch, so the fix has to be the whole branch. A screenshot of a
    // slide of text is as unreplaceable as a chart when the styling carries meaning.
    for (const label of ['Chart', 'Diagram', 'Screenshot', 'Table', 'Map', 'Photo', 'Illustration']) {
      const exc = imagesOfTextException('1.4.5', { label })
      expect(exc.action, `${label} has no action`).toBeTruthy()
      expect(exc.action.resolution, `${label} resolution`).toBe(DESCRIBED_NOT_REPLACED)
    }
  })

  it('the describe action declares that it needs text, with a reason a reviewer can read', () => {
    // needsText is not decoration: api/routes/hitl.py 422s a described decision carrying no
    // description, because keeping an image of text without describing it resolves nothing. The
    // card disables the button on this flag, so losing it would turn a guarded control into a
    // failed request after the click.
    const exc = imagesOfTextException('1.4.5', chart)
    expect(exc.action.needsText).toBe(true)
    expect(exc.action.needsTextHint).toMatch(/screen reader/i)
    expect(exc.action.title).toMatch(/1\.1\.1/)          // says where the description goes
    expect(exc.action.title).toMatch(/judgement/i)        // and that 1.4.5 is resolved, not fixed
  })

  it('a logo keeps the essential-logotype exemption', () => {
    const exc = imagesOfTextException('1.4.9', logo)
    expect(exc.action).toBeTruthy()
    expect(exc.action.resolution).toBe('essential_exception')
    expect(exc.prompt).toMatch(/logo or brand mark/i)
  })

  it('an UNIDENTIFIED image keeps the exemption — a short baked-in block is often a brand mark', () => {
    const exc = imagesOfTextException('1.4.9', null)
    expect(exc.action).toBeTruthy()
    expect(exc.action.resolution).toBe('essential_exception')
  })
})
