import { describe, it, expect } from 'vitest'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import EvidenceCard from './EvidenceCard.jsx'

// "Draft with AI" exists for exactly one situation: an item that reached the inbox with NO
// AI value attached — e.g. an image whose alt text the vision model could not produce, which
// otherwise reads "a person must write a meaningful description" with no way to ask for help.
// When a proposal IS attached the box is already filled, and offering a re-draft would
// silently overwrite the value whose rationale is shown beneath it.

const base = {
  id: 1,
  scan_id: 'scan1',
  file: 'handbook.pdf',
  rule_id: '1.1.1',            // a VALUE_FIX criterion → editable
  rule_name: 'Non-text Content',
  status: 'pending',
  finding_count: 3,
}

const markup = (item) => renderToStaticMarkup(createElement(EvidenceCard, { item, onAct: () => {} }))

describe('EvidenceCard — on-demand AI draft', () => {
  it('offers "Draft with AI" when no proposal or approved value exists', () => {
    const html = markup({ ...base })
    expect(html).toContain('Draft with AI')
    expect(html).toContain('No AI draft')
  })

  it('does NOT offer a draft when the server already proposed a value', () => {
    const html = markup({
      ...base,
      proposals: [{ proposed_value: 'A nurse reviews a chart with a patient.', rationale: 'vision model' }],
    })
    expect(html).not.toContain('Draft with AI')
    // A row carrying a proposal renders the per-instance editor, which shows the drafted value
    // and the reasoning behind it — not a bare textarea labelled "AI recommendation" with no
    // evidence of what is changing.
    expect(html).toContain('A nurse reviews a chart with a patient.')
    expect(html).toContain('vision model')
    expect(html).toContain('becomes')
  })

  it('does NOT offer a draft when a value was previously approved', () => {
    const html = markup({ ...base, approved_value: 'Chart of Q3 revenue by region.' })
    expect(html).not.toContain('Draft with AI')
  })

  it('does not offer a draft without the ids /ai/suggest needs', () => {
    // suggestFix(scan_id, file, rule_id) — without all three the request cannot be formed,
    // so the button must not appear rather than fail on click.
    expect(markup({ ...base, scan_id: null })).not.toContain('Draft with AI')
    expect(markup({ ...base, file: null })).not.toContain('Draft with AI')
  })

  it('does not offer a draft on a judgement criterion (nothing to type)', () => {
    // 1.4.3 contrast is not a VALUE_FIX rule and carries no proposal → no editor, no button.
    const html = markup({ ...base, rule_id: '1.4.3', rule_name: 'Contrast (Minimum)' })
    expect(html).not.toContain('Draft with AI')
  })
})
