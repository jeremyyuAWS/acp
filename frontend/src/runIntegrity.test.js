// The verdict, asserted directly. No DOM — this is the safety mechanism on the Assess screen and
// it should be checkable without rendering anything.
//
// The four scenarios these cover are the four ways a run can lie to a reader:
//   incomplete scan   — checks that never ran, counted as passes
//   engine failure    — a file nothing opened, presented as assessed
//   stale results     — the previous run's numbers under this run's heading
//   complete scan     — the gate has to be able to CLEAR a run, or it is just a permanent warning
import { describe, it, expect } from 'vitest'
import {
  runIntegrity, integrityCaveat, skippedRulesOf, fileGapReason,
  COMPLETE, INCOMPLETE, UNAVAILABLE, STALE, PENDING,
} from './runIntegrity.js'

/** A manifest in the shape GET /scans/{sid}/manifest returns. */
const manifest = (over = {}) => ({
  scan_id: 'run-1',
  files_total: 2,
  rules_expected_total: 34,
  rules_checked_total: 34,
  rules_errored_total: 0,
  rules_not_checked_total: 0,
  rules_errored_unattributed_total: 0,
  rules_not_applicable_total: 106,
  completeness_pct: 100,
  complete: true,
  files: [
    { file: 'a.docx', file_status: 'analysed', reason: null, rules_expected: 17, rules_checked: 17,
      rules_errored: 0, rules_not_checked: 0, rules_errored_unattributed: 0,
      rules_not_applicable: 53, completeness_pct: 100, complete: true, rules: [] },
    { file: 'b.docx', file_status: 'analysed', reason: null, rules_expected: 17, rules_checked: 17,
      rules_errored: 0, rules_not_checked: 0, rules_errored_unattributed: 0,
      rules_not_applicable: 53, completeness_pct: 100, complete: true, rules: [] },
  ],
  ...over,
})

/** The same manifest with one file the engine could not open. */
const withBrokenFile = () => manifest({
  rules_checked_total: 17, rules_not_checked_total: 17, completeness_pct: 50, complete: false,
  files: [
    manifest().files[0],
    { file: 'broken.docx', file_status: 'error', reason: null, rules_expected: 17, rules_checked: 0,
      rules_errored: 0, rules_not_checked: 17, rules_errored_unattributed: 0,
      rules_not_applicable: 53, completeness_pct: 0, complete: false,
      rules: [{ rule_id: 'DOCX-ALT-001', status: 'NOT_CHECKED', finding_count: 0 },
              { rule_id: 'DOCX-TITLE-001', status: 'NOT_CHECKED', finding_count: 0 }] },
  ],
})

// ── a fully complete scan ─────────────────────────────────────────────────────────────────
describe('a run where every applicable check ran', () => {
  it('is complete and may be presented as a conformance result', () => {
    const v = runIntegrity(manifest(), { manifestScanId: 'run-1', currentScanId: 'run-1' })
    expect(v.status).toBe(COMPLETE)
    expect(v.conformanceClaimAllowed).toBe(true)
    expect(v.counts.completenessPct).toBe(100)
    expect(v.files).toEqual([])
  })

  it('carries no caveat, which is the only case that does not', () => {
    expect(integrityCaveat(runIntegrity(manifest()))).toBeNull()
  })

  it('does not count not-applicable rules against it', () => {
    const v = runIntegrity(manifest())
    expect(v.counts.notApplicable).toBe(106)
    expect(v.status).toBe(COMPLETE)
  })

  it('reports an unsupported-format file without treating it as affected', () => {
    const m = manifest({
      files_total: 3,
      files: [...manifest().files, {
        file: 'notes.txt', file_status: 'analysed', reason: 'unsupported_format',
        rules_expected: 0, rules_checked: 0, rules_errored: 0, rules_not_checked: 0,
        rules_errored_unattributed: 0, rules_not_applicable: 0, completeness_pct: 100,
        complete: true, rules: [] }],
    })
    const v = runIntegrity(m)
    // Nothing was owed for a .txt, so listing it as affected would send someone looking for a
    // fault that is not there.
    expect(v.status).toBe(COMPLETE)
    expect(v.counts.filesAffected).toBe(0)
  })
})

