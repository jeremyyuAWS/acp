import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

// The card for an APPROVED row whose write was refused credit must say so, in the ladder and in a
// sentence. Before this, the write was discarded, apply.unverified was logged, and the reviewer —
// who had just approved the value — saw nothing at all.

vi.mock('./api.js', () => ({
  suggestFix: () => Promise.resolve({ suggestion: '', is_template: false }),
  getFileRemediationDiffs: () => Promise.resolve([]),
  aiProvenance: () => null,
  getFileThumbnail: () => Promise.resolve(null),
  getFilePage: () => Promise.resolve(null),
  getFileGeometry: () => Promise.resolve(null),
  getSourceLink: () => Promise.resolve({ url: null }),
  getScanAiCalls: () => Promise.resolve([]),
  validateAlt: () => Promise.resolve({}),
}))

afterEach(unmountAll)

const { default: EvidenceCard } = await import('./EvidenceCard.jsx')

// 2.4.6 (a value-fix with a proposal, no auto-draft) keeps the mount deterministic — the outcome
// mechanics are criterion-agnostic, so this exercises them without the vision path.
const base = {
  id: 7, scan_id: 's1', file: 'report.docx', rule_id: '2.4.6', rule_name: 'Headings and Labels',
  finding_count: 1, reviewed_at: '2026-09-07T03:00:00+00:00',
  proposals: [{ locator: 'w:body#h1', before: 'Section 1', proposed_value: 'Q3 revenue by region',
                rationale: 'grounded in the section’s opening sentence' }],
}
const refused = {
  ...base, status: 'approved', applied: 0, approved_value: 'Q3 revenue by region',
  apply_outcome: { outcome: 'still_failing', criteria: ['2.4.6'], reason: '', ts: '2026-09-07T03:01:00+00:00' },
}
const pending = { ...base, status: 'pending' }

let container
const mount = async (item) => {
  const { container: c, root } = createTestRoot()
  container = c
  await act(async () => { root.render(createElement(EvidenceCard, { item, onAct: () => {} })) })
}

describe('EvidenceCard — a refused write is visible on the card', () => {
  it('renders the outcome sentence with the criterion, as a status message', async () => {
    await mount(refused)
    const note = container.querySelector('.evcard-apply-outcome')
    expect(note).not.toBeNull()
    expect(note.getAttribute('role')).toBe('status')
    expect(note.textContent).toContain('Written, but 2.4.6 still fails on re-scan.')
    expect(note.textContent).toContain('nothing was credited')
  })

  it('the ladder shows the write on a working copy and the re-scan as failed — no green "Written to document"', async () => {
    await mount(refused)
    const text = container.querySelector('.evcard-ladder').textContent
    expect(text).toContain('✓ Written to a working copy')
    expect(text).toContain('✗ Re-scan verified')
    expect(text).not.toContain('Written to document')
  })

  it('a pending row renders no outcome — nothing has been written yet', async () => {
    await mount(pending)
    expect(container.querySelector('.evcard-apply-outcome')).toBeNull()
    const text = container.querySelector('.evcard-ladder').textContent
    expect(text).not.toContain('✗')
    expect(text).not.toContain('working copy')
    expect(text).toContain('● Human review')
  })
})
