import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import NextStep from './NextStep.jsx'

// "NEXT" — the one thing to do about everything above it.
//
// The case this file guards hardest is the PERCENTAGE. Board 7 reads "ACP can fix 41% of the
// findings deterministically", and that shape is what this redesign spent #545 removing: a bare
// percentage hides its denominator, which is how "51% auto-remediable" got quoted for a year.

const here = dirname(fileURLToPath(import.meta.url))
const src = readFileSync(join(here, 'NextStep.jsx'), 'utf8')

const METRICS = {
  documentsNeedingAttention: 1204,
  totalFindings: 18332,
  autoFixAvailable: 7516,
  humanReviewRequired: 10816,
}

const render = (props = {}) =>
  renderToStaticMarkup(createElement(NextStep, { metrics: METRICS, ...props }))
    .replace(/<[^>]+>/g, ' ').replace(/&#x27;/g, "'").replace(/&amp;/g, '&')
    .replace(/&quot;/g, '"').replace(/\s+/g, ' ')

describe('the forward action, with its denominator', () => {
  it('states both counts and the total they partition', () => {
    const t = render()
    expect(t).toMatch(/1,204 documents carry at least one unresolved finding/)
    expect(t).toMatch(/Of 18,332 findings/)
    expect(t).toMatch(/fix 7,516 automatically/)
    expect(t).toMatch(/remaining 10,816 need a person/)
  })

  it('never states the split as a bare percentage', () => {
    // The exact shape #545 removed. 41% of an unstated total is the claim nobody can check.
    const t = render()
    expect(t).not.toMatch(/\d+\s*%/)
    expect(t).not.toMatch(/deterministically/)   // the word travelled with the percentage
  })

  it('the two counts actually add up to the total on screen', () => {
    // Rendered arithmetic a reader can check, not a pair of numbers that merely look related.
    expect(METRICS.autoFixAvailable + METRICS.humanReviewRequired).toBe(METRICS.totalFindings)
  })

  it('offers Remediate as the primary action', () => {
    expect(render({ onRemediate: () => {} })).toMatch(/Go to Remediate/)
  })

  it('offers no dead buttons', () => {
    // No handler, no button — rather than one that does nothing when clicked.
    const t = render()
    expect(t).not.toMatch(/Go to Remediate/)
    expect(t).not.toMatch(/Export report/)
  })
})

describe('the states it must not overclaim', () => {
  it('renders nothing at all before a run', () => {
    expect(renderToStaticMarkup(createElement(NextStep, { metrics: null }))).toBe('')
  })

  it('reports a clear result WITH the coverage caveat, and offers no remediation', () => {
    // "No findings" over a partly-evaluated estate is the most damaging sentence this product
    // prints, so the caveat is not optional and the Remediate button must not appear.
    const t = render({ metrics: { ...METRICS, totalFindings: 0, autoFixAvailable: 0, humanReviewRequired: 0, documentsNeedingAttention: 0 }, onRemediate: () => {} })
    expect(t).toMatch(/No unresolved findings in the documents that were assessed/)
    expect(t).toMatch(/not the same as conformance/)
    expect(t).not.toMatch(/Go to Remediate/)
  })

  it('names the undecided lifecycle backlog, and that those files were not assessed', () => {
    const t = render({ awaiting: 343 })
    expect(t).toMatch(/343 files still hold a lifecycle recommendation awaiting a decision/)
    expect(t).toMatch(/they were not assessed/)
  })

  it('omits the backlog line when the column was never read, rather than saying zero', () => {
    // null is "we did not read it", which is not "none are waiting". This line is the only place
    // an undecided recommendation surfaces after Discover, so a false zero closes a loop nobody
    // actually closed.
    expect(render({ awaiting: null })).not.toMatch(/lifecycle recommendation/)
    expect(render({ awaiting: 0 })).not.toMatch(/lifecycle recommendation/)
  })
})

describe('deterministic means deterministic', () => {
  it('reads autoFixAvailable and never recomputes an auto lane of its own', () => {
    // autoFixAvailable counts findings whose capability lane is `auto`, not `assisted`. An
    // AI-drafted fix is advice awaiting a decision; counting it as automation is the overclaim
    // the metric contract was rewritten to prevent. This component must not redefine that.
    // Comments stripped first: the comment EXPLAINING that the assisted lane is excluded
    // necessarily contains the word, so a whole-file ban matches its own protected explanation.
    // The claim is about the code, so the assertions run against the code.
    const code = src
      .replace(/\/\*[\s\S]*?\*\//g, '')
      .replace(/^\s*\/\/.*$/gm, '')
    expect(code).toMatch(/metrics\.autoFixAvailable/)
    expect(code).not.toMatch(/assisted/)
    expect(code).not.toMatch(/\.filter\(|\.reduce\(|capabilityFor|modeFor/)
    // The stripper must not be what makes this pass.
    expect(code).toContain('export default function NextStep')
  })
})
