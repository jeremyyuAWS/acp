// docs/assessment-capability-matrix.md is a DERIVED page, and until 2026-08-04 nothing checked
// that it still matched what it was derived from. It went stale for three weeks: 2.4.6 dropped
// 🟢→🟡 on docx (997b7d0) and html (0be9e00), and pdf 4.1.2 moved ⚪→🟡 (04b6213), all with the
// EST fixture in assessCoverage.test.js updated in the same commits — while the doc kept
// printing the superseded cells.
//
// The doc's own "Regenerating" section claimed EST guarded it. EST pins assessCoverage.js
// against itself and never opens this file, so the claim was false in the direction that costs
// most: it told the next reader not to bother checking. This test is the guard that was
// described but missing.
//
// It compares against the SAME builders the generator prints, so the doc, the generator and
// this test cannot form a triangle where two agree and the third is the one people read.
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

import { gridTable, totalsTable } from '../scripts/gen_assess_table.mjs'

const HERE = dirname(fileURLToPath(import.meta.url))
const DOC = resolve(HERE, '../../docs/assessment-capability-matrix.md')

const REGEN = 'run `node scripts/gen_assess_table.mjs` from frontend/ and paste both tables in'

/** The markdown table that starts with `header`, as trimmed lines, up to the first blank. */
function tableAfter(text, header) {
  const lines = text.split('\n')
  const start = lines.findIndex((l) => l.trim().startsWith(header))
  expect(start, `no table starting "${header}" in the matrix doc`).toBeGreaterThan(-1)
  const out = []
  for (let i = start; i < lines.length && lines[i].trim() !== ''; i++) out.push(lines[i].trim())
  return out
}

describe('docs/assessment-capability-matrix.md matches the logic it is derived from', () => {
  const doc = readFileSync(DOC, 'utf8')

  it('the 20-criterion grid is current', () => {
    expect(tableAfter(doc, '| SC | Criterion'), REGEN).toEqual(gridTable())
  })

  it('the per-format tallies are current', () => {
    expect(tableAfter(doc, '| Format | Assessable'), REGEN).toEqual(totalsTable())
  })

  it('the totals are the grid counted, not a second hand-maintained claim', () => {
    // Cheap independent arithmetic: every format's lanes must partition the 20. If the
    // generator itself were wrong, the two tests above would agree with it and still be wrong
    // together — this one does not go through gridTable().
    for (const row of totalsTable().slice(2)) {
      const c = row.split('|').map((s) => s.trim())
      const nums = [c[3], c[4], c[5], c[6], c[7]].map((v) => (v === '—' ? 0 : Number(v)))
      expect(nums.reduce((a, b) => a + b, 0), `${c[1]} lanes must sum to 20`).toBe(20)
      expect(c[2]).toBe(`**${nums[0] + nums[1]} / 20**`)   // assessable = 🟢 + 🟡
    }
  })

  it('does not claim the EST fixture guards this page', () => {
    // The specific false sentence that let the drift survive. Guarding against its return is
    // the point: a wrong claim about coverage is what stopped anyone looking for three weeks.
    expect(doc).not.toMatch(/fail that test until this snapshot and the fixture are both updated/)
  })
})