// ── an incomplete scan ────────────────────────────────────────────────────────────────────
describe('a run with checks that did not run', () => {
  it('refuses the conformance claim and says so in the headline', () => {
    const v = runIntegrity(withBrokenFile())
    expect(v.status).toBe(INCOMPLETE)
    expect(v.conformanceClaimAllowed).toBe(false)
    expect(v.headline).toMatch(/not a conformance result/i)
  })

  it('reports checked, expected and completeness as separate figures', () => {
    const v = runIntegrity(withBrokenFile())
    expect(v.counts).toMatchObject({ checked: 17, expected: 34, missing: 17, notChecked: 17 })
    expect(v.counts.completenessPct).toBe(50)
  })

  it('names the affected files rather than only counting them', () => {
    const v = runIntegrity(withBrokenFile())
    expect(v.files.map((f) => f.file)).toEqual(['broken.docx'])
    expect(v.counts.filesAffected).toBe(1)
  })

  it('does not list a file that was fully assessed', () => {
    expect(runIntegrity(withBrokenFile()).files.map((f) => f.file)).not.toContain('a.docx')
  })

  it('refuses even when the backend claims the run is complete', () => {
    // `complete` was structurally true for every scan this table ever held, so a reader that
    // believed it alone would have believed that too. The counts have to agree.
    const v = runIntegrity(manifest({
      complete: true, rules_checked_total: 30, rules_not_checked_total: 4,
      files: [manifest().files[0], { ...manifest().files[1], rules_checked: 13,
        rules_not_checked: 4, complete: false }],
    }))
    expect(v.status).toBe(INCOMPLETE)
    expect(v.conformanceClaimAllowed).toBe(false)
  })

  it('carries a caveat naming the arithmetic, for use beside a clean finding count', () => {
    // The damaging case: zero findings over a run that evaluated half its checks. Nothing on
    // screen looks wrong, which is exactly why the sentence has to travel with the result.
    expect(integrityCaveat(runIntegrity(withBrokenFile())))
      .toBe('17 of 34 applicable checks completed — not a conformance result.')
  })

  it('shows whether the manifest’s own numbers add up', () => {
    expect(runIntegrity(withBrokenFile()).counts.reconciles).toBe(true)
    const bad = runIntegrity(manifest({ rules_checked_total: 5, complete: false }))
    expect(bad.counts.reconciles).toBe(false)
  })
})

// ── engine failures ───────────────────────────────────────────────────────────────────────
describe('a run where the engine failed', () => {
  it('distinguishes an attempted-and-errored check from one that never ran', () => {
    const v = runIntegrity(manifest({
      complete: false, rules_checked_total: 31, rules_errored_total: 2, rules_not_checked_total: 1,
      files: [manifest().files[0], { ...manifest().files[1], rules_checked: 14, rules_errored: 2,
        rules_not_checked: 1, complete: false }],
    }))
    expect(v.counts.errored).toBe(2)
    expect(v.counts.notChecked).toBe(1)
    // Both are absence of evidence, and they are still not the same thing: one has a cause.
    expect(v.counts.missing).toBe(3)
  })

  it('explains a file the engine could not open', () => {
    expect(runIntegrity(withBrokenFile()).files[0].why)
      .toBe('The engine could not analyse this file.')
  })

  it('reports errors the engine counted but did not attribute to a rule', () => {
    const v = runIntegrity(manifest({
      complete: false, rules_checked_total: 32, rules_errored_unattributed_total: 2,
      files: [manifest().files[0], { ...manifest().files[1], rules_checked: 15,
        rules_errored_unattributed: 2, complete: false }],
    }))
    expect(v.counts.unattributed).toBe(2)
    expect(v.files[0].why).toBe('Some checks errored; which ones was not recorded.')
    expect(v.conformanceClaimAllowed).toBe(false)
  })

  it('names the skipped and errored rules of a file, and never the not-applicable ones', () => {
    const file = { rules: [
      { rule_id: 'DOCX-TITLE-001', status: 'NOT_CHECKED' },
      { rule_id: 'DOCX-ALT-001', status: 'ERROR' },
      { rule_id: 'DOCX-LANG-001', status: 'PASS' },
      { rule_id: 'PPTX-ALT-001', status: 'NOT_APPLICABLE' },
    ] }
    expect(skippedRulesOf(file)).toEqual([
      { ruleId: 'DOCX-ALT-001', status: 'ERROR' },
      { ruleId: 'DOCX-TITLE-001', status: 'NOT_CHECKED' },
    ])
  })

  it('describes the shape of a gap it has no recorded cause for, rather than guessing one', () => {
    // A wrong explanation is worse than none: it sends someone to fix the wrong thing.
    expect(fileGapReason({ reason: null, file_status: 'analysed', rules_not_checked: 3 }))
      .toBe('Some applicable checks did not run.')
    expect(fileGapReason({ reason: null, file_status: 'analysed' })).toBeNull()
  })

  it('says when a file has no recorded results at all', () => {
    expect(fileGapReason({ reason: 'no_manifest' }))
      .toBe('No check results were recorded for this file at all.')
  })
})

