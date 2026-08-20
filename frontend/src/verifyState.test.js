/**
 * Verification state — tested for what it must REFUSE to say.
 *
 * The whole module is one withheld word. Applying a fix and clearing a finding are two events, and
 * this codebase already knows they come apart: several criteria report "applied" and do not clear,
 * because the fixer writes one metadata field and the detector reads another. So:
 *
 *   · a finding is never counted as cleared because a remediation run touched its document;
 *   · a finding is only counted as cleared where the backend's own re-scan of the CORRECTED COPY
 *     found the criterion absent — a completed remediation-state row and nothing else;
 *   · the three states partition the assessment's findings and the sum is printed.
 *
 * The mutation to try here is dropping the `state === 'complete'` filter, so a seeded
 * 'not_started' row reads as verified. Every case in "a run is not a confirmation" goes red.
 */
import { describe, it, expect } from 'vitest'
import { verifyState, reconcileVerify, wasRemediated, verifiedAtOf } from './verifyState.js'

const CRITERIA = new Set(['1.1.1', '1.3.1'])
const CAP = { docx: { '1.1.1': 'assisted', '1.3.1': 'auto' }, pdf: { '1.1.1': 'assisted' } }
const ASMT = { docx: { '1.1.1': 'review', '1.3.1': 'auto' }, pdf: { '1.1.1': 'review' } }

const doc = (name, issues = [], over = {}) => ({ file: name, name, status: 'analysed', issues, ...over })
const finding = (sc) => ({ wcag: `SC_${sc.replace(/\./g, '_')}`, severity: 'SERIOUS' })

const run = (files, over = {}) => verifyState(files, { cap: CAP, assessment: ASMT, criteria: CRITERIA, ...over })

// a.docx has been remediated (a corrected copy exists); b.docx has not.
const ESTATE = [
  doc('a.docx', [finding('1.3.1'), finding('1.1.1')], { remediated_at: '2026-08-20T16:57:00Z' }),
  doc('b.docx', [finding('1.3.1')]),
]

describe('an absent run is not a verified estate', () => {
  it('returns null when nothing has been loaded', () => {
    expect(run(null)).toBeNull()
    expect(run({ detail: 'forbidden' })).toBeNull()
    expect(reconcileVerify(null)).toBeNull()
  })
})

describe('a run is not a confirmation', () => {
  it('confirms nothing on a remediated document with no completed criteria', () => {
    // a.docx has a corrected copy and its findings are STILL findings. This is the assertion the
    // whole module exists for: applying something does not resolve anything.
    const v = run(ESTATE)
    expect(v.remediatedDocuments).toBe(1)
    expect(v.confirmedFindings).toBe(0)
    expect(v.unconfirmedFindings).toBe(2)
    expect(v.untouchedFindings).toBe(1)
  })

  it('confirms only the criterion whose remediation-state row completed', () => {
    const v = run(ESTATE, { appliedCriteria: { 'a.docx': [{ rule_id: '1.3.1', state: 'complete' }] } })
    expect(v.confirmedFindings).toBe(1)
    expect(v.unconfirmedFindings).toBe(1)     // 1.1.1 in a.docx is untouched
    expect(v.untouchedFindings).toBe(1)       // b.docx
  })

  it('ignores a seeded row that has not completed', () => {
    // Every violation gets a 'not_started' remediation_state row at assess time. Reading those as
    // verified would mark the entire estate resolved the moment it was assessed.
    const v = run(ESTATE, { appliedCriteria: { 'a.docx': [{ rule_id: '1.3.1', state: 'not_started' }] } })
    expect(v.confirmedFindings).toBe(0)
    expect(v.unconfirmedFindings).toBe(2)
  })

  it('keeps unconfirmed and untouched apart', () => {
    // Both are open findings, and they need different next steps: one had a fix attempted that did
    // not take, the other has never been touched. Collapsing them hides a failed fix.
    const v = run(ESTATE)
    expect(v.documents.find((d) => d.file === 'a.docx').remediated).toBe(true)
    expect(v.documents.find((d) => d.file === 'b.docx').remediated).toBe(false)
  })
})

describe('the three states partition the assessment findings', () => {
  it('sums to the total and prints the identity', () => {
    const v = run(ESTATE, { appliedCriteria: { 'a.docx': ['1.3.1'] } })
    const r = reconcileVerify(v)
    expect(r.ok).toBe(true)
    expect(r.line).toBe('1 confirmed cleared + 1 applied but not confirmed + '
                      + '1 not yet remediated = 3 findings')
  })

  it('cannot confirm a criterion the assessment never found here', () => {
    const v = run(ESTATE, { appliedCriteria: { 'b.docx': ['1.1.1'] } })
    expect(v.confirmedFindings).toBe(0)
    expect(reconcileVerify(v).ok).toBe(true)
  })

  it('excludes documents that could not be opened', () => {
    const v = run([...ESTATE, doc('locked.pdf', [], { status: 'error', error: 'password-protected' })])
    expect(v.documents.map((d) => d.file)).not.toContain('locked.pdf')
    expect(v.documentsAssessed).toBe(2)
    expect(reconcileVerify(v).ok).toBe(true)
  })
})

describe('a corrected copy is what makes a document remediated', () => {
  it('reads the record the backend actually writes', () => {
    expect(wasRemediated({ remediated_at: '2026-08-20T16:57:00Z' })).toBe(true)
    expect(wasRemediated({ blob_url: 'https://…' })).toBe(true)     // the durable copy, always
    expect(wasRemediated({ drive_write_url: 'https://…' })).toBe(true)  // the mirror, when enabled
    expect(wasRemediated({})).toBe(false)
    expect(wasRemediated(null)).toBe(false)
  })

  it('treats a completed criterion as evidence a run happened, even with no timestamp', () => {
    const v = run([doc('c.docx', [finding('1.3.1')])], { appliedCriteria: { 'c.docx': ['1.3.1'] } })
    expect(v.documents[0].remediated).toBe(true)
    expect(v.confirmedFindings).toBe(1)
  })

  it('carries the latest verification time, and null when none was recorded', () => {
    expect(verifiedAtOf([{ rule_id: 'a', state: 'complete', updated_at: '2026-08-20T10:00:00Z' },
                         { rule_id: 'b', state: 'complete', updated_at: '2026-08-20T16:57:00Z' }]))
      .toBe('2026-08-20T16:57:00Z')
    // A row that did not complete must not date a verification that did not happen.
    expect(verifiedAtOf([{ rule_id: 'a', state: 'not_started', updated_at: '2026-08-20T16:57:00Z' }]))
      .toBeNull()
    expect(verifiedAtOf(['1.3.1'])).toBeNull()
    expect(verifiedAtOf(undefined)).toBeNull()
  })

  it('lists the documents a re-scan would be about, and only those', () => {
    const v = run(ESTATE)
    expect(v.remediatedFiles).toEqual(['a.docx'])
  })

  it('orders documents by what is still open', () => {
    const v = run(ESTATE, { appliedCriteria: { 'a.docx': ['1.3.1', '1.1.1'] } })
    expect(v.documents.map((d) => d.file)).toEqual(['b.docx', 'a.docx'])
    expect(v.documents[1].open).toBe(0)
    expect(v.documents[1].confirmedCriteria).toEqual(['1.1.1', '1.3.1'])
  })
})
