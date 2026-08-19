/**
 * "Every fix was applied automatically" — said over documents nobody could open.
 *
 * FROM PRODUCTION, 2026-08-19. A 22-document SharePoint scan. One drawer read
 *
 *     Could not analyse — file unreadable.        (Policy - Anticoagulation … .docx)
 *
 * while the Review queue on the same screen read
 *
 *     All clear — nothing needs your review.
 *     Nothing needs your review — every fix was applied automatically.
 *
 * Both counts behind those sentences were CORRECT: the HITL queue really was empty. The claim
 * drawn from them was not. A file that could not be READ had no fix applied to it, automatically
 * or otherwise — it was skipped, and the screen reported skipped as done.
 *
 * This is the house defect in a new costume (see `_fill_run_aggregate` in api/store.py, and the
 * 2026-07-30 scope incident): a true number, a false sentence, and the reassuring reading is the
 * wrong one. It matters more here than in most places, because "every fix was applied
 * automatically" is the sentence a compliance officer would quote to an auditor.
 *
 * WHAT IS AND IS NOT GUARDED HERE. The copy logic is pulled out into reviewQueueCopy.js so it can
 * be tested as behaviour rather than as a string in a 1,200-line component — Remediate mounts a
 * page's worth of dependencies, which is why its existing tests (remediateNavigation,
 * remediateCollapse) are source-level. So this file has two lanes, deliberately, the same shape
 * reviewQueueNaming.test.jsx uses: the unit cases prove the sentences are right, and the source
 * sweep proves Remediate actually calls them rather than keeping a hardcoded copy alongside.
 * Neither substitutes for the other.
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { unanalysableCount, reviewEmptyLine, reviewLeadLine } from './reviewQueueCopy.js'

const HERE = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(HERE, f), 'utf8')

// statusOf maps `status === 'error'` to 'unanalysable' — the record a file that was opened and
// failed to read leaves behind. Built through the same shapes the real rows have.
const unreadable = (file) => ({ file, status: 'error', score: null, issues: [] })
const fixed = (file) => ({ file, status: 'analysed', score: 100, compliant: true, issues: [] })

describe('counting what nobody could open', () => {
  it('counts only the files that failed to analyse', () => {
    expect(unanalysableCount([unreadable('a.docx'), fixed('b.docx'), fixed('c.pdf')])).toBe(1)
  })

  it('is zero, not a crash, when there are no files at all', () => {
    // The pre-scan and mid-scan states both land here, and a caveat that throws takes the page
    // with it — strictly worse than the sentence it was protecting.
    expect(unanalysableCount([])).toBe(0)
    expect(unanalysableCount(null)).toBe(0)
    expect(unanalysableCount(undefined)).toBe(0)
  })

  it('does not count a file that was merely never assessed', () => {
    // ADR 0020 Discover-only rows have no score and no status. "Nobody looked yet" and "we looked
    // and could not read it" are different facts; conflating them would put a scary caveat on
    // every fresh scan, and a caveat that fires always stops being read.
    expect(unanalysableCount([{ file: 'd.docx', score: null }])).toBe(0)
  })
})

describe('the empty-queue sentence', () => {
  it('still says the simple thing when every document was readable', async () => {
    const line = reviewEmptyLine([fixed('a.docx')], { totalHitl: 0 })
    expect(line).toMatch(/Nothing needs your review/)
    expect(line).toMatch(/every fix was applied automatically/)
  })

  it('does NOT claim every fix was applied when a document could not be read', () => {
    // THE case. This is the exact production state: queue empty, one unreadable file.
    const line = reviewEmptyLine([unreadable('a.docx'), fixed('b.docx')], { totalHitl: 0 })
    expect(line, 'the false claim survived').not.toMatch(/every fix was applied automatically/)
    expect(line).toMatch(/1 document could not be analysed/)
    expect(line).toMatch(/not remediated/)
  })

  it('pluralises, because "1 documents" reads as a bug and undermines the warning', () => {
    const line = reviewEmptyLine([unreadable('a.docx'), unreadable('b.docx')], { totalHitl: 0 })
    expect(line).toMatch(/2 documents could not be analysed/)
  })

  it('carries the caveat into the all-reviewed branch too', () => {
    // A reviewer who worked through the queue gets "All reviewed" — true of the queue, and just
    // as incomplete about the estate. The caveat belongs to the estate, so it cannot live in only
    // one branch of a ternary.
    const line = reviewEmptyLine([unreadable('a.docx')], { totalHitl: 3, acted: { approved: 3 } })
    expect(line).toMatch(/All reviewed/)
    expect(line).toMatch(/1 document could not be analysed/)
  })
})

describe('the section lead', () => {
  it('says "All clear" only when it is actually all clear', () => {
    expect(reviewLeadLine([fixed('a.docx')], 0)).toMatch(/All clear/)
  })

  it('withholds "All clear" while documents remain unread', () => {
    const line = reviewLeadLine([unreadable('a.docx')], 0)
    expect(line, '"All clear" over an unreadable document').not.toMatch(/All clear/)
    expect(line).toMatch(/could not be analysed/)
  })

  it('says nothing about the queue count — that sentence is not this one\'s job', () => {
    // The lead only renders in the zero-queue state; the populated state has its own sentence.
    expect(reviewLeadLine([fixed('a.docx')], 0)).not.toMatch(/\d+ finding/)
  })
})

describe('Remediate uses these, rather than keeping its own copy', () => {
  // A source sweep, because the unit cases above can only prove the helpers are right — not that
  // the page calls them. The original defect was a hardcoded string inside a ternary, and that is
  // exactly what would come back.
  const r = read('Remediate.jsx')

  it('imports the helpers', () => {
    expect(r).toMatch(/from '\.\/reviewQueueCopy\.js'/)
  })

  it('no longer hardcodes the unconditional claim', () => {
    expect(r, 'the hardcoded sentence is back in Remediate.jsx')
      .not.toMatch(/every fix was applied automatically/)
    expect(r, '"All clear" is hardcoded again')
      .not.toMatch(/All clear — nothing needs your review/)
  })
})
