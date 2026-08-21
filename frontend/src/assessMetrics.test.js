/**
 * The metric definitions, tested as definitions rather than as arithmetic.
 *
 * Adding up is the easy half. What these cases pin is the half that produced the screen this
 * replaces — four counts of "problems" over four unstated denominators:
 *
 *   · a document ACP could not OPEN is not an assessed document, and must not sit in the
 *     denominator of coverage;
 *   · an AI draft is not an automatic fix. Counting `assisted` as auto is precisely what turned
 *     into "51% auto-remediable" for work nobody could apply unattended;
 *   · "unable to assess" counts CHECKS THAT DID NOT RUN, never files that happened to pass;
 *   · a run that has not happened returns null, not zeros. A grid of 0s reads as a completed run
 *     that found nothing.
 *
 * The partitions are asserted to SUM, because `reconcile()` prints those sums on screen — a broken
 * partition has to be visible to the reader, not only to whoever reads the query.
 */
import { describe, it, expect } from 'vitest'
import { assessMetrics, statusOf, reconcile, coverageSentence, SEVERITIES,
         findingsByCriterion } from './assessMetrics.js'
import { findingLevel } from './findingLevel.js'

// Two criteria, so a "no method" case is expressible without inventing a third.
const CRITERIA = new Set(['1.1.1', '1.3.1'])

// 1.1.1 is an AI-drafted fix on docx; 1.3.1 is deterministic. Both are assessable.
const CAP = { docx: { '1.1.1': 'assisted', '1.3.1': 'auto' }, pdf: { '1.1.1': 'assisted', '1.3.1': 'human' } }
const ASMT = { docx: { '1.1.1': 'review', '1.3.1': 'auto' }, pdf: { '1.1.1': 'review' } }

const doc = (name, issues = [], over = {}) => ({
  file: name, name, status: 'analysed', issues, ...over,
})
const finding = (sc, severity = 'SERIOUS', over = {}) => ({
  wcag: `SC_${sc.replace(/\./g, '_')}`, rule_id: `R-${sc}`, severity, ...over,
})

const run = (files, over = {}) =>
  assessMetrics(files, { cap: CAP, assessment: ASMT, criteria: CRITERIA, ...over })

describe('an absent run is not an empty one', () => {
  it('returns null when there is no file list', () => {
    expect(assessMetrics(null, { cap: CAP, assessment: ASMT })).toBeNull()
    expect(assessMetrics(undefined, { cap: CAP, assessment: ASMT })).toBeNull()
  })

  it('returns null for the shape a failed read hands back, not a zeroed summary', () => {
    // A 403 body parses to an object. Rendering that as "0 findings in 0 documents" is a completed
    // run that found nothing — the exact false verdict the redesign exists to remove.
    expect(assessMetrics({ detail: 'forbidden' }, { cap: CAP, assessment: ASMT })).toBeNull()
  })

  it('distinguishes that from a real run over an empty estate', () => {
    const m = run([])
    expect(m).not.toBeNull()
    expect(m.documentsSelected).toBe(0)
    expect(m.status).toBe('empty')
  })
})

describe('documents assessed', () => {
  it('counts files where at least one check completed', () => {
    const m = run([doc('a.docx'), doc('b.docx')])
    expect(m.documentsAssessed).toBe(2)
    expect(m.documentsSelected).toBe(2)
  })

  it('excludes a file that could not be opened, and names it', () => {
    // THE definitional case. A file ACP never read is not an assessed file; counting it would make
    // the denominator of every coverage number on the screen wrong.
    const m = run([
      doc('good.docx'),
      doc('locked.pdf', [], { status: 'error', error: 'password-protected' }),
    ])
    expect(m.documentsSelected).toBe(2)
    expect(m.documentsAssessed).toBe(1)
    expect(m.documentsUnopened).toEqual([
      { file: 'locked.pdf', name: 'locked.pdf', reason: 'password-protected' },
    ])
  })

  it('keeps an unopened file out of the check denominator entirely', () => {
    const one = run([doc('good.docx')])
    const two = run([doc('good.docx'), doc('locked.pdf', [], { status: 'error' })])
    expect(two.selectedChecks, 'an unopened file contributed checks').toBe(one.selectedChecks)
  })
})

