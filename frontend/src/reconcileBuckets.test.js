import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import {
  reconcileBuckets, bucketsReconcile, bucketEquation,
  BUCKET_ORDER, BUCKET_PRECEDENCE, BUCKET_META,
} from './estateFunnel.js'
import { reconciliationInputs } from './reconciliationInputs.js'
import { analysedCount } from './docStatus.js'

// The load-bearing claim of the Overview report screen: every discovered file lands in exactly one
// bucket, and the buckets add up to the discovered total. These cases exist so that a partition
// which stops adding up FAILS here rather than shipping as a plausible row of numbers.

const here = dirname(fileURLToPath(import.meta.url))

// A whole-Drive estate: 12,408 discovered, 8,336 of them in an assessable format.
const INV = {
  discovered: 12408,
  assessment_eligible: 8336,
  truncated: false,
  by_format: { pdf: 3600, image: 3000, docx: 2900, xlsx: 1300, other: 1072, pptx: 536, av: 0 },
  by_status: { assessable: 8336, metadata_only: 3000, unsupported: 1072, excluded: 0 },
}

describe('reconcileBuckets — the partition', () => {
  it('returns null when there is no inventory to partition', () => {
    expect(reconcileBuckets(null)).toBe(null)
    expect(reconcileBuckets({})).toBe(null)
    expect(reconcileBuckets({ discovered: 0 })).toBe(null)
  })

  it('adds up to the discovered total when every bucket is measured', () => {
    // xlsx deselected (1,300), 343 flagged for lifecycle review, 47 unreadable, the rest assessed.
    const rec = reconcileBuckets(INV, {
      selectedFormats: ['docx', 'pdf', 'pptx', 'html'],
      lifecycleExcluded: 343,
      unreadable: 47,
      assessed: 8336 - 1300 - 343 - 47,
    })
    expect(rec.complete).toBe(true)
    expect(rec.total).toBe(12408)
    expect(rec.unaccounted).toBe(0)
    expect(rec.reconciles).toBe(true)
    expect(bucketsReconcile(INV, {
      selectedFormats: ['docx', 'pdf', 'pptx', 'html'],
      lifecycleExcluded: 343, unreadable: 47, assessed: 6646,
    })).toBe(true)
  })

  it('sums the buckets to exactly the number it claims — checked by adding the rows, not by trusting the field', () => {
    const rec = reconcileBuckets(INV, {
      selectedFormats: ['docx', 'pdf', 'pptx', 'html'], lifecycleExcluded: 343,
      unreadable: 47, assessed: 6646,
    })
    const byHand = rec.rows.reduce((n, r) => n + (r.value || 0), 0)
    expect(byHand).toBe(rec.total)
    expect(byHand).toBe(rec.discovered)
  })

  it('reports a SHORTFALL rather than absorbing it — a bucket is never the remainder', () => {
    // 500 assessment-eligible files simply never assessed (a cancelled run). Nothing may quietly
    // swell to cover them: the sum falls short and says so.
    const rec = reconcileBuckets(INV, {
      selectedFormats: ['docx', 'pdf', 'pptx', 'html'],
      lifecycleExcluded: 343, unreadable: 47, assessed: 6646 - 500,
    })
    expect(rec.reconciles).toBe(false)
    expect(rec.unaccounted).toBe(500)
    expect(rec.overlap).toBe(false)
  })

  it('reports an OVERLAP when the buckets double-count', () => {
    // The lifecycle/type pair is the one overlap the aggregates cannot rule out (a flagged file in
    // a deselected type is in both marginals). It must surface as arithmetic, not be clamped away.
    const rec = reconcileBuckets(INV, {
      selectedFormats: ['docx', 'pdf', 'pptx', 'html'],
      lifecycleExcluded: 343, unreadable: 47, assessed: 6646 + 200,
    })
    expect(rec.overlap).toBe(true)
    expect(rec.unaccounted).toBe(-200)
    expect(rec.reconciles).toBe(false)
  })

  it('an unmeasured bucket is null, never a zero, and never counted in the total', () => {
    // No lifecycle counter on the run: "nothing was flagged" and "nobody recorded whether anything
    // was flagged" are opposite claims and the reassuring one must not be the default.
    const rec = reconcileBuckets(INV, {
      selectedFormats: ['docx', 'pdf', 'pptx', 'html'], unreadable: 47, assessed: 6646,
    })
    const lifecycle = rec.rows.find((r) => r.key === 'lifecycle')
    expect(lifecycle.value).toBe(null)
    expect(lifecycle.measured).toBe(false)
    expect(lifecycle.share).toBe(null)
    expect(rec.complete).toBe(false)
    expect(rec.reconciles).toBe(false)
    expect(rec.total).toBe(12408 - 343)
  })

  it('distinguishes "no type narrowing" (a measured zero) from "scope not recorded" (unknown)', () => {
    const unrestricted = reconcileBuckets(INV, { selectedFormats: null })
    expect(unrestricted.rows.find((r) => r.key === 'type').value).toBe(0)

    const unknown = reconcileBuckets(INV, {})
    expect(unknown.rows.find((r) => r.key === 'type').value).toBe(null)
  })

  it('prefers discovery’s own drop count over the by-format derivation', () => {
    // scope.skipped_out_of_scope was counted by the process that did the dropping; the derivation
    // is the fallback. A direct measurement wins.
    const rec = reconcileBuckets(INV, { typeNotSelected: 1234, selectedFormats: ['docx'] })
    expect(rec.rows.find((r) => r.key === 'type').value).toBe(1234)
  })

  it('counts no-test from the eligible split and never lets it read negative', () => {
    const rec = reconcileBuckets(INV, {})
    expect(rec.rows.find((r) => r.key === 'no_test').value).toBe(12408 - 8336)
    // A stale summary claiming more eligible than discovered clamps to 0 rather than going negative.
    const stale = reconcileBuckets({ discovered: 10, assessment_eligible: 99 }, {})
    expect(stale.rows.find((r) => r.key === 'no_test').value).toBe(0)
  })

  it('falls back to by_status.assessable when assessment_eligible is absent', () => {
    const rec = reconcileBuckets({ discovered: 100, by_status: { assessable: 60 } }, {})
    expect(rec.rows.find((r) => r.key === 'no_test').value).toBe(40)
  })

  it('leaves no-test unmeasured when the summary carries neither eligible count', () => {
    const rec = reconcileBuckets({ discovered: 100 }, {})
    expect(rec.rows.find((r) => r.key === 'no_test').value).toBe(null)
  })

  it('rejects non-measurements — NaN, negatives and strings are unknown, not counts', () => {
    const rec = reconcileBuckets(INV, { assessed: NaN, unreadable: -3, lifecycleExcluded: '343' })
    expect(rec.rows.find((r) => r.key === 'assessed').value).toBe(null)
    expect(rec.rows.find((r) => r.key === 'unreadable').value).toBe(null)
    expect(rec.rows.find((r) => r.key === 'lifecycle').value).toBe(null)
  })

  it('carries the truncation flag through, so a floor is never presented as a total', () => {
    expect(reconcileBuckets({ ...INV, truncated: true }, {}).truncated).toBe(true)
    expect(reconcileBuckets(INV, {}).truncated).toBe(false)
  })

  it('reports overrides as a footnote count, never as a sixth bucket', () => {
    const rec = reconcileBuckets(INV, { lifecycleExcluded: 343, lifecycleOverridden: 9 })
    expect(rec.overridden).toBe(9)
    expect(rec.rows).toHaveLength(BUCKET_ORDER.length)
    expect(rec.rows.map((r) => r.key)).toEqual(BUCKET_ORDER)
  })

  it('a share is a fraction of the discovered total — the denominator the panel prints', () => {
    const rec = reconcileBuckets(INV, { assessed: 6204 })
    expect(rec.rows.find((r) => r.key === 'assessed').share).toBeCloseTo(0.5, 6)
  })
})

