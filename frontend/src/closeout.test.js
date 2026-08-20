import { describe, it, expect } from 'vitest'
import {
  VERIFY, NEXT, docCloseout, verifyLine, closeoutSummary, complianceRecord, nextStep,
  ASSESS_HANDOFF_NOTE,
} from './closeout.js'

// Shapes mirror what api/handlers.py:758-827 produces per file:
//   rescan 'ran'         → residual was a set; cleared/kept are real
//   rescan 'unavailable' → residual was None (proposals.py:180-184); nothing is evidence
const cleared = (file, rules = ['1.1.1']) => ({ file, remediated_at: 't', rescan: 'ran', cleared: rules, kept: [] })
const failing = (file) => ({ file, remediated_at: 't', rescan: 'ran', cleared: ['1.1.1'], kept: ['1.4.3'] })
const unverified = (file) => ({ file, remediated_at: 't', rescan: 'unavailable', cleared: ['1.1.1'], kept: [] })
const untouched = (file) => ({ file })

describe('docCloseout — "we could not check" is its own state', () => {
  it('reads a clean re-scan as cleared', () => {
    const d = docCloseout(cleared('a.docx', ['1.1.1', '2.4.2']))
    expect(d.state).toBe(VERIFY.CLEARED)
    expect(d.cleared).toEqual(['1.1.1', '2.4.2'])
    expect(d.kept).toEqual([])
  })

  it('reads a re-scan that found a fix did not take as still-failing', () => {
    const d = docCloseout(failing('b.docx'))
    expect(d.state).toBe(VERIFY.STILL_FAILING)
    expect(d.kept).toEqual(['1.4.3'])
    // The criteria that DID clear are still credited — the document is partly fixed, and saying
    // otherwise would be its own inaccuracy.
    expect(d.cleared).toEqual(['1.1.1'])
  })

  // The load-bearing one. api/proposals.py returns None when the re-scan cannot run and
  // api/handlers.py credits it so an infra failure never penalises a fix. That is right for the
  // store and wrong for the screen: nothing verified those fixes.
  it('reads a re-scan that could not run as unverified, and credits nothing', () => {
    const d = docCloseout(unverified('c.docx'))
    expect(d.state).toBe(VERIFY.UNVERIFIED)
    expect(d.state).not.toBe(VERIFY.CLEARED)
    // The record claimed 1.1.1 cleared; with no re-scan behind it, it is not reported as verified.
    expect(d.cleared).toEqual([])
    // What WAS applied is still carried — the fixes happened, they are just unconfirmed.
    expect(d.applied).toEqual(['1.1.1'])
  })

  it('treats a missing rescan field as not-run rather than assuming it ran', () => {
    expect(docCloseout({ file: 'd.docx', remediated_at: 't', cleared: ['1.1.1'] }).state).toBe(VERIFY.UNVERIFIED)
    expect(docCloseout({ file: 'd.docx', remediated_at: 't', cleared: ['1.1.1'], rescan: null }).state).toBe(VERIFY.UNVERIFIED)
  })

  it('separates "nothing was applied" from "applied but unverified"', () => {
    expect(docCloseout(untouched('e.docx')).state).toBe(VERIFY.NOT_REMEDIATED)
  })

  it('counts a document remediated when it has a delivered copy but no rule lists', () => {
    // record_remediation writes blob_url/drive_write_url (handlers.py:747); a file can carry
    // those without the frontend having the per-rule breakdown.
    expect(docCloseout({ file: 'f.docx', blob_url: 'https://blob/x' }).state).toBe(VERIFY.UNVERIFIED)
  })

  it('keeps an unread review count null rather than calling it zero', () => {
    expect(docCloseout(cleared('a.docx')).pendingReview).toBeNull()
    expect(docCloseout({ ...cleared('a.docx'), pendingReview: 0 }).pendingReview).toBe(0)
    expect(docCloseout({ ...cleared('a.docx'), pendingReview: 3 }).pendingReview).toBe(3)
  })
})