describe('documents needing attention', () => {
  it('counts distinct files holding at least one unresolved finding', () => {
    const m = run([
      doc('a.docx', [finding('1.1.1'), finding('1.3.1')]),
      doc('b.docx', [finding('1.1.1')]),
      doc('c.docx'),
    ])
    expect(m.documentsNeedingAttention).toBe(2)
    expect(m.totalFindings).toBe(3)
  })

  it('ignores a finding that has already been resolved', () => {
    // Written so the metric starts falling the moment the backend sends the field, rather than
    // needing a second change here. Absence of the field means unresolved, which is the safe way
    // round: a fixed finding lingering is visible; a live one vanishing is not.
    const m = run([doc('a.docx', [finding('1.1.1', 'SERIOUS', { resolution: 'fixed' })])])
    expect(m.totalFindings).toBe(0)
    expect(m.documentsNeedingAttention).toBe(0)
  })

  it('counts a finding with no resolution field as unresolved', () => {
    expect(run([doc('a.docx', [finding('1.1.1')])]).totalFindings).toBe(1)
  })
})

describe('auto-fix means deterministic, and nothing else', () => {
  it('counts a deterministic fix and not an AI draft', () => {
    // 1.3.1 is 'auto' on docx; 1.1.1 is 'assisted' — an AI draft awaiting a person's approval.
    const m = run([doc('a.docx', [finding('1.3.1'), finding('1.1.1')])])
    expect(m.autoFixAvailable, 'an AI draft was counted as an automatic fix').toBe(1)
    expect(m.humanReviewRequired).toBe(1)
  })

  it('counts a re-authoring criterion under human review', () => {
    const m = run([doc('a.pdf', [finding('1.3.1')])])   // 'human' on pdf
    expect(m.autoFixAvailable).toBe(0)
    expect(m.humanReviewRequired).toBe(1)
  })

  it('is format-aware — the same criterion differs by file type', () => {
    // 1.3.1 is deterministic on docx and re-authoring on pdf. A format-blind flag reported a docx
    // as "0 auto-fixable" once; this is the assertion that stops it recurring.
    const docx = run([doc('a.docx', [finding('1.3.1')])])
    const pdf = run([doc('a.pdf', [finding('1.3.1')])])
    expect(docx.autoFixAvailable).toBe(1)
    expect(pdf.autoFixAvailable).toBe(0)
  })

  it('treats an unknown pair as human, never as a silent auto', () => {
    const m = assessMetrics([doc('a.docx', [finding('1.3.1')])],
      { cap: {}, assessment: ASMT, criteria: CRITERIA })
    expect(m.autoFixAvailable).toBe(0)
  })
})

describe('unable to assess counts checks, not files', () => {
  it('counts selected checks with no method for that format', () => {
    // pdf has a lane for 1.1.1 and none for 1.3.1 — so one of the two selected checks could not run.
    const m = run([doc('a.pdf')])
    expect(m.selectedChecks).toBe(2)
    expect(m.checksEvaluated).toBe(1)
    expect(m.unableToAssess).toBe(1)
    expect(m.unassessableCriteria).toEqual(['1.3.1'])
  })

  it('does not count a file that simply passed everything', () => {
    // THE misreading in the previous panel: a clean document is not an unassessed one.
    const m = run([doc('a.docx')])
    expect(m.unableToAssess).toBe(0)
    expect(m.checksEvaluated).toBe(2)
  })

  it('treats the human lane as a check that did not run', () => {
    // 'human' means a person assesses it end to end — ACP produced no verdict, so it is neither a
    // pass nor a failure and must not be counted as coverage.
    const m = assessMetrics([doc('a.docx')],
      { cap: CAP, assessment: { docx: { '1.1.1': 'human', '1.3.1': 'auto' } }, criteria: CRITERIA })
    expect(m.unableToAssess).toBe(1)
    expect(m.coverageEvaluated).toBe(1)
  })
})

