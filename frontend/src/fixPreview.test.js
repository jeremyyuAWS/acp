import { describe, it, expect } from 'vitest'
import {
  FIX_MODES, scOfFinding, criterionOf, fixModeOf, proposedValue, appliedStateOf,
  destinationOf, fixPreviewModel,
} from './fixPreview.js'
import { CAPABILITY_FALLBACK } from './capability.js'

// R4's decision layer. The assertions that matter are the honesty ones: the mode is derived from
// real finding state (and says what derived it), a value that does not exist is reported as absent,
// and the destination sentence tracks the REAL drive-mirror setting — including the unread case,
// which must not be answered with the reassuring default.

const F = (over) => ({ id: 1, file: 'plan.docx', type: 'docx', ...over })

describe('scOfFinding', () => {
  it('reads the criterion from any of the field spellings, including a bare sc', () => {
    expect(scOfFinding(F({ rule_id: 'SC_1_1_1' }))).toBe('1.1.1')
    expect(scOfFinding(F({ wcag: '1.4.3' }))).toBe('1.4.3')
    expect(scOfFinding(F({ sc: 'WCAG_2_4_2' }))).toBe('2.4.2')
    expect(scOfFinding(F({}))).toBe('')
  })
})

describe('criterionOf', () => {
  it('carries the catalog name and the plain-language requirement', () => {
    const c = criterionOf('1.1.1')
    expect(c.name).toBe('Non-text Content')
    expect(c.requirement).toMatch(/text alternative/i)
  })
  it('returns nulls for an unlisted criterion rather than a guess', () => {
    expect(criterionOf('9.9.9')).toEqual({ sc: '9.9.9', name: null, requirement: null })
    expect(criterionOf('')).toEqual({ sc: null, name: null, requirement: null })
  })
})

describe('fixModeOf', () => {
  it('a deterministic fix ACP already wrote is Automatic', () => {
    const m = fixModeOf(F({ rule_id: 'SC_1_3_1', autoApplied: true }))
    expect(m.key).toBe('automatic')
    expect(m.label).toBe(FIX_MODES.automatic.label)
    expect(m.basis).toMatch(/deterministically/)
  })

  it('a finding carrying a drafted value is an AI draft to review', () => {
    const m = fixModeOf(F({ rule_id: 'SC_1_1_1', after: 'A bar chart of Q3 revenue by region' }))
    expect(m.key).toBe('ai-draft')
    expect(m.basis).toMatch(/drafted value/)
  })

  it('a REJECTED draft is no longer an AI draft — a person has to author it', () => {
    const m = fixModeOf(F({ rule_id: 'SC_1_1_1', after: 'A bar chart', rejectedFix: true }))
    expect(m.key).toBe('human')
    expect(m.basis).toMatch(/rejected/)
  })

  it('a criterion needing human judgement stays human even where the capability table says auto', () => {
    // 2.1.1 is in remediationTrack's HUMAN_JUDGEMENT_SCS precisely because a detector can DETECT it
    // without anything being able to FIX it. The capability table must not override that.
    const cap = { docx: { '2.1.1': 'auto' } }
    const m = fixModeOf(F({ rule_id: 'SC_2_1_1' }), { cap, fmt: 'docx' })
    expect(m.key).toBe('human')
    expect(m.basis).toMatch(/human judgement/)
  })

  it('an undrafted finding the capability table lists as auto is Automatic, and names that as its basis', () => {
    expect(CAPABILITY_FALLBACK.docx['1.3.1']).toBe('auto')   // the premise, pinned
    const m = fixModeOf(F({ rule_id: 'SC_1_3_1' }), { cap: CAPABILITY_FALLBACK, fmt: 'docx' })
    expect(m.key).toBe('automatic')
    expect(m.basis).toMatch(/capability table/)
  })

  it('without a capability map it does not invent a capability claim — it falls to the steps it has', () => {
    const m = fixModeOf(F({ rule_id: 'SC_1_3_1' }))
    expect(m.key).toBe('guided')
    expect(m.basis).toMatch(/fix steps/)
  })

  it('no draft and no criterion-specific steps is Human authoring required', () => {
    const m = fixModeOf(F({ rule_id: 'SC_9_9_9' }))
    expect(m.key).toBe('human')
    expect(m.basis).toMatch(/no drafted value/)
  })

  it('a blocked finding is not dressed as a fix awaiting a decision', () => {
    expect(fixModeOf(F({ rule_id: 'SC_1_3_1', status: 'blocked' })).key).toBe('blocked')
  })
})

