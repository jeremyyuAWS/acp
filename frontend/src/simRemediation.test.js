// The SIM fixtures that let the demo show before→after evidence. They must reproduce the
// shapes the live backend persists, and must never let the demo claim a fix it can't show.
import { describe, it, expect } from 'vitest'
import { simProposalsFor, simRemediationDiffs, SIM_THUMB } from './sim.js'
import { isSafeThumb } from './ProposalThumb.jsx'
import { comparisonFor } from './reviewCard.js'

describe('simProposalsFor — drafts awaiting approval', () => {
  it('drafts a value only for the criteria a model can write one for', () => {
    expect(simProposalsFor('1.1.1')[0].proposed_value).toMatch(/Bar chart/)
    expect(simProposalsFor('2.4.4')[0].proposed_value).toMatch(/intake form/)
  })

  it('offers no draft for a judgement criterion, rather than inventing one', () => {
    for (const sc of ['1.4.3', '1.4.6', '1.2.2', '']) expect(simProposalsFor(sc)).toBeNull()
  })

  it('the alt-text proposal carries an image the reviewer can actually judge', () => {
    expect(isSafeThumb(simProposalsFor('1.1.1')[0].thumb)).toBe(true)
    expect(isSafeThumb(SIM_THUMB)).toBe(true)
  })

  it('names itself simulated, so a demo screenshot never reads as a real model run', () => {
    for (const sc of ['1.1.1', '2.4.4']) expect(simProposalsFor(sc)[0].source).toMatch(/simulated/)
  })

  it('hands callers a copy — a reviewer editing one card cannot mutate the fixture', () => {
    simProposalsFor('1.1.1')[0].proposed_value = 'clobbered'
    expect(simProposalsFor('1.1.1')[0].proposed_value).toMatch(/Bar chart/)
  })
})

describe('simRemediationDiffs — fixes already written into the document', () => {
  const FILES = [
    { file: 'handbook.pdf', issues: [{ wcag: 'SC_1_3_1' }, { wcag: 'SC_1_1_1' }, { wcag: 'SC_1_3_1' }] },
    { file: 'contrast.html', issues: [{ wcag: 'SC_1_4_3' }] },
    { file: 'no-issues.docx', issues: [] },
  ]

  it('emits a row only for deterministically-fixed criteria', () => {
    const rows = simRemediationDiffs(FILES)
    expect(rows.map((r) => r.rule_id)).toEqual(['1.3.1'])
    expect(rows[0]).toMatchObject({ file: 'handbook.pdf', before: expect.stringContaining('<td>') })
  })

  it('never emits a diff for a judgement criterion or an alt-text draft', () => {
    const scs = simRemediationDiffs(FILES).map((r) => r.rule_id)
    expect(scs).not.toContain('1.4.3')   // contrast — human sign-off
    expect(scs).not.toContain('1.1.1')   // alt text — a draft, not an applied fix
  })

  it('deduplicates repeated findings of the same criterion in one file', () => {
    expect(simRemediationDiffs(FILES).filter((r) => r.file === 'handbook.pdf').length).toBe(1)
  })

  it('feeds comparisonFor as an APPLIED fix, matched on file and criterion', () => {
    const rows = simRemediationDiffs(FILES)
    expect(comparisonFor({ ruleId: '1.3.1', file: 'handbook.pdf' }, rows).applied).toBe(true)
    // and does not leak onto another document's card
    expect(comparisonFor({ ruleId: '1.3.1', file: 'contrast.html' }, rows)).toBeNull()
  })

  it('a judgement finding gets no comparison at all — the card must say so', () => {
    expect(comparisonFor({ ruleId: '1.4.3', file: 'contrast.html' }, simRemediationDiffs(FILES))).toBeNull()
  })
})