describe('bucketEquation', () => {
  it('writes out only the measured buckets', () => {
    const rec = reconcileBuckets(INV, {
      selectedFormats: ['docx', 'pdf', 'pptx', 'html'], lifecycleExcluded: 343,
      unreadable: 47, assessed: 6646,
    })
    expect(bucketEquation(rec)).toBe('6,646 + 343 + 1,300 + 4,072 + 47')
  })

  it('omits an unmeasured bucket rather than writing it as 0', () => {
    const rec = reconcileBuckets(INV, { selectedFormats: null, assessed: 100 })
    const eq = bucketEquation(rec)
    expect(eq).toBe('100 + 0 + 4,072')       // type is a MEASURED zero; lifecycle/unreadable are absent
    expect(eq.split(' + ')).toHaveLength(3)
  })

  it('is null when nothing at all was measured', () => {
    expect(bucketEquation(reconcileBuckets({ discovered: 5 }, {}))).toBe(null)
    expect(bucketEquation(null)).toBe(null)
  })
})

describe('bucketsReconcile mirrors ageBandsReconcile', () => {
  it('is true when there is nothing to check', () => {
    expect(bucketsReconcile(null)).toBe(true)
    expect(bucketsReconcile({ discovered: 0 })).toBe(true)
  })

  it('is false the moment the rows stop adding up', () => {
    expect(bucketsReconcile(INV, { selectedFormats: null, lifecycleExcluded: 0, unreadable: 0, assessed: 1 }))
      .toBe(false)
  })
})