describe('coverage is a fraction of a named list', () => {
  it('counts a criterion evaluated in any assessed document', () => {
    const m = run([doc('a.pdf'), doc('b.docx')])
    expect(m.coverageEvaluated).toBe(2)      // 1.3.1 ran on the docx even though it could not on the pdf
    expect(m.coverageSelected).toBe(2)
    expect(coverageSentence(m)).toBe('2 of 2 selected criteria evaluated')
  })

  it('reports a fraction, never a percentage', () => {
    // A percentage hides WHICH criteria went unevaluated, which is the only actionable part.
    expect(coverageSentence(run([doc('a.pdf')]))).toBe('1 of 2 selected criteria evaluated')
    expect(coverageSentence(run([doc('a.pdf')]))).not.toMatch(/%/)
  })

  it('returns null with no metrics rather than a sentence about nothing', () => {
    expect(coverageSentence(null)).toBeNull()
  })
})

describe('the conformance target actually filters', () => {
  it('drops a finding above the target level', () => {
    const aaa = { wcag: 'SC_1_1_1', severity: 'MINOR', level: 'AAA' }
    expect(run([doc('a.docx', [aaa])], { level: 'AA' }).totalFindings).toBe(0)
    expect(run([doc('a.docx', [aaa])], { level: 'AAA' }).totalFindings).toBe(1)
  })

  it('derives a level for a finding that carries none', () => {
    expect(findingLevel({ wcag: 'SC_1_1_1' })).toBe('A')
    expect(findingLevel({ wcag: 'SC_1_1_1', level: 'AAA' })).toBe('AAA')
  })

  it('defaults an unknown criterion to the strictest reading', () => {
    // A finding that should not have blocked is arguable. One that silently vanished is not
    // visible at all, so the unknown case blocks rather than disappears.
    expect(findingLevel({ wcag: 'SC_9_9_9' })).toBe('A')
  })
})

describe('severity partitions the findings', () => {
  it('counts each finding under exactly one severity', () => {
    const m = run([doc('a.docx', [
      finding('1.1.1', 'CRITICAL'), finding('1.1.1', 'SERIOUS'),
      finding('1.3.1', 'MODERATE'), finding('1.3.1', 'MINOR'),
    ])])
    expect(m.bySeverity).toEqual({ CRITICAL: 1, SERIOUS: 1, MODERATE: 1, MINOR: 1, UNKNOWN: 0 })
  })

  it('gives an unrecognised severity its own bucket rather than dropping it', () => {
    // Dropping it would break the printed sum silently — the one outcome worse than an odd label.
    const m = run([doc('a.docx', [finding('1.1.1', 'CATASTROPHIC')])])
    expect(m.bySeverity.UNKNOWN).toBe(1)
    expect(reconcile(m).findings.ok).toBe(true)
  })
})

describe('the arithmetic the screen prints', () => {
  const m = () => run([
    doc('a.docx', [finding('1.1.1', 'CRITICAL'), finding('1.3.1', 'SERIOUS')]),
    doc('b.pdf', [finding('1.1.1', 'MODERATE')]),
    doc('c.docx'),
    doc('locked.pdf', [], { status: 'error', error: 'password-protected' }),
  ])

  it('reconciles the findings', () => {
    const r = reconcile(m())
    expect(r.findings.ok).toBe(true)
    expect(r.findings.line).toBe('1 auto-fixable + 2 needing review = 3 findings')
  })

  it('reconciles the checks, and names both factors of the denominator', () => {
    const r = reconcile(m())
    expect(r.checks.ok).toBe(true)
    expect(r.checks.line).toMatch(/= 6 selected checks \(3 documents × 2 criteria\)/)
  })

  it('sums severity to the finding total', () => {
    const met = m()
    const sum = SEVERITIES.reduce((a, s) => a + met.bySeverity[s], 0) + met.bySeverity.UNKNOWN
    expect(sum).toBe(met.totalFindings)
  })

  it('returns null rather than a reconciliation of nothing', () => {
    expect(reconcile(null)).toBeNull()
  })
})

