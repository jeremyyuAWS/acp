import { describe, it, expect } from 'vitest'
import { leadWithIsolatedImage, imagesOfTextException } from './reviewCard.js'

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

  it('a chart on 1.4.9 gets remediation guidance and NO logo/exempt action', () => {
    const exc = imagesOfTextException('1.4.9', chart)
    expect(exc.action).toBeUndefined()
    expect(exc.note).toMatch(/logotype exemption/i)
    expect(exc.note).toMatch(/data table/i)   // a chart specifically points to a data table
  })

  it('a diagram on 1.4.5 also gets guidance, no exempt action', () => {
    const exc = imagesOfTextException('1.4.5', diagram)
    expect(exc.action).toBeUndefined()
    expect(exc.note).toMatch(/logotype exemption/i)
    expect(exc.note).not.toMatch(/data table/i)   // non-chart guidance omits the data-table line
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
