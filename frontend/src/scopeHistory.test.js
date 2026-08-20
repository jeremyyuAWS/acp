/**
 * "How big is this?" on the review step — answered with a measured number or with nothing.
 *
 * WHAT WAS NOT BUILT, AND WHY IT IS THE POINT. The obvious feature was a live pre-scan estimate:
 * walk the chosen folders, count, print. Two reasons it is absent:
 *
 *   1. Under ADR 0020 a Discover run IS the listing — it enumerates, persists an inventory, and
 *      opens nothing. An estimate is therefore not a cheap preview of an expensive operation, it
 *      is very nearly the operation, run twice.
 *   2. It would put a SECOND number for the same estate on screen, taken at a different moment
 *      under a different cap. Two numbers that can disagree, both correct, is exactly the
 *      2026-07-30 defect: "1 document" and "8 documents" six seconds apart, read as an estate
 *      that shrank.
 *
 * So this reports what THIS EXACT SCOPE covered last time — measured, stored, and frozen beside
 * its own boundary. The cases below are the ways that can go wrong quietly:
 *
 *   · matching a run whose boundary was NOT identical, so a number arrives captioned as this
 *     scope's when it belongs to a different one — the original defect with a longer fuse
 *   · rendering a NULL file count as 0, which claims the scope covered nothing
 *   · printing a truncated listing's count as a total, when it is only a floor
 *   · degrading the no-history case into something that reads like a small number
 */
import { describe, it, expect } from 'vitest'
import { lastRunOfScope, coverageSentence } from './scopeHistory.js'

const HR = { id: 'hr', name: 'HR' }
const FIN = { id: 'fin', name: 'Finance' }
const run = (over = {}) => ({
  id: 'r1', completed_at: '2026-08-18T10:00:00Z', source: 'drive', files: 240,
  scope: { kind: 'folder', folders: [HR] }, ...over,
})

describe('matching is on the WHOLE boundary', () => {
  it('finds the run whose frozen scope is identical', () => {
    const hit = lastRunOfScope([run()], { folders: [HR] }, 'drive')
    expect(hit.files).toBe(240)
    expect(hit.scanId).toBe('r1')
  })

  it('does not match a run with different folders', () => {
    expect(lastRunOfScope([run()], { folders: [FIN] }, 'drive')).toBe(null)
  })

  it('does not match a run with different criteria', () => {
    // A criteria scope changes which FORMATS are in scope, so it changes the count. Reporting one
    // scope's number under another's caption is the whole defect, one level down.
    const r = run({ scope: { folders: [HR], scan_scope: { '1.1.1': ['pdf'] } } })
    expect(lastRunOfScope([r], { folders: [HR] }, 'drive')).toBe(null)
    expect(lastRunOfScope([r], { folders: [HR], scan_scope: { '1.1.1': ['pdf'] } }, 'drive')).toBeTruthy()
  })

  it('does not match a carve-out that is no longer there', () => {
    const r = run({ scope: { folders: [HR], excluded: ['arch'] } })
    expect(lastRunOfScope([r], { folders: [HR] }, 'drive')).toBe(null)
    // …and matches when it IS, across the two shapes the two sides store it in (a run keeps bare
    // ids, the wizard keeps {id,name}).
    expect(lastRunOfScope([r], { folders: [HR], excluded: [{ id: 'arch', name: 'Archive' }] }, 'drive')).toBeTruthy()
  })

  it('does not match across source families', () => {
    expect(lastRunOfScope([run({ source: 'sharepoint' })], { folders: [HR] }, 'drive')).toBe(null)
  })

  it('takes the newest of several identical runs', () => {
    const hits = [run({ id: 'old', completed_at: '2026-08-01T10:00:00Z', files: 100 }),
                  run({ id: 'new', completed_at: '2026-08-18T10:00:00Z', files: 240 })]
    expect(lastRunOfScope(hits, { folders: [HR] }, 'drive').scanId).toBe('new')
  })
})

describe('what it refuses to report', () => {
  it('ignores a run with no file count rather than calling it zero', () => {
    // NULL files means the run never finished listing. Zero is a claim — "that scope covered
    // nothing" — and a stronger, more wrong one than saying nothing.
    expect(lastRunOfScope([run({ files: null })], { folders: [HR] }, 'drive')).toBe(null)
  })

  it('ignores a run with no recorded scope', () => {
    expect(lastRunOfScope([run({ scope: null })], { folders: [HR] }, 'drive')).toBe(null)
  })
})

describe('the sentence', () => {
  it('names the count, the scope and the date', () => {
    const s = coverageSentence(lastRunOfScope([run()], { folders: [HR] }, 'drive'), '18 Aug')
    expect(s).toMatch(/240 documents/)
    expect(s).toMatch(/this exact scope/)
    expect(s).toMatch(/18 Aug/)
  })

  it('says a truncated count is a floor, not a total', () => {
    const r = run({ scope: { folders: [HR], truncated: true } })
    const s = coverageSentence(lastRunOfScope([r], { folders: [HR] }, 'drive'))
    expect(s).toMatch(/hit its listing cap/)
    expect(s).toMatch(/the real total is higher/)
  })

  it('says plainly that there is no history, rather than implying a small number', () => {
    const s = coverageSentence(null)
    expect(s).toMatch(/No earlier run of this exact scope/)
    expect(s).toMatch(/determined when the scan starts/)
    expect(s, 'a numeral leaked into the no-history sentence').not.toMatch(/\d/)
  })
})