describe('screen state, in precedence order', () => {
  const st = (o) => statusOf({ selected: 1, assessed: 1, findings: 0, anyReviewLane: false, ...o })

  it('nothing matched the scope', () => {
    expect(st({ selected: 0, assessed: 0 })).toBe('empty')
  })

  it('failed beats everything else that could be true', () => {
    // No check reached a terminal state. A failed run must never present as clear.
    expect(st({ assessed: 0 })).toBe('failed')
    expect(st({ assessed: 0, findings: 5 })).toBe('failed')
  })

  it('partial beats attention, so a stopped run is never read as a complete one', () => {
    expect(st({ notStarted: 3, findings: 9 })).toBe('partial')
  })

  it('only claims partial when the caller actually knows', () => {
    // The file list alone cannot say how many documents were never started. Guessing would
    // manufacture the very state this is meant to expose.
    expect(st({ findings: 2 })).toBe('attention')
    expect(st({ notStarted: 0, findings: 2 })).toBe('attention')
    expect(st({ notStarted: undefined, findings: 0 })).toBe('clear')
  })

  it('separates awaiting-review from clear', () => {
    expect(st({ findings: 0, anyReviewLane: true })).toBe('awaiting_review')
    expect(st({ findings: 0, anyReviewLane: false })).toBe('clear')
  })

  it('reads a stopped run as partial from runStatus alone, before any not-started count', () => {
    // A cancelled or interrupted run did not reach the end of its scope. That is partial even when
    // the caller cannot yet say how many documents were skipped — the file list is what get_scan
    // returns, which is only what ran. Findings present must not let it read as a complete result.
    expect(st({ runStatus: 'cancelled', findings: 9 })).toBe('partial')
    expect(st({ runStatus: 'interrupted', findings: 0 })).toBe('partial')
  })

  it('reads an errored run as failed even where a record survived', () => {
    expect(st({ runStatus: 'error', assessed: 1, findings: 5 })).toBe('failed')
  })

  it('leaves a completed run classified exactly as before the argument existed', () => {
    // 'done' and undefined are the no-op: a completed run is still classified by its findings only,
    // so nothing on the happy path moves.
    expect(st({ runStatus: 'done', findings: 3 })).toBe('attention')
    expect(st({ runStatus: 'done', findings: 0, anyReviewLane: false })).toBe('clear')
    expect(st({ runStatus: undefined, findings: 0, anyReviewLane: false })).toBe('clear')
  })

  it('never lets no-scope be masked by the run status', () => {
    // Empty is decided first: a scope that selected nothing is "nothing to assess", not a failure of
    // a run that never had anything to do.
    expect(st({ selected: 0, assessed: 0, runStatus: 'error' })).toBe('empty')
  })

  it('threads runStatus through assessMetrics onto a real estate', () => {
    expect(run([doc('a.docx', [finding('1.1.1')])], { runStatus: 'cancelled' }).status).toBe('partial')
    expect(run([doc('a.docx', [finding('1.1.1')])], { runStatus: 'done' }).status).toBe('attention')
  })

  it('derives the state from a real estate', () => {
    expect(run([doc('a.docx', [finding('1.1.1')])]).status).toBe('attention')
    expect(run([doc('a.docx')]).status).toBe('awaiting_review')   // 1.1.1 is a review lane on docx
    expect(run([doc('a.pdf', [], { status: 'error' })]).status).toBe('failed')
  })
})

