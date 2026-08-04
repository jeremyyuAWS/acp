// Emit both tables of docs/assessment-capability-matrix.md from the live assessment logic.
//
// This used to be a snippet pasted inside the doc it generates, which had two costs: the
// snippet covered only the 20-criterion grid (the "Assessable totals" table underneath was
// hand-maintained, and drifted), and a snippet cannot be imported by a test. It is a file now
// so that frontend/src/matrixDoc.test.js can call the same builders the doc is made from —
// a generator and its guard that disagree would just be a second source of truth.
//
//   node scripts/gen_assess_table.mjs      (from frontend/)
import { assessmentIn, DOCUMENTS_20 } from '../src/assessCoverage.js'
import { WCAG } from '../src/wcagCatalog.js'

const NAME = Object.fromEntries(WCAG.map((c) => [c.sc, c.name]))
const LVL = Object.fromEntries(WCAG.map((c) => [c.sc, c.level]))

export const FMTS = ['docx', 'xlsx', 'pptx', 'pdf', 'html']
export const SYM = { auto: '🟢', review: '🟡', human: '🔴', na: '⚪', gap: '🟠', at: '🔵' }

/** The 20-criterion document core, as markdown rows. */
export function gridTable() {
  const out = [
    `| SC | Criterion | Lvl | ${FMTS.map((f) => f.toUpperCase()).join(' | ')} |`,
    `|----|-----------|:---:|${FMTS.map(() => ':----:').join('|')}|`,
  ]
  for (const sc of DOCUMENTS_20) {
    const cells = FMTS.map((f) => SYM[assessmentIn(sc, f)])
    out.push(`| ${sc} | ${NAME[sc]} | ${LVL[sc]} | ${cells.join(' | ')} |`)
  }
  return out
}

/** Per-format tallies. Derived from the same assessmentIn() call as the grid, never counted
 *  by hand — the two tables cannot disagree if only one of them is authored. */
export function totalsTable() {
  const out = [
    '| Format | Assessable | 🟢 auto | 🟡 review | 🔴 human | ⚪ N/A | 🔵 AT |',
    '|--------|:----------:|:------:|:--------:|:-------:|:-----:|:-----:|',
  ]
  for (const f of FMTS) {
    const lanes = DOCUMENTS_20.map((sc) => assessmentIn(sc, f))
    const n = (x) => lanes.filter((l) => l === x).length
    const at = n('at')
    out.push(
      `| ${f.toUpperCase()} | **${n('auto') + n('review')} / ${DOCUMENTS_20.length}** | ` +
      `${n('auto')} | ${n('review')} | ${n('human')} | ${n('na')} | ${at || '—'} |`
    )
  }
  return out
}

// Only print when run directly, so importing this from a test stays silent.
if (import.meta.url === `file://${process.argv[1]}`) {
  console.log(gridTable().join('\n'))
  console.log('')
  console.log(totalsTable().join('\n'))
}
