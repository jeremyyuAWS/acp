/**
 * The remediation partition, tested as a set of claims rather than as arithmetic.
 *
 * The claim that matters most, and the one a single character breaks:
 *
 *   an AI DRAFT IS NOT AN AUTOMATIC FIX.
 *
 * `laneOfFinding` reads `fixMode` against three named literals precisely so that folding 'assisted'
 * into 'auto' is a visible edit. Prove it: change `fixMode === 'auto'` to
 * `fixMode !== 'human'` in remediationWork.js and the three cases marked MUTATION below go red —
 * the automatic count, the drafted count, and the batch scope that the Apply button acts on. That
 * mutation is exactly what produced "51% auto-remediable" for work nobody could apply unattended,
 * so it is the mutation these tests exist to catch.
 *
 * The other claims:
 *   · the five lanes SUM to the assessment's own finding total — printed on screen, so a broken
 *     partition is visible to a reader rather than only to whoever reads the query;
 *   · "applied" only ever comes from a completed remediation-state row, never from a run having
 *     been started, and never from a criterion this assessment did not find;
 *   · an absent run returns null, not five zeros.
 */
import { describe, it, expect } from 'vitest'
import { remediationWork, reconcileWork, batchScope, laneOfFinding, criteriaNamed,
         WORK_LANES } from './remediationWork.js'

const CRITERIA = new Set(['1.1.1', '1.3.1', '1.4.3'])
// 1.1.1 is an AI draft on docx, 1.3.1 is deterministic, 1.4.3 has no entry → 'human'.
const CAP = { docx: { '1.1.1': 'assisted', '1.3.1': 'auto' },
              pdf: { '1.1.1': 'assisted', '1.3.1': 'human', '1.4.3': 'auto' } }
const ASMT = { docx: { '1.1.1': 'review', '1.3.1': 'auto', '1.4.3': 'review' },
               pdf: { '1.1.1': 'review', '1.3.1': 'review', '1.4.3': 'auto' } }

const doc = (name, issues = [], over = {}) => ({ file: name, name, status: 'analysed', issues, ...over })
const finding = (sc, severity = 'SERIOUS') => ({ wcag: `SC_${sc.replace(/\./g, '_')}`, severity })

const run = (files, over = {}) =>
  remediationWork(files, { cap: CAP, assessment: ASMT, criteria: CRITERIA, ...over })

// a.docx: 1.3.1 auto, 1.3.1 auto, 1.1.1 assisted, 1.4.3 human   → 2 auto, 1 drafted, 1 authored
// b.pdf : 1.4.3 auto, 1.1.1 assisted                            → 1 auto, 1 drafted
const ESTATE = [
  doc('a.docx', [finding('1.3.1'), finding('1.3.1'), finding('1.1.1', 'CRITICAL'), finding('1.4.3')]),
  doc('b.pdf', [finding('1.4.3'), finding('1.1.1', 'CRITICAL')]),
  doc('clean.docx'),
  doc('locked.pdf', [], { status: 'error', error: 'password-protected' }),
]

describe('an absent run is not an empty one', () => {
  it('returns null with no file list', () => {
    expect(run(null)).toBeNull()
    expect(run(undefined)).toBeNull()
  })

  it('returns null for the object shape a failed read hands back', () => {
    // Rendering "0 automatic · 0 drafted · 0 authored" from a 403 body is a completed remediation
    // screen reporting no work — the exact false verdict the null exists to prevent.
    expect(run({ detail: 'forbidden' })).toBeNull()
  })

  it('distinguishes that from a real run over an empty estate', () => {
    const w = run([])
    expect(w).not.toBeNull()
    expect(w.assessmentTotal).toBe(0)
    expect(reconcileWork(w).ok).toBe(true)
  })
})

describe('an AI draft is not an automatic fix', () => {
  it('counts only deterministic findings as automatic', () => {          // MUTATION
    const w = run(ESTATE)
    expect(w.lanes.automatic.count).toBe(3)      // 2 × 1.3.1 on docx, 1 × 1.4.3 on pdf
  })

  it('counts assisted findings in their own lane, never in automatic', () => {   // MUTATION
    const w = run(ESTATE)
    expect(w.lanes.drafted.count).toBe(2)        // 1.1.1 on each document
    // Said as an identity rather than as two numbers: automatic + drafted is the whole of what
    // "51% auto-remediable" claimed was automatable, and only the first half of it is.
    expect(w.lanes.automatic.count + w.lanes.drafted.count).toBe(5)
    expect(w.lanes.automatic.count).not.toBe(5)
  })

  it('puts a criterion with no capability entry in the authoring lane, not the automatic one', () => {
    const w = run(ESTATE)
    // 1.4.3 is absent from CAP.docx, so modeFor resolves it to 'human'.
    expect(w.lanes.authored.count).toBe(1)
    expect(w.lanes.authored.findings[0].sc).toBe('1.4.3')
    expect(w.lanes.authored.findings[0].file).toBe('a.docx')
  })

  it('routes each fixMode to exactly one lane', () => {
    expect(laneOfFinding({ sc: '1.3.1', fixMode: 'auto' })).toBe('automatic')
    expect(laneOfFinding({ sc: '1.1.1', fixMode: 'assisted' })).toBe('drafted')
    expect(laneOfFinding({ sc: '1.4.3', fixMode: 'human' })).toBe('authored')
    // An unrecognised mode is authoring work — the lane that asks a person to look. It must never
    // fall through to automatic, which would apply something unattended on the strength of a typo.
    expect(laneOfFinding({ sc: '9.9.9', fixMode: 'probably-fine' })).toBe('authored')
    expect(laneOfFinding({ sc: '9.9.9' })).toBe('authored')
  })
})

