import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { isSafeThumb } from './ProposalThumb.jsx'
import { firstThumb, firstProposed, firstRationale, firstSource, buildEvidenceCard } from './reviewCard.js'

const here = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(here, f), 'utf8')
const PNG = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUg=='

describe('isSafeThumb — an untrusted string must never reach an <img src>', () => {
  it('accepts the data URLs _thumb_b64 produces', () => {
    expect(isSafeThumb(PNG)).toBe(true)
    expect(isSafeThumb('data:image/jpeg;base64,/9j/4AAQ')).toBe(true)
    expect(isSafeThumb('data:image/webp;base64,UklGRg==')).toBe(true)
  })

  it('rejects anything that is not an image data URL', () => {
    // proposals arrive as JSON from the database; a bad value must render nothing, not execute.
    expect(isSafeThumb('javascript:alert(1)')).toBe(false)
    expect(isSafeThumb('data:text/html;base64,PHNjcmlwdD4=')).toBe(false)
    expect(isSafeThumb('https://evil.example/x.png')).toBe(false)
    expect(isSafeThumb('data:image/png;base64,abc"onerror=alert(1)')).toBe(false)
    expect(isSafeThumb('')).toBe(false)
    expect(isSafeThumb(null)).toBe(false)
    expect(isSafeThumb(42)).toBe(false)
  })
})

describe('proposal accessors', () => {
  const item = { rule_id: '1.1.1', file: 'deck.pptx', proposals: [
    { locator: 'ppt/slides/slide3.xml#rId4', before: '(no alt text)',
      proposed_value: 'A clinician reviewing intake forms with a parent.',
      rationale: 'No text found in the image; described from visual content.',
      source: 'AI vision model (llava)', thumb: PNG },
  ] }

  it('reads the model draft, the image, the rationale and the model', () => {
    expect(firstProposed(item)).toMatch(/clinician/)
    expect(firstThumb(item)).toBe(PNG)
    expect(firstRationale(item)).toMatch(/No text found/)
    expect(firstSource(item)).toBe('AI vision model (llava)')
  })

  it('returns null when there is no proposal, rather than inventing one', () => {
    for (const empty of [{}, { proposals: [] }, { proposals: null }, null]) {
      expect(firstThumb(empty)).toBeNull()
      expect(firstProposed(empty)).toBeNull()
    }
  })

  it('the evidence card carries the image and the reasoning', () => {
    const card = buildEvidenceCard(item)
    expect(card.thumb).toBe(PNG)
    expect(card.rationale).toMatch(/No text found/)
    expect(card.proposalSource).toBe('AI vision model (llava)')
  })
})

describe('the review screens render the proposal, not a template', () => {
  it('Remediate no longer falls through to the canned string when a proposal exists', () => {
    // `after: it.approved_value || template` always hit the template: nothing server-side ever
    // writes approved_value, so every image in every document showed the same sentence.
    const src = read('Remediate.jsx')
    expect(src).toMatch(/after: firstProposed\(it\) \|\| it\.approved_value \|\| ba\.after/)
    expect(src).toMatch(/thumb: firstThumb\(it\)/)
  })

  it('Remediate labels a template as a next step, never as an AI suggestion', () => {
    expect(read('Remediate.jsx')).toMatch(/hasProposal \? 'AI suggested value' : 'Next step'/)
  })

  it('EvidenceCard prefers the offending image over the PDF-only page render', () => {
    const src = read('EvidenceCard.jsx')
    expect(src).toMatch(/card\.thumb\s*\n?\s*\?\s*<ProposalThumb/)
    expect(src).toMatch(/: \(card\.scanId && card\.file && <Thumbnail/)
  })

  it('both screens draw the thumb from the same helper', () => {
    expect(read('Remediate.jsx')).toMatch(/from '\.\/reviewCard\.js'/)
    expect(read('EvidenceCard.jsx')).toMatch(/from '\.\/reviewCard\.js'/)
  })
})
