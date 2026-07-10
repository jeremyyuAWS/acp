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

  it('a file has SEVERAL images, each with its own locator, picture and draft', () => {
    // One Approve must never stand in for images the reviewer was not shown, so the demo has
    // to exercise the multi-image path rather than the comfortable one-image case.
    const ps = simProposalsFor('1.1.1')
    expect(ps.length).toBeGreaterThan(1)
    expect(new Set(ps.map((p) => p.locator)).size).toBe(ps.length)      // distinct targets
    expect(new Set(ps.map((p) => p.thumb)).size).toBe(ps.length)        // distinct pictures
    expect(new Set(ps.map((p) => p.proposed_value)).size).toBe(ps.length)
    ps.forEach((p) => expect(isSafeThumb(p.thumb)).toBe(true))
  })

  it('every proposal carries a locator, or the server could not write it anywhere', () => {
    for (const sc of ['1.1.1', '2.4.4']) {
      simProposalsFor(sc).forEach((p) => expect(p.locator).toMatch(/#/))
    }
  })

  it('the locator names a part the document could actually have', () => {
    // A "ppt/slides/…" locator on an xlsx card is exactly the detail a reviewer notices.
    expect(simProposalsFor('1.1.1', 'deck.pptx')[0].locator).toMatch(/^ppt\/slides\/.*#Picture 1$/)
    expect(simProposalsFor('1.1.1', 'sheet.xlsx')[0].locator).toMatch(/^xl\/drawings\/.*#Picture 1$/)
    expect(simProposalsFor('1.1.1', 'report.docx')[0].locator).toMatch(/^word\/document\.xml#/)
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
