import { describe, it, expect } from 'vitest'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import EvidenceCard from './EvidenceCard.jsx'
import { buildEvidenceCard, evidenceOf } from './reviewCard.js'

// A 1.1.1 row asks a human to describe images. It used to show them none: the thumbnail was
// captured only on the vision path, so exactly when the model could not help — and a person
// had to write the alt text — the card rendered no picture at all.
//
// A row carries N images (19 in the deck that motivated this), so the card shows a STRIP.
// One thumbnail beside "19 findings" would tell the reviewer they are describing that image.

const PNG = 'data:image/png;base64,iVBORw0KGgo='
const base = {
  id: 1, scan_id: 'scan1', file: 'deck.pptx', rule_id: '1.1.1',
  rule_name: 'Non-text Content', status: 'pending', finding_count: 19,
}
const ev = (n) => Array.from({ length: n }, (_, i) => ({ locator: `ppt/slides/slide${i}.xml#rId${i}`, thumb: PNG }))
const markup = (item) => renderToStaticMarkup(createElement(EvidenceCard, { item, onAct: () => {} }))

describe('EvidenceCard — the images awaiting a description', () => {
  it('renders one thumbnail per deferred image, not just the first', () => {
    const html = markup({ ...base, evidence: ev(19) })
    expect(html.split(`src="${PNG}"`).length - 1).toBe(19)
  })

  it('says how many images need describing when there is more than one', () => {
    expect(markup({ ...base, evidence: ev(19) })).toContain('19 images need a description')
  })

  it('uses the singular when a single image is deferred', () => {
    const html = markup({ ...base, evidence: ev(1), finding_count: 1 })
    expect(html).toContain('The image needing a description')
    expect(html).not.toContain('images need a description')
  })

  it('renders no strip at all when the row carries no evidence', () => {
    expect(markup({ ...base })).not.toContain('evcard-evidence-strip')
  })

  it('marks exactly one thumbnail as picked — the one Draft with AI will describe', () => {
    const html = markup({ ...base, evidence: ev(5) })
    expect(html.split('aria-pressed="true"').length - 1).toBe(1)
  })

  it('gives every thumbnail an alt naming which image it is', () => {
    const html = markup({ ...base, evidence: ev(3) })
    expect(html).toContain('Image 1 of 3 in deck.pptx')
    expect(html).toContain('Image 3 of 3 in deck.pptx')
  })

  it('drops a thumbnail whose data URL is not a safe image', () => {
    const html = markup({ ...base, evidence: [{ locator: 'a#1', thumb: 'javascript:alert(1)' }] })
    expect(html).not.toContain('javascript:alert(1)')
  })
})

describe('reviewCard — evidence is not a proposal', () => {
  it('never lets evidence masquerade as an AI proposal', () => {
    const card = buildEvidenceCard({ ...base, evidence: ev(3) })
    expect(card.evidence).toHaveLength(3)
    expect(card.proposal).toBeNull()        // no value to approve → confidence stays honest
    expect(card.recommendation).toBeNull()
  })

  it('tolerates a missing or malformed evidence column', () => {
    expect(evidenceOf({})).toEqual([])
    expect(evidenceOf({ evidence: null })).toEqual([])
    expect(evidenceOf({ evidence: 'not-a-list' })).toEqual([])
  })
})
