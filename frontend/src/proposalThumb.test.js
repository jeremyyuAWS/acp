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
  it('Remediate never falls back to a canned "after" string', () => {
    // `after: it.approved_value || template` always hit the template: nothing server-side ever
    // writes approved_value, so every image in every document showed the same sentence. The
    // fallback is gone — a missing draft must read as missing, not as a fix already applied.
    const src = read('Remediate.jsx')
    expect(src).toMatch(/after: firstProposed\(it\) \|\| it\.approved_value \|\| null/)
    expect(src).not.toMatch(/after: firstProposed\(it\)[^\n]*ba\.after/)
    expect(src).toMatch(/thumb: firstThumb\(it\)/)
  })

  it('Remediate labels a template as a next step, never as an AI suggestion', () => {
    expect(read('Remediate.jsx')).toMatch(/suggested && hasProposal \? 'AI suggested value' : 'Next step'/)
  })

  it('no canned "a fix was applied" string survives in either queue builder', () => {
    // Both the DB-backed queue and the SIM queue used to hand the card a constant sentence
    // claiming alt text had been added. Neither ITEM_BA nor its fallback carries an `after`.
    const src = read('Remediate.jsx')
      .replace(/\/\*[\s\S]*?\*\//g, '')                              // block + JSX comments
      .split('\n').filter((l) => !l.trim().startsWith('//')).join('\n')
    expect(src).not.toMatch(/AI-generated alt text added/)
    expect(src).not.toMatch(/'AI fix applied — review before certifying'/)
    expect(src).not.toMatch(/after: \(\) =>/)
  })

  it('Remediate renders the unified EvidenceCard, which sources its own comparison so late diffs still show', () => {
    // Canonical vision #1: the Human-review list now renders the SAME EvidenceCard as the AI Work
    // Inbox — fed the raw hitl row (q._raw). EvidenceCard fetches its own remediation diffs
    // (getFileRemediationDiffs) in an effect and derives the before/after at render, so a
    // late-arriving diff still shows without baking a stale value into the mapped item.
    const src = read('Remediate.jsx')
    expect(src).toMatch(/<EvidenceCard[^>]*item=\{q\._raw \|\| q\}/)
    expect(src).toMatch(/proposals: it\.proposals/)   // dbItemToUi still carries proposals through
    expect(read('EvidenceCard.jsx')).toMatch(/getFileRemediationDiffs/)
  })

  it('EvidenceCard shows the large page hero AND the object thumb (ADR 0018 visual-first)', () => {
    const src = read('EvidenceCard.jsx')
    // The finding's page rendered large is the HERO (Principle 2) — no longer a mere fallback:
    // rendered whenever scanId+file are present (self-hides if the backend can't rasterize).
    expect(src).toMatch(/evcard-hero[\s\S]{0,200}<Thumbnail scanId=\{card\.scanId\} file=\{card\.file\} page=\{card\.page \|\| 1\} maxHeight=\{360\}/)
    // The offending image (proposals[0].thumb) still renders as the object beside the text.
    expect(src).toMatch(/\{card\.thumb && \([\s\S]{0,80}<ProposalThumb/)
  })

  it('both screens draw the thumb from the same helper', () => {
    expect(read('Remediate.jsx')).toMatch(/from '\.\/reviewCard\.js'/)
    expect(read('EvidenceCard.jsx')).toMatch(/from '\.\/reviewCard\.js'/)
  })
})
