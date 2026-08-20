/**
 * "Last modified" on Discover — and the two ways a distribution lies quietly.
 *
 * The counts come from `summarize()`, which bands every discovered file (api/estate_inventory.py).
 * The frontend's job is not to compute them; it is to refuse to draw them when they are not there,
 * and to keep them in an order that means something.
 *
 * ONE — a missing field is not a measured zero. `by_age` is absent from every report written
 * before the aggregation shipped. Rendering that as five bars of zero would state, in a chart, that
 * an estate nobody measured contains nothing old. Same family as #479/#483/#491/#502/#514: absence
 * of evidence drawn as evidence of absence.
 *
 * TWO — ordinal buckets must not be sorted by size. `compositionRows` sorts largest-first, which is
 * right for formats and destroys a distribution: "under 1 year, over 5 years, 1–3 years" is not a
 * shape anybody can read.
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { ageRows, ageBandsReconcile, estateModel } from './estateFunnel.js'

const HERE = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(HERE, f), 'utf8')

const INV = {
  discovered: 100,
  assessment_eligible: 60,
  by_age: { lt_1y: 10, y1_3: 20, y3_5: 30, gt_5y: 35, unknown: 5 },
}

describe('a scan with no age data', () => {
  it('returns null rather than a row of zeros', () => {
    // THE case. Every report written before the aggregation shipped has no `by_age`.
    expect(ageRows({ discovered: 100 }), 'a missing field was drawn as measured zeros').toBeNull()
    expect(ageRows({ discovered: 100, by_age: {} })).toBeNull()
    expect(ageRows(null)).toBeNull()
  })

  it('does not block the rest of the coverage model', () => {
    const m = estateModel({ discovered: 100, assessment_eligible: 60 }, {})
    expect(m.age).toBeNull()
    expect(m.discovered).toBe(100)
    expect(m.funnel.length).toBeGreaterThan(0)
  })
})

describe('the bands that are there', () => {
  it('are ordered youngest to oldest, with no-date last', () => {
    // NOT sorted by count. These are ordinal buckets; re-ordering them by size destroys the only
    // thing a distribution is for.
    expect(ageRows(INV).map((r) => r.key)).toEqual(['lt_1y', 'y1_3', 'y3_5', 'gt_5y', 'unknown'])
  })

  it('keeps that order even when the counts would sort differently', () => {
    const rows = ageRows({ discovered: 6, by_age: { gt_5y: 1, lt_1y: 5 } })
    expect(rows.map((r) => r.key), 'the bands were sorted by size').toEqual(['lt_1y', 'gt_5y'])
  })

  it('omits a band the scan did not report, rather than inventing a zero', () => {
    const rows = ageRows({ discovered: 5, by_age: { lt_1y: 5 } })
    expect(rows).toHaveLength(1)
  })

  it('shows "no date recorded" as its own band', () => {
    // The caveat on every other bar. Hiding it would make the rest look complete.
    const r = ageRows(INV).find((x) => x.key === 'unknown')
    expect(r.label).toMatch(/No date/i)
    expect(r.value).toBe(5)
  })

  it('carries counts through untouched', () => {
    expect(ageRows(INV).map((r) => r.value)).toEqual([10, 20, 30, 35, 5])
  })
})

describe('do the bands add up', () => {
  it('reconciles when they sum to discovered', () => {
    expect(ageBandsReconcile(INV)).toBe(true)      // 10+20+30+35+5 = 100
  })

  it('does NOT reconcile when they fall short', () => {
    // Built to sum, so a mismatch means the two numbers came from different places — a stale
    // report, or a summary that banded a subset. The panel says so rather than letting a reader
    // add up bars that never reach the headline count.
    expect(ageBandsReconcile({ discovered: 100, by_age: { lt_1y: 10 } })).toBe(false)
  })

  it('is vacuously true when there is no age data to disagree with', () => {
    expect(ageBandsReconcile({ discovered: 100 })).toBe(true)
  })
})

describe('the panel actually consults this', () => {
  const src = read('EstateCoverage.jsx')

  it('renders nothing at all when there is no age data', () => {
    // The gate, not a fallback: `{m.age && (...)}`.
    expect(src).toMatch(/\{m\.age && \(/)
  })

  it('draws the bands with the shared Bars primitive', () => {
    // Bars renders items in the GIVEN order and treats a null value as "not measured" rather than
    // as zero — both properties this panel needs, which is why there is no new chart component.
    expect(src).toMatch(/<Bars items=\{m\.age\}/)
  })

  it('says the bands are a floor when the listing was truncated', () => {
    expect(src).toMatch(/m\.truncated && 'The listing hit its cap/)
  })

  it('warns when the bands do not reconcile', () => {
    expect(src).toMatch(/!m\.ageReconciles/)
  })

  it('says the distribution spans the whole estate, not the assessable subset', () => {
    expect(src).toMatch(/not only the assessable ones/)
  })
})