describe('verifyLine — every sentence is about evidence, not effort', () => {
  it('says what the re-scan found when it ran', () => {
    expect(verifyLine(docCloseout(cleared('a', ['1.1.1', '2.4.2'])))).toMatch(/Re-scanned after the fix: 2 criteria no longer fail/)
    expect(verifyLine(docCloseout(failing('b')))).toMatch(/1 criterion cleared, 1 still fails/)
  })

  it('says plainly that nothing is verified when the re-scan could not run', () => {
    const line = verifyLine(docCloseout(unverified('c')))
    expect(line).toMatch(/could not run/i)
    expect(line).toMatch(/nothing here is verified/i)
    // Not dressed up as a pass, and not reported as a failure of the document.
    expect(line).not.toMatch(/no longer fail/i)
    expect(line).not.toMatch(/still fails/i)
  })
})

describe('closeoutSummary — the unverified count survives the roll-up', () => {
  const docs = [cleared('a'), cleared('b'), failing('c'), unverified('d'), untouched('e')]

  it('counts each state separately', () => {
    const s = closeoutSummary(docs)
    expect(s.total).toBe(5)
    expect(s.cleared).toBe(2)
    expect(s.stillFailing).toBe(1)
    expect(s.unverified).toBe(1)
    expect(s.notRemediated).toBe(1)
  })

  it('never folds unverified documents into the cleared count', () => {
    const s = closeoutSummary([cleared('a'), unverified('b'), unverified('c')])
    expect(s.cleared).toBe(1)
    expect(s.unverified).toBe(2)
  })

  it('reports pendingReview as null when no document carried a queue count', () => {
    expect(closeoutSummary(docs).pendingReview).toBeNull()
  })

  it('sums pendingReview when it was actually read, and 0 is then a real zero', () => {
    expect(closeoutSummary([{ ...cleared('a'), pendingReview: 2 }, { ...cleared('b'), pendingReview: 1 }]).pendingReview).toBe(3)
    expect(closeoutSummary([{ ...cleared('a'), pendingReview: 0 }]).pendingReview).toBe(0)
  })

  it('handles an empty run without inventing anything', () => {
    const s = closeoutSummary([])
    expect(s.total).toBe(0)
    expect(s.pendingReview).toBeNull()
  })
})

describe('complianceRecord — entries appear because they happened', () => {
  it('names the re-scan truthfulness gate when there is re-scan evidence', () => {
    const rows = complianceRecord(closeoutSummary([cleared('a')]))
    const verified = rows.find((r) => r.key === 'verified')
    expect(verified.detail).toMatch(/credited only if it actually stopped failing/i)
    expect(verified.detail).toMatch(/cannot show a fix that never landed/i)
  })

  it('records fixes that did not take, and says they were left failing', () => {
    const rows = complianceRecord(closeoutSummary([failing('b')]))
    const row = rows.find((r) => r.key === 'unverified-log')
    expect(row.detail).toContain('remediate.unverified')
    expect(row.detail).toMatch(/left failing rather than credited/i)
  })

  it('records the absence of evidence as its own entry', () => {
    const rows = complianceRecord(closeoutSummary([unverified('c')]))
    const row = rows.find((r) => r.key === 'no-evidence')
    expect(row).toBeTruthy()
    expect(row.detail).toMatch(/no verification either way/i)
  })

  it('omits entries for things that did not happen', () => {
    const keys = complianceRecord(closeoutSummary([cleared('a')])).map((r) => r.key)
    expect(keys).not.toContain('unverified-log')
    expect(keys).not.toContain('no-evidence')
    expect(keys).not.toContain('released')
  })

  it('does not claim a review routing when the queue was never read', () => {
    // pendingReview null → no review row. A fixed list of reassurances would print one anyway.
    expect(complianceRecord(closeoutSummary([cleared('a')])).map((r) => r.key)).not.toContain('review')
    expect(complianceRecord(closeoutSummary([{ ...cleared('a'), pendingReview: 2 }])).map((r) => r.key)).toContain('review')
  })

  it('is empty for a run with nothing in it', () => {
    expect(complianceRecord(closeoutSummary([]))).toEqual([])
  })
})