describe('what this module refuses to compute', () => {
  it('exposes no score, no percentage and no effort estimate', () => {
    const m = run([doc('a.docx', [finding('1.1.1')])])
    const keys = Object.keys(m).join(' ')
    expect(keys, 'a score is back').not.toMatch(/score/i)
    expect(keys, 'a percentage is back').not.toMatch(/pct|percent/i)
    expect(keys, 'an effort estimate is back').not.toMatch(/hours|minutes|effort|eta/i)
  })
})

describe('what needs a person comes first', () => {
  // The ordering principle, and it is deliberately NOT "worst first". A finding ACP fixes
  // deterministically costs a human nothing — one button in remediation and it is gone. A finding
  // needing judgement costs attention, which is the only scarce thing on this screen. So the list
  // leads with what needs somebody and sinks what does not.
  //
  // Nothing is hidden by this. An auto-fixable critical is still shown, still red, still counted
  // in every total; it simply stops occupying the top of a list of things to do.
  const auto = (sev) => finding('1.3.1', sev)      // deterministic on docx
  const person = (sev) => finding('1.1.1', sev)    // 'assisted' on docx — a draft, so a person

  it('ranks one serious finding needing a person above ten auto-fixable criticals', () => {
    const m = run([
      doc('machine.docx', Array.from({ length: 10 }, () => auto('CRITICAL'))),
      doc('human.docx', [person('SERIOUS')]),
    ])
    expect(m.rows.map((r) => r.name)).toEqual(['human.docx', 'machine.docx'])
  })

  it('still orders by severity among documents that all need a person', () => {
    const m = run([
      doc('minor.docx', [person('MINOR')]),
      doc('critical.docx', [person('CRITICAL')]),
      doc('moderate.docx', [person('MODERATE')]),
    ])
    expect(m.rows.map((r) => r.name)).toEqual(['critical.docx', 'moderate.docx', 'minor.docx'])
  })

  it('does not hide the auto-fixable work it deprioritises', () => {
    const m = run([doc('machine.docx', [auto('CRITICAL')]), doc('human.docx', [person('MINOR')])])
    const machine = m.rows.find((r) => r.name === 'machine.docx')
    expect(machine.bySeverity.CRITICAL, 'a deprioritised finding stopped being counted').toBe(1)
    expect(m.totalFindings).toBe(2)
  })

  it('marks whether a document needs a person at all', () => {
    const m = run([doc('machine.docx', [auto('CRITICAL')]), doc('human.docx', [person('MINOR')])])
    expect(m.rows.find((r) => r.name === 'machine.docx').needsPerson).toBe(false)
    expect(m.rows.find((r) => r.name === 'human.docx').needsPerson).toBe(true)
  })

  it('sorts a file that never opened last — it holds no work at all', () => {
    const m = run([
      doc('locked.docx', [], { status: 'error' }),
      doc('machine.docx', [auto('MINOR')]),
      doc('human.docx', [person('MINOR')]),
    ])
    expect(m.rows.map((r) => r.name)).toEqual(['human.docx', 'machine.docx', 'locked.docx'])
  })

  it('applies the same rule to the criterion groups inside one file', () => {
    const row = run([doc('a.docx', [auto('CRITICAL'), person('MINOR')])]).rows[0]
    const groups = findingsByCriterion(row)
    expect(groups.map((g) => g.sc), 'an auto-fixable group outranked one needing a person')
      .toEqual(['1.1.1', '1.3.1'])
    expect(groups[0].needsPerson).toBe(true)
    expect(groups[1].needsPerson).toBe(false)
  })

  it('returns no groups for a file that never opened', () => {
    expect(findingsByCriterion(run([doc('x.docx', [], { status: 'error' })]).rows[0])).toBeNull()
  })
})