describe('the partition sums to the assessment total', () => {
  it('adds up across every lane', () => {
    const w = run(ESTATE)
    const sum = WORK_LANES.reduce((a, k) => a + w.lanes[k].count, 0)
    expect(sum).toBe(w.assessmentTotal)
    expect(w.assessmentTotal).toBe(6)
  })

  it('prints the identity as a line, in lane order', () => {
    const r = reconcileWork(run(ESTATE))
    expect(r.ok).toBe(true)
    expect(r.line).toBe('3 + 2 + 1 + 0 + 0 = 6 findings')
  })

  it('counts a one-finding estate with a singular noun', () => {
    const r = reconcileWork(run([doc('a.docx', [finding('1.3.1')])]))
    expect(r.line).toBe('1 + 0 + 0 + 0 + 0 = 1 finding')
  })

  it('excludes documents that could not be opened from every lane', () => {
    // locked.pdf is in the estate and holds no findings — it must not appear anywhere, and it must
    // not be counted as a document with work.
    const w = run(ESTATE)
    for (const k of WORK_LANES) expect(w.lanes[k].files).not.toContain('locked.pdf')
    expect(w.documentsAssessed).toBe(3)
    expect(w.documentsWithFindings).toBe(2)
  })
})

describe('applied means a re-scan confirmed it, not that a run started', () => {
  it('moves a finding out of the outstanding lanes when its criterion completed', () => {
    const w = run(ESTATE, { appliedCriteria: { 'a.docx': [{ rule_id: '1.3.1', state: 'complete' }] } })
    expect(w.lanes.applied.count).toBe(2)      // both 1.3.1 findings in a.docx
    expect(w.lanes.automatic.count).toBe(1)    // only b.pdf's 1.4.3 is left
    expect(reconcileWork(w).ok).toBe(true)
  })

  it('ignores a remediation-state row that has not completed', () => {
    // The whole hazard of this input: a 'not_started' row read as done takes real work off the
    // screen, and the total still sums, so nothing looks wrong.
    const w = run(ESTATE, { appliedCriteria: { 'a.docx': [{ rule_id: '1.3.1', state: 'not_started' }] } })
    expect(w.lanes.applied.count).toBe(0)
    expect(w.lanes.automatic.count).toBe(3)
  })

  it('cannot invent an applied finding this assessment did not report', () => {
    // A criterion completed on a document that has no finding for it must add nothing. The lanes
    // are subsets of the assessment's population, never a second population beside it.
    const w = run(ESTATE, { appliedCriteria: { 'clean.docx': ['1.3.1'], 'a.docx': ['2.4.2'] } })
    expect(w.lanes.applied.count).toBe(0)
    expect(w.assessmentTotal).toBe(6)
    expect(reconcileWork(w).ok).toBe(true)
  })

  it('scopes applied criteria per document', () => {
    // 1.4.3 completed on b.pdf must not clear a.docx's 1.4.3 finding.
    const w = run(ESTATE, { appliedCriteria: { 'b.pdf': ['1.4.3'] } })
    expect(w.lanes.applied.count).toBe(1)
    expect(w.lanes.applied.files).toEqual(['b.pdf'])
    expect(w.lanes.authored.count).toBe(1)     // a.docx's 1.4.3 is untouched
  })

  it('takes applied ahead of unfixable, so no finding is counted twice', () => {
    const w = run(ESTATE, { appliedCriteria: { 'a.docx': ['1.3.1'] },
                            unfixableCriteria: { 'a.docx': ['1.3.1', '1.1.1'] } })
    expect(w.lanes.applied.count).toBe(2)
    expect(w.lanes.unfixable.count).toBe(1)    // 1.1.1 only
    expect(reconcileWork(w).ok).toBe(true)
  })

  it('reads plain criterion strings and stateful rows the same way', () => {
    expect([...criteriaNamed(['1.3.1', '2.4.2'])]).toEqual(['1.3.1', '2.4.2'])
    expect([...criteriaNamed([{ rule_id: '1.3.1', state: 'complete' }])]).toEqual(['1.3.1'])
    expect([...criteriaNamed([{ rule_id: '1.3.1', state: 'not_started' }])]).toEqual([])
    expect([...criteriaNamed(undefined)]).toEqual([])
    expect([...criteriaNamed([null, '', {}])]).toEqual([])
  })
})

describe('the batch acts on the deterministic lane and no other', () => {
  it('scopes to the documents holding automatic findings', () => {       // MUTATION
    const b = batchScope(run(ESTATE))
    expect(b.count).toBe(3)
    expect(b.files).toEqual(['a.docx', 'b.pdf'])
    expect(b.documents).toBe(2)
    // The criteria named beside the button are the deterministic ones only. 1.1.1 is drafted on
    // both documents and must not be advertised as something the button will apply.
    expect(b.criteria).toEqual(['1.3.1', '1.4.3'])
    expect(b.criteria).not.toContain('1.1.1')
  })

  it('is null when nothing is deterministic, so no button is offered over zero fixes', () => {
    const est = [doc('a.docx', [finding('1.1.1'), finding('1.4.3')])]
    const w = run(est)
    expect(w.lanes.automatic.count).toBe(0)
    expect(batchScope(w)).toBeNull()
  })

  it('is null when the run has not happened', () => {
    expect(batchScope(null)).toBeNull()
    expect(reconcileWork(null)).toBeNull()
  })

  it('drops a document from the batch once its automatic work is confirmed applied', () => {
    const b = batchScope(run(ESTATE, { appliedCriteria: { 'a.docx': ['1.3.1'] } }))
    expect(b.files).toEqual(['b.pdf'])
    expect(b.count).toBe(1)
  })
})
