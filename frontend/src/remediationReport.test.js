import { describe, it, expect } from 'vitest'
import { buildRemediationModel, VERIFY_GUIDE } from './reportModel.js'

// The remediation report is the record a reviewer SIGNS. Two things therefore have to be true
// of the model behind it, and neither is cosmetic:
//   1. it never invents a timestamp
//   2. it never claims to be complete when it was truncated
const DOC = 'Patient Education/2024/Clinical-FAQ-39.docx'
const base = (over = {}) => ({
  files: [{ file: DOC, remediated_at: '2026-07-29T18:00:00Z' }],
  diffsByFile: { [DOC]: [{ rule_id: 'SC_1_1_1', before: '(none)', after: 'A clinician.' }] },
  appliedFixes: [],
  scNames: { '1.1.1': 'Non-text Content', '2.4.2': 'Page Titled' },
  ...over,
})

describe('timestamps are recorded, never inferred', () => {
  it('says so plainly when applied_fixes has no row for the change', () => {
    const m = buildRemediationModel(base())
    expect(m.documents[0].items[0].at).toBeNull()
    expect(m.totals.unstamped).toBe(1)
  })

  it('does NOT borrow the document remediated_at for an unstamped change', () => {
    // remediation_diff has no time column at all; the document-level stamp is a different
    // event at a different moment. Substituting it would imply a precision we do not have.
    const m = buildRemediationModel(base())
    expect(m.documents[0].remediatedAt).not.toBeNull()
    expect(m.documents[0].items[0].atIso).toBeNull()
  })

  it('uses the EARLIEST write for a criterion fixed across many images', () => {
    // The API returns newest-first; a criterion spanning 19 images was done when the first
    // write landed, so taking the head of that list would report the wrong moment.
    const m = buildRemediationModel(base({ appliedFixes: [
      { file: DOC, rule_id: 'SC_1_1_1', created_at: '2026-07-29T18:09:00Z' },
      { file: DOC, rule_id: 'SC_1_1_1', created_at: '2026-07-29T18:01:00Z' },
    ] }))
    expect(m.documents[0].items[0].atIso).toBe('2026-07-29T18:01:00Z')
  })

  it('ignores a malformed timestamp rather than rendering "Invalid Date"', () => {
    const m = buildRemediationModel(base({ files: [{ file: DOC, remediated_at: 'not-a-date' }] }))
    expect(m.documents[0].remediatedAt).toBeNull()
  })
})

describe('one checkbox per criterion, not per image', () => {
  it('collapses repeated rule_ids', () => {
    const m = buildRemediationModel(base({ diffsByFile: { [DOC]: [
      { rule_id: 'SC_1_1_1', before: 'a', after: 'b' },
      { rule_id: 'SC_1_1_1', before: 'c', after: 'd' },
      { rule_id: 'SC_2_4_2', before: 'e', after: 'f' },
    ] } }))
    expect(m.documents[0].items.map((i) => i.sc)).toEqual(['1.1.1', '2.4.2'])
  })

  it('accepts both the engine form (SC_1_1_1) and the dotted form', () => {
    const m = buildRemediationModel(base({ diffsByFile: { [DOC]: [{ rule_id: '1.1.1', before: 'a', after: 'b' }] } }))
    expect(m.documents[0].items[0].sc).toBe('1.1.1')
  })
})

describe('which documents appear', () => {
  it('omits a document nothing was done to', () => {
    const m = buildRemediationModel(base({
      files: [{ file: DOC, remediated_at: '2026-07-29T18:00:00Z' }, { file: 'untouched.pptx' }],
    }))
    expect(m.documents.map((d) => d.name)).toEqual(['Clinical-FAQ-39.docx'])
  })

  it('splits name from folder, so a reviewer can find the right one of two same-named files', () => {
    const m = buildRemediationModel(base())
    expect(m.documents[0].name).toBe('Clinical-FAQ-39.docx')
    expect(m.documents[0].dir).toBe('Patient Education/2024')
  })
})

describe('truncation is disclosed', () => {
  it('flags partial when the server row cap was reached', () => {
    const fixes = Array.from({ length: 200 }, () => ({ file: DOC, rule_id: 'SC_1_1_1', created_at: '2026-07-29T18:01:00Z' }))
    expect(buildRemediationModel(base({ appliedFixes: fixes, cappedAt: 200 })).partial).toBe(200)
  })

  it('does not cry partial when the cap was not reached', () => {
    expect(buildRemediationModel(base({ cappedAt: 200 })).partial).toBeNull()
  })
})

describe('how-to-verify covers both platforms, for present formats only', () => {
  it('scopes the guide to formats actually in the report', () => {
    const m = buildRemediationModel(base())
    expect(m.formats).toEqual(['docx'])   // a docx-only report must not explain PowerPoint
  })

  it('every guide ACP can emit has BOTH mac and windows steps', () => {
    for (const [fmt, g] of Object.entries(VERIFY_GUIDE)) {
      expect(g.mac?.length, `${fmt} needs macOS steps`).toBeGreaterThan(0)
      expect(g.win?.length, `${fmt} needs Windows steps`).toBeGreaterThan(0)
      expect(g.app, `${fmt} needs an app name`).toBeTruthy()
    }
  })
})
