import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

// Progressive disclosure (Review queue): the card must LEAD with the decision (intent + the
// editor/recommendation) and COLLAPSE the audit jargon — the trust-state enums, provenance, and the
// "why human review" reason — under a "Details ▾" disclosure. This pins the structure so a later
// edit can't quietly pull the machinery back into the primary flow.

vi.mock('./api.js', () => ({
  suggestFix: () => Promise.resolve({ suggestion: '', is_template: false }),
  getFileRemediationDiffs: () => Promise.resolve([]),
  aiProvenance: () => null,
  getFileThumbnail: () => Promise.resolve(null),
  getFilePage: () => Promise.resolve(null),
  getFileGeometry: () => Promise.resolve(null),
  getScanAiCalls: () => Promise.resolve([]),
  validateAlt: () => Promise.resolve({}),
}))

// Unmount every root this file mounts — see testRoots.js.
afterEach(unmountAll)

const { default: EvidenceCard } = await import('./EvidenceCard.jsx')

// 2.4.6 (heading) is an irreducibly-human criterion → whyReview renders; with a proposal the trust
// pills render and no auto-draft fires.
const item = {
  id: 1, scan_id: 's1', file: 'report.docx', rule_id: '2.4.6', rule_name: 'Headings and Labels',
  status: 'pending', finding_count: 1,
  proposals: [{ locator: 'w:body#h1', before: 'Section 1', proposed_value: 'Q3 revenue by region',
                rationale: 'grounded in the section’s opening sentence' }],
}

let container
const mount = async (it = item) => {
  const { container: c, root } = createTestRoot()
  container = c
  await act(async () => { root.render(createElement(EvidenceCard, { item: it, onAct: () => {} })) })
}

describe('EvidenceCard — Details ▾ progressive disclosure', () => {
  it('collapses trust + why-human-review under a Details disclosure', async () => {
    await mount()
    const details = container.querySelector('details.evcard-details')
    expect(details).not.toBeNull()
    // the audit jargon lives INSIDE the disclosure
    expect(details.querySelector('.evcard-trust')).not.toBeNull()
    expect(details.querySelector('.evcard-whyreview')).not.toBeNull()
    expect(details.textContent).toContain('Why human review?')
  })

  it('keeps the decision content (intent) OUT of the disclosure — it leads the card', async () => {
    await mount()
    const intent = container.querySelector('.evcard-intent')
    expect(intent).not.toBeNull()
    expect(intent.closest('details.evcard-details')).toBeNull()   // intent is not buried
  })

  it('is collapsed by default (no open attribute)', async () => {
    await mount()
    expect(container.querySelector('details.evcard-details').open).toBe(false)
  })
})