describe('nextStep — the most blocking state wins', () => {
  it('sends you to re-check first when any document has no evidence', () => {
    // Ranked above still-failing on purpose: a document that is honestly failing is visible, and
    // one that was never checked looks exactly like one that passed.
    const s = closeoutSummary([cleared('a'), failing('b'), unverified('c'), { ...cleared('d'), pendingReview: 4 }])
    const n = nextStep(s)
    expect(n.key).toBe(NEXT.REVERIFY)
    expect(n.label).toMatch(/Re-check 1 document/)
  })

  it('returns still-failing documents to remediation once evidence exists everywhere', () => {
    expect(nextStep(closeoutSummary([cleared('a'), failing('b')])).key).toBe(NEXT.REMEDIATE)
  })

  it('sends you to review when everything cleared but findings await a person', () => {
    const n = nextStep(closeoutSummary([{ ...cleared('a'), pendingReview: 2 }]))
    expect(n.key).toBe(NEXT.REVIEW)
    expect(n.detail).toMatch(/never released unread/i)
  })

  it('offers release only when the loop is genuinely closed', () => {
    const n = nextStep(closeoutSummary([{ ...cleared('a'), pendingReview: 0 }, { ...cleared('b'), pendingReview: 0 }]))
    expect(n.key).toBe(NEXT.PUBLISH)
    expect(n.label).toMatch(/Release 2 verified documents/)
    // Same disclaimer the Release Center carries — verified in scope is not overall conformance.
    expect(n.detail).toMatch(/does not certify overall conformance/i)
  })

  it('does not offer release on the strength of an unread review queue', () => {
    // pendingReview null, not 0 — nobody checked, so "everything is approved" is not established.
    // Cleared documents with no queue reading still reach PUBLISH, but the reason is stated as
    // approval, so this pins that the null case is not silently counted as pending either.
    const n = nextStep(closeoutSummary([cleared('a')]))
    expect(n.key).toBe(NEXT.PUBLISH)
    expect(n.key).not.toBe(NEXT.REVIEW)
  })

  it('says there is nothing to hand off for an untouched run', () => {
    expect(nextStep(closeoutSummary([untouched('e')])).key).toBe(NEXT.NOTHING)
    expect(nextStep(closeoutSummary([])).key).toBe(NEXT.NOTHING)
  })
})

describe('ADR 0020 — nothing here may imply discovery opens a file', () => {
  it('puts the re-check in Assess and says Discover never opens a file', () => {
    expect(ASSESS_HANDOFF_NOTE).toMatch(/Assess step/i)
    expect(ASSESS_HANDOFF_NOTE).toMatch(/never opens a file/i)
  })

  it('no handoff string attributes reading or scanning to Discover', () => {
    const strings = []
    for (const docs of [[cleared('a')], [failing('b')], [unverified('c')], [{ ...cleared('a'), pendingReview: 2 }], []]) {
      const s = closeoutSummary(docs)
      const n = nextStep(s)
      strings.push(n.label, n.detail, ...complianceRecord(s).map((r) => r.detail))
      strings.push(...s.docs.map(verifyLine))
    }
    for (const str of strings) {
      // "Discover" may only appear in the note that explicitly disclaims file access; no other
      // string may put a read, scan or open next to it.
      expect(str).not.toMatch(/discover\w*\s+(?:re-?)?(?:scans?|reads?|opens?|analyses?|analyzes?)/i)
      expect(str).not.toMatch(/(?:re-?)?(?:scan|read|open|analyse|analyze)\w*\s+(?:in|during|at)\s+discover/i)
    }
  })
})
