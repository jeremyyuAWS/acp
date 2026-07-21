import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { measuredReviewTime, fmtReviewMs, REVIEW_TIME_BASIS } from './reviewerTime.js'

const here = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(here, f), 'utf8')
// Only executable lines: a comment explaining a deleted fabrication is not a fabrication.
const code = (f) => read(f).split('\n').filter((l) => !l.trim().startsWith('//')).join('\n')

describe('no screen claims a time saving', () => {
  // "est. savings 12.4 hrs" was the largest number on the review screen. It was
  // manualMin - remediateMin, and manualMin was `findings * 35 + 20` — a constant someone
  // typed. Nobody ever timed a document being remediated by hand, so there was no baseline
  // to have saved anything against.
  for (const f of ['Remediate.jsx', 'RiskScore.jsx', 'scanReport.js']) {
    it(`${f} neither computes nor renders a saving`, () => {
      expect(code(f)).not.toMatch(/savedMin|savedHrs|est\. savings|saves ≈|vs\. manual/)
    })
  }

  it('sim.js still computes savedMin for nobody — no consumer may reappear', () => {
    // Left in place (it is the recommender's own arithmetic, not a rendered claim), so this
    // asserts the *absence of consumers* rather than the absence of the field.
    const consumers = ['Remediate.jsx', 'RiskScore.jsx', 'scanReport.js', 'pdfReport.js',
                       'FileDrawer.jsx', 'Publish.jsx', 'Overview.jsx']
      .filter((f) => { try { return /\.savedMin|savedMin:/.test(code(f)) } catch { return false } })
    expect(consumers).toEqual([])
  })
})

describe('durations that survive are labelled as estimates', () => {
  it('RiskScore renders effort through fmtEffort, not a bare {n}h', () => {
    const c = code('RiskScore.jsx')
    // Effort is now grounded on the capability-derived finding split (estimateEffortMin), not the
    // SIM-only rec.remediateMin — but it must STILL flow through fmtEffort ("est.") and carry the
    // EFFORT_BASIS tooltip so it can never read as a measurement.
    expect(c).toMatch(/fmtEffort\(effortMin\)/)
    expect(c).toMatch(/estimateEffortMin\(/)
    expect(c).not.toMatch(/rec\.remediateMin|\{effortH\}h|remediateMin \|\| 0\) \/ 60/)
    expect(c).toMatch(/title=\{EFFORT_BASIS\}/)
  })

  it('the Remediate plan cards drop the bare "~" prefix for the est. formatter', () => {
    const c = code('Remediate.jsx')
    expect(c).not.toMatch(/~\$\{hrs\(/)
    expect(c).toMatch(/fmtEffort\(b\.min\)/)
  })
})

describe('reviewer time is measured or it is not shown', () => {
  it('formats only real millisecond readings', () => {
    expect(fmtReviewMs(8000)).toBe('8s')
    expect(fmtReviewMs(84000)).toBe('1m 24s')
    expect(fmtReviewMs(0)).toBeNull()        // no review has been timed
    expect(fmtReviewMs(null)).toBeNull()
    expect(fmtReviewMs(-5)).toBeNull()
    expect(fmtReviewMs('12s')).toBeNull()
  })

  it('says nothing until enough reviews have actually happened', () => {
    expect(measuredReviewTime(null)).toBeNull()
    expect(measuredReviewTime({})).toBeNull()
    expect(measuredReviewTime({ reviewed: 0, avg_review_ms: 0 })).toBeNull()
    // One decision is a number, not an average.
    expect(measuredReviewTime({ reviewed: 1, avg_review_ms: 9000 })).toBeNull()
    // Reviews recorded before review_ms was captured land here: count without timing.
    expect(measuredReviewTime({ reviewed: 40, avg_review_ms: null })).toBeNull()
  })

  it('reports the average once it is real', () => {
    expect(measuredReviewTime({ reviewed: 7, avg_review_ms: 23800 }))
      .toEqual({ avg: '24s', reviewed: 7 })
  })

  it('declares the measurement as its basis, and names the column it came from', () => {
    expect(REVIEW_TIME_BASIS).toMatch(/^Measured:/)
    expect(REVIEW_TIME_BASIS).toMatch(/review_ms/)
  })

  it('is sourced from the backend, not from sim.js', () => {
    const c = code('Remediate.jsx')
    expect(c).toMatch(/getHitlAnalytics\(runId\)/)
    // Anchored to the setter: `if (!runId || SIM) return` appears elsewhere in this file, so a
    // bare match on it would pass even with the SIM guard deleted from the review-stats effect.
    expect(c).toMatch(/if \(!runId \|\| SIM\) \{ setReviewStats\(null\); return \}/)
  })
})
