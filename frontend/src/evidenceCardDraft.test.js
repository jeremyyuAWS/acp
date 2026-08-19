import { describe, it, expect } from 'vitest'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import EvidenceCard from './EvidenceCard.jsx'

// The single-box draft is now AUTOMATIC (Review queue): a value-fix that reaches the inbox with no
// AI value drafts its preview on sight, so the old "✨ Draft with AI" button is gone. These pins are
// on the STATIC render (renderToStaticMarkup runs no effects, so the auto-draft never fires here) —
// the auto-draft firing itself is covered in evidenceCardAutoDraft.test.jsx.

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

describe('EvidenceCard — auto-draft, no manual button', () => {
  it('shows the author-it-yourself box with NO "Draft with AI" button when nothing is drafted', () => {
    const html = markup({ ...base })
    expect(html).not.toContain('Draft with AI')          // the manual button is gone
    expect(html).toContain('No AI draft')                // label still frames the empty state
    expect(html).toContain('Type the value a screen reader should announce') // placeholder present
  })

  it('renders the drafted value + reasoning inline when the server already proposed one', () => {
    const html = markup({
      ...base,
      proposals: [{ proposed_value: 'A nurse reviews a chart with a patient.', rationale: 'vision model' }],
    })
    expect(html).not.toContain('Draft with AI')
    // A row carrying a proposal renders the per-instance editor, which shows the drafted value
    // and the reasoning behind it — not a bare textarea with no evidence of what is changing.
    expect(html).toContain('A nurse reviews a chart with a patient.')
    expect(html).toContain('vision model')
    expect(html).toContain('becomes')
  })

  it('shows no draft button on a judgement criterion (nothing to type)', () => {
    // 1.4.3 contrast is not a VALUE_FIX rule and carries no proposal → no editor, no button.
    const html = markup({ ...base, rule_id: '1.4.3', rule_name: 'Contrast (Minimum)' })
    expect(html).not.toContain('Draft with AI')
  })
})
