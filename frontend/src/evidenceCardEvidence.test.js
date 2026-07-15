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
  // A deferred row's images now each get their own editor (ProposalEditors driven by evidence),
  // not a shared picker — the only way to record one description per image.
  it('renders one editable row per deferred image, not just the first', () => {
    const html = markup({ ...base, evidence: ev(19) })
    expect(html.split('evcard-multi-row').length - 1).toBe(19)
  })

  it('gives every deferred image its own description box', () => {
    const html = markup({ ...base, evidence: ev(19) })
    expect((html.match(/<textarea/g) || [])).toHaveLength(19)
  })

  it('offers a per-image draft retry on every deferred image (auto-draft fills them; this recovers)', () => {
    const html = markup({ ...base, evidence: ev(5) })
    expect((html.match(/Draft this image/g) || [])).toHaveLength(5)
  })

  it('no picker survives — the deferred images are edit boxes, not a pick-one strip', () => {
    const html = markup({ ...base, evidence: ev(5) })
    // The old radio-style thumbnail picker (its class + aria-pressed selection) is gone. Note the
    // HowToConfirm platform toggle legitimately uses aria-pressed, so we assert on the picker's own
    // class + the per-image edit rows rather than a blanket aria-pressed check.
    expect(html).not.toContain('evcard-evidence-strip')
    expect((html.match(/evcard-multi-row/g) || [])).toHaveLength(5)
  })

  it('names each image by its locator, so the reviewer knows which one they are describing', () => {
    const evd = [{ locator: 'ppt/slides/slide1.xml#Pic1', thumb: PNG },
                 { locator: 'ppt/slides/slide3.xml#Pic4', thumb: PNG }]
    const html = markup({ ...base, evidence: evd })
    expect(html).toContain('ppt/slides/slide1.xml#Pic1')
    expect(html).toContain('ppt/slides/slide3.xml#Pic4')
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
