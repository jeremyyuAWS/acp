// The reviewer is told why THIS criterion matters, not why its principle matters.
//
// WHY THIS FILE EXISTS. `wcagWhy.js` carries one specific consequence line for each of the 87
// WCAG criteria and its header says it is "shown on every coverage tile". It was not shown
// anywhere: `git log -S wcagWhy` returned only the commit that added it, and no module in the
// tree ever imported it. Meanwhile `reviewCard.js` composed its "who is blocked" clause from a
// four-entry principle table, so every Perceivable finding — a missing alt text, a contrast
// failure, a scrambled reading order — explained itself to the reviewer with the same sentence.
//
// That is the quiet failure this repo keeps hitting: a module with tests-worth of content,
// merged, green, and mounted nowhere. It reads as shipped on any status list. So this file
// asserts BOTH halves — that the specific line is used, and that the generic one is no longer
// what a reviewer sees — because only the second half fails if someone reverts the wiring.
import { describe, expect, it } from 'vitest'

import { explainFinding, whyRecommendation } from './reviewCard.js'
import { WCAG } from './wcagCatalog.js'
import { WHY } from './wcagWhy.js'

const card = (sc) => ({ sc, problem: 'x', recommendation: null })
const explainOf = (sc) => explainFinding(card(sc)) || ''

describe('the impact clause is per criterion', () => {
  it('covers every criterion the product can report, in both directions', () => {
    // The fallback exists for safety, but nothing in the catalog should ever reach it.
    const scs = WCAG.map((c) => c.sc)
    expect(scs.filter((s) => !WHY[s])).toEqual([])
    expect(Object.keys(WHY).filter((s) => !scs.includes(s))).toEqual([])
    expect(scs).toHaveLength(87)
  })

  it('uses the specific line, not the principle sentence', () => {
    // 1.1.1's own words must reach the reviewer.
    const text = explainOf('1.1.1')
    expect(text).toContain('perceive images, charts or icons')
    expect(text).not.toContain('other assistive technology cannot access this content')
  })

  // Pull out JUST the impact clause — the text between "it currently fails, so " and the stop.
  // Comparing whole explanations does NOT work and this was caught by bite-checking rather than
  // by reading: the explanation embeds the criterion's name and requirement, which differ per
  // criterion regardless, so three explanations built from ONE shared principle clause still
  // compare unequal. The first version of the regression test below did exactly that and stayed
  // green with the wiring reverted — a check that could not fail.
  const clauseOf = (sc) => (explainOf(sc).match(/currently fails, so ([^.]+)\./) || [])[1] || null

  it('THE REGRESSION: criteria under one principle get DIFFERENT clauses', () => {
    // Under the principle table these three are all Perceivable and produced a byte-for-byte
    // identical clause. Reverting the wiring turns this red; the coverage test above would not
    // notice, because the data was always fine — only its use was missing.
    const clauses = ['1.1.1', '1.4.3', '1.3.2'].map(clauseOf)
    for (const c of clauses) expect(c).toBeTruthy()
    expect(new Set(clauses).size).toBe(3)
  })

  it('no two criteria in the whole catalog share a clause by accident', () => {
    // The sweep behind the three examples: 87 criteria, 87 distinct clauses. A future edit that
    // collapses any subset onto a shared sentence fails here.
    const seen = new Map()
    for (const sc of Object.keys(WHY)) {
      const c = clauseOf(sc)
      if (!c) continue
      if (seen.has(c)) throw new Error(`${sc} and ${seen.get(c)} share a clause: "${c}"`)
      seen.set(c, sc)
    }
    expect(seen.size).toBe(87)
  })

  it('joins grammatically for all 87 — no doubled stop, no mid-sentence capital', () => {
    // Every WHY entry is a standalone capitalised sentence; both call sites embed it after
    // "...so ". A naive join yields "so Screen-reader users can't perceive images..". Asserted
    // across the whole table rather than on one example, because the join is per-entry.
    const bad = []
    for (const sc of Object.keys(WHY)) {
      const t = explainOf(sc)
      if (!t) continue
      if (/\.\./.test(t)) bad.push(`${sc}: doubled stop`)
      if (/ so [A-Z]/.test(t)) bad.push(`${sc}: capital after "so"`)
    }
    expect(bad).toEqual([])
  })

  it('reaches the other consumer too', () => {
    // whyRecommendation() builds the card's `because` line from the same clause.
    const r = whyRecommendation({ sc: '1.1.1', problem: 'p', recommendation: 'a chart' })
    expect(r.because).toContain('perceive images, charts or icons')
    expect(r.because).not.toContain('other assistive technology cannot access this content')
  })

  it('an unknown criterion still gets a true, if unspecific, clause', () => {
    // The principle fallback must survive — a criterion outside the catalog must not produce
    // "undefined" in front of a reviewer.
    const t = explainFinding({ sc: '9.9.9', problem: 'x' }) || ''
    expect(t).not.toContain('undefined')
  })
})