describe('proposedValue', () => {
  it('reads after, then the first proposal', () => {
    expect(proposedValue(F({ after: 'en-US' }))).toEqual({ value: 'en-US', known: true })
    expect(proposedValue(F({ proposals: [{ proposed_value: 'Quarterly plan' }] })))
      .toEqual({ value: 'Quarterly plan', known: true })
  })
  it('reports an absent value as unknown rather than an empty string', () => {
    expect(proposedValue(F({}))).toEqual({ value: null, known: false })
    expect(proposedValue(F({ after: '' }))).toEqual({ value: null, known: false })
  })
})

describe('appliedStateOf', () => {
  it('a drafted value is NOT applied', () => {
    expect(appliedStateOf(F({ after: 'en-US' }))).toEqual({ applied: false, verified: false })
  })
  it('applied and verified are separate facts', () => {
    expect(appliedStateOf(F({ autoApplied: true }))).toEqual({ applied: true, verified: false })
    expect(appliedStateOf(F({ status: 'verified' }))).toEqual({ applied: true, verified: true })
  })
})

describe('destinationOf — ADR 0010', () => {
  const ALWAYS = /writes a corrected copy\. The original document is not modified\./

  it('says nothing about the drive when the setting has not been read', () => {
    const d = destinationOf(null)
    expect(d.known).toBe(false)
    expect(d.drive).toBeNull()
    expect(d.always).toMatch(ALWAYS)
  })

  it('an explicit null enabled is still unread, not off', () => {
    expect(destinationOf({ enabled: null, folder: 'Remediated' }).known).toBe(false)
  })

  it('with the mirror ON it names the folder a copy is written into', () => {
    // get_drive_mirror_enabled() defaults TRUE, so this is the DEFAULT deployment, not the exception.
    const d = destinationOf({ enabled: true, folder: 'Remediated' })
    expect(d.known).toBe(true)
    expect(d.drive).toMatch(/connected drive, a copy is also written to the “Remediated” folder there/)
  })

  it('with the mirror on but no folder name it does not invent one', () => {
    expect(destinationOf({ enabled: true }).drive).toMatch(/a copy is also written to the mirror folder there/)
  })

  it('only with the mirror explicitly OFF does it say the source drive is untouched', () => {
    expect(destinationOf({ enabled: false, folder: 'Remediated' }).drive).toMatch(/source drive is not written to/)
  })
})

describe('fixPreviewModel', () => {
  it('is null for no finding, so a caller renders an empty state and not a blank fix card', () => {
    expect(fixPreviewModel(null)).toBeNull()
  })

  it('assembles the problem, the mode and the destination from real fields', () => {
    const m = fixPreviewModel(
      F({ rule_id: 'SC_1_1_1', after: 'A bar chart of Q3 revenue', severity: 'SERIOUS', page: 4 }),
      { driveMirror: { enabled: true, folder: 'Remediated' } },
    )
    expect(m.sc).toBe('1.1.1')
    expect(m.criterion.name).toBe('Non-text Content')
    expect(m.mode.key).toBe('ai-draft')
    expect(m.proposed).toEqual({ value: 'A bar chart of Q3 revenue', known: true })
    expect(m.location).toBe('Page 4')
    expect(m.format).toBe('docx')
    expect(m.destination.drive).toMatch(/Remediated/)
  })

  it('attaches fix steps only to the modes that need them', () => {
    const guided = fixPreviewModel(F({ rule_id: 'SC_1_3_1' }))
    expect(guided.mode.key).toBe('guided')
    expect(guided.steps.mac).toBeTruthy()
    expect(guided.steps.specific).toBe(true)

    const auto = fixPreviewModel(F({ rule_id: 'SC_1_3_1', autoApplied: true }))
    expect(auto.mode.key).toBe('automatic')
    expect(auto.steps).toBeNull()
  })

  it('will not name an application when the format is unknown', () => {
    // fixSteps falls back to Word/Excel's Accessibility Checker path, which would be a guess for a
    // file whose format we could not resolve. No format → no steps.
    const m = fixPreviewModel({ id: 9, file: 'notes', rule_id: 'SC_1_3_1' })
    expect(m.format).toBeNull()
    expect(m.steps).toBeNull()
  })
})
