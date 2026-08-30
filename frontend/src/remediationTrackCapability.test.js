// The review card's "can ACP fix this?" badge must come from the PROVEN table, per format.
//
// WHY THIS FILE EXISTS. capability.js's header records that the frontend "used to carry THREE
// disagreeing versions of this fact", names two that were consolidated into it, and says "Both
// should read from here". remediationTrack.js was the third, and it was the one the review card
// reads for its badge and its primary action — so the most user-visible copy was the one still
// answering from hand-maintained sets keyed on the criterion alone.
//
// Measured across all 122 in-scope pairs before the change: 59 disagreed with
// api/remediation_capability.REMEDIATION, and 24 of those OVERSTATED — the badge promised
// "Auto Applied" or "Review Suggested" for a pair the backend records as `human`. A reviewer was
// told a fix was coming for something no lane can fix.
//
// The cause is structural, not a stale entry: eleven criteria have different lanes in different
// formats, so no criterion-only table can be right about them. Those are the cases below.
import { describe, expect, it } from 'vitest'

import { CAPABILITY_FALLBACK } from './capability.js'
import { remediationTrack } from './remediationTrack.js'

describe('remediationTrack reads the per-format capability table', () => {
  it('agrees with the table on every in-scope pair', () => {
    // The whole finding, asserted as one sweep rather than a handful of examples: any future
    // divergence between the badge and the proven lane fails here, whichever direction it goes.
    const wrong = []
    for (const [fmt, scs] of Object.entries(CAPABILITY_FALLBACK)) {
      for (const [sc, lane] of Object.entries(scs)) {
        const got = remediationTrack({ sc, fmt }).track
        if (got !== lane) wrong.push(`${sc} ${fmt}: table=${lane} badge=${got}`)
      }
    }
    expect(wrong).toEqual([])
  })

  it('never promises a fix for a pair the backend routes to a human', () => {
    // The harmful direction, called out separately so a regression reads as what it is.
    const overstated = []
    for (const [fmt, scs] of Object.entries(CAPABILITY_FALLBACK)) {
      for (const [sc, lane] of Object.entries(scs)) {
        if (lane !== 'human') continue
        const got = remediationTrack({ sc, fmt }).track
        if (got !== 'human') overstated.push(`${sc} ${fmt} → ${got}`)
      }
    }
    expect(overstated).toEqual([])
  })

  it('gives one criterion different answers in different formats', () => {
    // 2.4.4 link purpose: the Office formats have a proposer and a writer; PDF does not, and
    // api/remediate_pdf.py says so in terms. A format-blind model answered "assisted" for both.
    expect(remediationTrack({ sc: '2.4.4', fmt: 'docx' }).track).toBe('assisted')
    expect(remediationTrack({ sc: '2.4.4', fmt: 'pdf' }).track).toBe('human')

    // 1.4.1 use of colour: assisted on docx, human everywhere else it is in scope.
    expect(remediationTrack({ sc: '1.4.1', fmt: 'docx' }).track).toBe('assisted')
    expect(remediationTrack({ sc: '1.4.1', fmt: 'pptx' }).track).toBe('human')
  })

  it('treats a criterion absent from a format as human, not as fixable', () => {
    // capability.js: "A pair absent from a format's map is out of scope for that format and
    // treated as human." A criterion a format is not even assessed on cannot have a fix lane,
    // and the old model badged several of these "Auto Applied".
    expect(CAPABILITY_FALLBACK.pptx['1.4.8']).toBeUndefined()
    expect(remediationTrack({ sc: '1.4.8', fmt: 'pptx' }).track).toBe('human')
  })

  it('accepts the live capability map in preference to the bundled mirror', () => {
    // GET /capability is the running deployment's answer; the bundle is the offline default.
    const live = { docx: { '2.4.4': 'auto' } }
    expect(remediationTrack({ sc: '2.4.4', fmt: 'docx', capability: live }).track).toBe('auto')
  })

  it('is case-insensitive about the format, because the card upper-cases it', () => {
    // reviewCard.js derives fmt from the filename and upper-cases it ("DOCX"); the table is
    // lower-cased. Getting this wrong would silently send every card down the no-format path,
    // which still returns a plausible answer — the failure would be invisible.
    expect(remediationTrack({ sc: '2.4.4', fmt: 'PDF' }).track).toBe('human')
    expect(remediationTrack({ sc: '2.4.4', fmt: 'pdf' }).track).toBe('human')
  })

  it('still demotes a low-confidence auto fix rather than claiming it was applied', () => {
    expect(remediationTrack({ sc: '1.4.3', fmt: 'docx' }).track).toBe('auto')
    expect(remediationTrack({
      sc: '1.4.3', fmt: 'docx', confidence: { level: { key: 'low' } },
    }).track).toBe('assisted')
  })

  it('falls back to the criterion-only model when the format is unknown', () => {
    // reviewCard falls back to "DOC" for a file with no extension, and other callers pass no
    // format at all. Defaulting those to human would badge them "Human Required" on no
    // evidence, so the old heuristic is kept for exactly this case.
    expect(remediationTrack({ sc: '1.4.3' }).track).toBe('auto')
    expect(remediationTrack({ sc: '1.4.3', fmt: 'DOC' }).track).toBe('auto')
    expect(remediationTrack({ sc: '2.1.1' }).track).toBe('human')
  })
})
