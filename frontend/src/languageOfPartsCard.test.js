// A Language-of-Parts card must say WHAT is changing.
//
// It used to render: a page thumbnail, the sentence "The AI drafted a fix; a person must
// approve it" (the fallback for any criterion missing from hitlMeta — 3.1.2 was), and
// "Compliance: Fail → Pass after approval". Nothing named the passage, nothing named the
// language, and approving wrote nothing. A reviewer had no idea what they were approving.
import { describe, it, expect } from 'vitest'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import EvidenceCard from './EvidenceCard.jsx'
import { metaFor } from './hitlMeta.js'
import { buildEvidenceCard } from './reviewCard.js'

const PASSAGE = 'La cita es a las tres de la tarde en la clínica de cardiología.'

const item = {
  id: 'i1',
  scan_id: 'scan1',
  file: 'Movate_AccessOps_Healthcare_v6.pdf',
  rule_id: '3.1.2',
  rule_name: 'Language of Parts',
  status: 'pending',
  finding_count: 2,
  proposals: [{
    locator: PASSAGE.slice(0, 60),
    before: PASSAGE,
    proposed_value: 'es',
    rationale: 'detected Spanish (langdetect confidence 0.99) — mark this passage lang="es"',
    source: 'langdetect (deterministic language detection)',
  }],
}

const markup = (it) => renderToStaticMarkup(createElement(EvidenceCard, { item: it, onAct: () => {} }))

describe('Language of Parts — the reviewer can see what changes', () => {
  it('shows the actual passage, not just a page thumbnail', () => {
    expect(markup(item)).toContain(PASSAGE)
  })

  it('shows the markup the value becomes, not a bare ISO code', () => {
    const html = markup(item)
    expect(html).toContain('lang=&quot;es&quot; — Spanish')   // "es" alone means nothing
    expect(html).toContain('writes')
  })

  it('shows why the language was detected, and by what', () => {
    const html = markup(item)
    expect(html).toContain('detected Spanish')
    expect(html).toContain('langdetect')
  })

  it('never claims an AI drafted a fix just because the criterion is unlisted', () => {
    // The old DEFAULT_META printed this on every unlisted criterion, drafted or not.
    expect(metaFor({ rule_id: '3.1.2' }).reason).not.toMatch(/The AI drafted a fix/)
    expect(metaFor({ rule_id: '3.1.2' }).reason).toMatch(/different language/i)
    // and the fallback itself no longer asserts a draft exists
    expect(metaFor({ rule_id: '9.9.9' }).reason).not.toMatch(/drafted/i)
  })
})

describe('Language of Parts — approving it does not certify the file', () => {
  it('does not promise Fail → Pass, because approval writes nothing on its own', () => {
    const card = buildEvidenceCard(item)
    expect(card.certifiesOnApprove).toBe(false)
    expect(card.impact).toEqual({ before: 'Fail', after: 'Fail' })
    expect(markup(item)).not.toContain('after approval')
  })

  it('a contrast finding still certifies on approval — the sign-off IS the resolution', () => {
    const contrast = { ...item, rule_id: '1.4.3', rule_name: 'Contrast (Minimum)', proposals: null }
    const card = buildEvidenceCard(contrast)
    expect(card.certifiesOnApprove).toBe(true)
    expect(card.impact).toEqual({ before: 'Fail', after: 'Pass' })
  })

  it('the button says what approving does — and 3.1.2 has no applier, so it records only', () => {
    expect(markup(item)).toContain('Approve — record sign-off')
    expect(markup(item)).not.toContain('Approve &amp; Apply')
  })

  it('alt text on an Office file DOES get written, so the button says so', () => {
    const alt = { ...item, rule_id: '1.1.1', rule_name: 'Non-text Content', file: 'deck.pptx',
                  proposals: [{ locator: 'ppt/slides/slide1.xml#Picture 1', before: '(no alt text)',
                                proposed_value: 'A clinician at a desk.' }] }
    expect(markup(alt)).toContain('Approve &amp; write into the document')
    // …but a PDF has no applier: do not promise a write we cannot perform
    expect(markup({ ...alt, file: 'handbook.pdf' })).toContain('Approve — record sign-off')
  })
})