describe('reconciliationInputs — the run-side facts', () => {
  const file = (over) => ({ file: 'a.docx', score: 90, issues: [], ...over })

  it('splits assessed from unreadable so neither claims the same file', () => {
    const files = [
      file({ score: 90 }),                                 // clean
      file({ score: 40, issues: [{ severity: 'SERIOUS' }] }), // issues
      file({ status: 'error', score: null }),              // unanalysable
      file({ score: null }),                               // never assessed
    ]
    const o = reconciliationInputs({}, files)
    expect(o.assessed).toBe(2)
    expect(o.unreadable).toBe(1)
  })

  it('keeps the coverage funnel’s identity: assessed + unreadable === analysedCount', () => {
    // The funnel's "Assessed" stage is analysedCount. If this split ever drifts from it the two
    // panels on the same screen begin describing different estates.
    const files = [
      file({ score: 90 }), file({ status: 'error', score: null }),
      file({ status: 'uncertain', score: null }), file({ score: null }),
    ]
    const o = reconciliationInputs({}, files)
    expect(o.assessed + o.unreadable).toBe(analysedCount(files))
  })

  it('passes an absent lifecycle counter through as absent, not as zero', () => {
    const o = reconciliationInputs({ scope: {} }, [])
    expect(o.lifecycleExcluded).toBeUndefined()
    expect(reconcileBuckets(INV, o).rows.find((r) => r.key === 'lifecycle').value).toBe(null)
  })

  it('reads discovery’s own skipped_out_of_scope as the type drop', () => {
    expect(reconciliationInputs({ scope: { skipped_out_of_scope: 47 } }, []).typeNotSelected).toBe(47)
  })

  it('reads the frozen scan scope, so a later re-scope cannot rewrite this run’s split', () => {
    const o = reconciliationInputs({ scan_scope: { '1.1.1': ['docx', 'pdf'], '1.3.1': ['pdf'] } }, [])
    expect(o.selectedFormats).toEqual(['docx', 'pdf'])
    // null scan_scope is frozenScope's documented "no restriction", not "nothing selected".
    expect(reconciliationInputs({}, []).selectedFormats).toBe(null)
  })

  it('survives a null run and a null file list', () => {
    const o = reconciliationInputs(null, null)
    expect(o.assessed).toBe(0)
    expect(o.unreadable).toBe(0)
    expect(o.selectedFormats).toBe(null)
  })
})

// ── Source-level pins — the parts of the contract a DOM assertion cannot see ──────────────────
describe('the module states its own rules', () => {
  const src = readFileSync(join(here, 'estateFunnel.js'), 'utf8')

  it('declares the precedence chain, lifecycle first', () => {
    expect(BUCKET_PRECEDENCE[0]).toBe('lifecycle')
    expect(BUCKET_PRECEDENCE.indexOf('lifecycle')).toBeLessThan(BUCKET_PRECEDENCE.indexOf('type'))
    // Same five keys in both orders — a bucket that exists in one and not the other is a bucket
    // whose precedence nobody decided.
    expect([...BUCKET_PRECEDENCE].sort()).toEqual([...BUCKET_ORDER].sort())
  })

  it('never describes a lifecycle recommendation as a completed archive or deletion', () => {
    // The system writes a TAG. Saying "archived" or "deleted" sends somebody looking for a file
    // that is still exactly where they left it.
    const note = BUCKET_META.lifecycle.note
    expect(note).toMatch(/recommendation/i)
    expect(note).toMatch(/no file was moved or deleted/i)
    expect(note).not.toMatch(/\bhave been (archived|deleted)\b/i)
  })

  it('does not derive any bucket as the remainder of the others', () => {
    // A residual bucket makes the reconciliation trivially true. `discovered - <bucket sum>` must
    // appear only as `unaccounted`, which is the REPORT of a mismatch, never a value.
    expect(src).toMatch(/const unaccounted = discovered - total/)
    expect(src).not.toMatch(/assessed:\s*discovered\s*-/)
  })

  it('keeps the age-band contract intact for the cross-language pin', () => {
    // tests/test_age_band_contract_sync.py parses these two constants out of this file.
    expect(src).toMatch(/const AGE_ORDER\s*=\s*\[/)
    expect(src).toMatch(/const AGE_LABEL\s*=\s*\{[\s\S]*?\n\}/)
  })
})