// ── stale results during a new run ────────────────────────────────────────────────────────
describe('results left on screen while a new run is going', () => {
  it('is stale, not complete, even when the manifest itself is perfect', () => {
    // The whole difficulty: the payload is internally consistent and describes a finished,
    // fully-covered run. There is nothing in it to notice.
    const v = runIntegrity(manifest(), { runInFlight: true })
    expect(v.status).toBe(STALE)
    expect(v.conformanceClaimAllowed).toBe(false)
  })

  it('withholds the counts rather than showing last run’s under this run’s heading', () => {
    expect(runIntegrity(manifest(), { runInFlight: true }).counts).toBeNull()
  })

  it('catches a manifest for a different scan than the one on screen', () => {
    // Survives a reload, where an "is something running" flag does not.
    const v = runIntegrity(manifest(), { manifestScanId: 'run-1', currentScanId: 'run-2' })
    expect(v.status).toBe(STALE)
    expect(v.detail).toMatch(/different run/i)
  })

  it('is stale before it is anything else, including while loading', () => {
    const v = runIntegrity(null, { loading: true, runInFlight: true })
    expect(v.status).toBe(STALE)
  })

  it('carries a caveat that does not read as a result', () => {
    expect(integrityCaveat(runIntegrity(manifest(), { runInFlight: true })))
      .toMatch(/superseded/i)
  })

  it('clears once the new run finishes and its own manifest arrives', () => {
    const v = runIntegrity(manifest({ scan_id: 'run-2' }),
                           { runInFlight: false, manifestScanId: 'run-2', currentScanId: 'run-2' })
    expect(v.status).toBe(COMPLETE)
  })
})

// ── the manifest could not be read ────────────────────────────────────────────────────────
describe('when coverage cannot be established at all', () => {
  it('is unavailable, and unavailable is not permission to claim conformance', () => {
    // The same failure the boot reads had (#1149/#1150): the absence of an answer defaulting to
    // the reassuring one.
    const v = runIntegrity(null, { error: new Error('network') })
    expect(v.status).toBe(UNAVAILABLE)
    expect(v.conformanceClaimAllowed).toBe(false)
    expect(v.readError).toBe('network')
  })

  it('treats a missing payload the same as a failed read', () => {
    expect(runIntegrity(null).status).toBe(UNAVAILABLE)
    expect(runIntegrity(undefined).conformanceClaimAllowed).toBe(false)
  })

  it('is pending while the read is in flight, and pending claims nothing either', () => {
    const v = runIntegrity(null, { loading: true })
    expect(v.status).toBe(PENDING)
    expect(v.conformanceClaimAllowed).toBe(false)
  })

  it('still says the findings on screen are real, so the panel is not read as data loss', () => {
    expect(runIntegrity(null, { error: new Error('x') }).detail).toMatch(/findings below are still/i)
  })
})

// ── the invariant ─────────────────────────────────────────────────────────────────────────
describe('the one rule this module exists to hold', () => {
  it('permits a conformance claim in exactly one state', () => {
    const cases = [
      runIntegrity(manifest()),                                   // complete
      runIntegrity(withBrokenFile()),                             // incomplete
      runIntegrity(manifest(), { runInFlight: true }),            // stale
      runIntegrity(null, { error: new Error('x') }),              // unavailable
      runIntegrity(null, { loading: true }),                      // pending
    ]
    expect(cases.filter((v) => v.conformanceClaimAllowed).map((v) => v.status)).toEqual([COMPLETE])
  })

  it('never returns a caveat only for the state that has earned silence', () => {
    expect(integrityCaveat(runIntegrity(manifest()))).toBeNull()
    for (const v of [runIntegrity(withBrokenFile()),
                     runIntegrity(manifest(), { runInFlight: true }),
                     runIntegrity(null, { error: new Error('x') }),
                     runIntegrity(null, { loading: true })]) {
      expect(integrityCaveat(v)).toBeTruthy()
    }
  })
})
